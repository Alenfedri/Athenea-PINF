"""Edición e higiene del dato de una sesión de la banda pectoral: recortar, corregir artefactos R-R,
dividir y fusionar. Las funciones puras trabajan con ``Sesion`` (series en memoria) y recalculan las métricas;
las ``aplicar_*`` persisten el cambio en SQLite sin alterar el esquema (solo UPDATE/DELETE/INSERT de la cuenta activa)."""

from __future__ import annotations

import statistics
import uuid
from dataclasses import dataclass, field, replace
from typing import Optional, Sequence

import numpy as np

from domain.modelos import Medicion
from domain.zonas_actividad import FC_MAX_REFERENCIA, repartir_zonas
from services import calculos_fisiologicos as calc
from services.metricas_avanzadas import PESOS_TRIMP

UMBRAL_ARTEFACTO = 0.20
VENTANA_MEDIANA = 5


@dataclass(frozen=True)
class Sesion:
    inicio_ts: int
    fin_ts: int
    ts: tuple[int, ...] = ()
    bpm: tuple[float, ...] = ()
    rpm: tuple[Optional[float], ...] = ()
    rr_ms: tuple[float, ...] = ()
    rr_t0: Optional[float] = None            # instante (s Unix) del primer R-R; None → inicio_ts

    @property
    def rr_t(self) -> list[float]:
        """Instante de fin de cada R-R (s Unix), acumulando desde ``rr_t0``."""
        t = float(self.inicio_ts if self.rr_t0 is None else self.rr_t0)
        salida = []
        for r in self.rr_ms:
            t += r / 1000.0
            salida.append(t)
        return salida


@dataclass(frozen=True)
class MetricasSesion:
    duracion_s: int
    bpm_medio: Optional[float]
    bpm_max: Optional[float]
    zonas_s: Optional[tuple[float, ...]]
    trimp: Optional[float]
    kcal: Optional[float]


def _mediciones(s: Sesion) -> list[Medicion]:
    return [Medicion(i, str(i), t, b, r, None, None, "ACTIVIDAD", None)
            for i, (t, b, r) in enumerate(zip(s.ts, s.bpm, s.rpm))]


def metricas(s: Sesion, perfil: Optional[calc.PerfilFisiologico] = None,
             fc_max: float = FC_MAX_REFERENCIA) -> MetricasSesion:
    ms = _mediciones(s)
    validos = [b for b in s.bpm if b and b > 0]
    rep = repartir_zonas(ms, fc_max)
    return MetricasSesion(
        duracion_s=max(0, s.fin_ts - s.inicio_ts),
        bpm_medio=statistics.fmean(validos) if validos else None,
        bpm_max=max(validos) if validos else None,
        zonas_s=rep.segundos if rep else None,
        trimp=sum(p * x / 60.0 for p, x in zip(PESOS_TRIMP, rep.segundos)) if rep else None,
        kcal=calc.kcal_actividad(ms, perfil) if validos else None)


# ------------------------------------------------------------------ Recortar

def recortar_sesion(s: Sesion, t_inicio: float, t_fin: float) -> Sesion:
    """Conserva [t_inicio, t_fin] (s Unix): recorta bpm/rpm/rr y ajusta inicio/fin (la duración se recalcula)."""
    if t_fin <= t_inicio:
        raise ValueError("El fin del recorte debe ser posterior al inicio")
    idx = [i for i, t in enumerate(s.ts) if t_inicio <= t <= t_fin]
    rt = s.rr_t
    ir = [i for i, t in enumerate(rt) if t_inicio <= t <= t_fin]
    rr = tuple(s.rr_ms[i] for i in ir)
    t0 = (rt[ir[0]] - s.rr_ms[ir[0]] / 1000.0) if ir else None
    return Sesion(int(max(s.inicio_ts, t_inicio)), int(min(s.fin_ts, t_fin)),
                  tuple(s.ts[i] for i in idx), tuple(s.bpm[i] for i in idx), tuple(s.rpm[i] for i in idx), rr, t0)


# ------------------------------------------------------------------ Artefactos R-R

def corregir_artefactos_rr(rr_ms: Sequence[float], umbral: float = UMBRAL_ARTEFACTO,
                           ventana: int = VENTANA_MEDIANA) -> tuple[list[float], int]:
    """Latidos con desviación > ``umbral`` respecto a la mediana local → interpolación lineal entre vecinos
    válidos. La suma total se conserva con una reescala mínima de toda la serie. Devuelve (rr, nº corregidos)."""
    rr = np.asarray(rr_ms, dtype=float)
    n = rr.size
    if n < 3:
        return list(map(float, rr)), 0
    h = ventana // 2
    med = np.array([np.median(rr[max(0, i - h):i + h + 1]) for i in range(n)])
    malo = np.abs(rr - med) > umbral * med
    if not malo.any() or malo.all():
        return list(map(float, rr)), 0
    buenos = np.flatnonzero(~malo)
    nuevo = rr.copy()
    nuevo[malo] = np.interp(np.flatnonzero(malo), buenos, rr[buenos])
    nuevo *= rr.sum() / nuevo.sum()                 # reescala mínima: la duración total no cambia
    return list(map(float, nuevo)), int(malo.sum())


def limpiar_sesion(s: Sesion) -> tuple[Sesion, int]:
    rr, n = corregir_artefactos_rr(s.rr_ms)
    return replace(s, rr_ms=tuple(rr)), n


# ------------------------------------------------------------------ Dividir / fusionar

def dividir_sesion(s: Sesion, t_corte: float) -> tuple[Sesion, Sesion]:
    if not s.inicio_ts < t_corte < s.fin_ts:
        raise ValueError("El punto de corte debe quedar dentro de la sesión")
    rt = s.rr_t
    ir = [i for i, t in enumerate(rt) if t <= t_corte]
    k = len(ir)

    def parte(ini, fin, i0, i1, rr_t0):
        idx = [i for i, t in enumerate(s.ts) if ini <= t < fin]
        return Sesion(int(ini), int(fin), tuple(s.ts[i] for i in idx), tuple(s.bpm[i] for i in idx),
                      tuple(s.rpm[i] for i in idx), tuple(s.rr_ms[i0:i1]), rr_t0)

    t0b = (rt[k] - s.rr_ms[k] / 1000.0) if k < len(rt) else None
    return (parte(s.inicio_ts, t_corte, 0, k, s.rr_t0),
            parte(int(t_corte), s.fin_ts, k, len(s.rr_ms), t0b))


def fusionar_sesiones(a: Sesion, b: Sesion) -> Sesion:
    """Une dos sesiones (en orden cronológico); el hueco entre ambas cuenta como parte de la duración."""
    a, b = sorted((a, b), key=lambda x: x.inicio_ts)
    if b.inicio_ts < a.fin_ts:
        raise ValueError("Las sesiones se solapan")
    return Sesion(a.inicio_ts, b.fin_ts, a.ts + b.ts, a.bpm + b.bpm, a.rpm + b.rpm, a.rr_ms + b.rr_ms, a.rr_t0)


# ------------------------------------------------------------------ Lectura / persistencia (SQLite, cuenta activa)

def cargar_sesion(repo, actividad_id: int) -> Optional[Sesion]:
    a = repo.obtener_actividad(actividad_id)
    if a is None:
        return None
    ms = sorted(repo.mediciones_de_actividad(actividad_id), key=lambda m: m.ts)
    rr = [x for v in repo.rr_rango(a.inicio_ts, a.fin_ts + 1) for x in v]
    return Sesion(a.inicio_ts, a.fin_ts, tuple(m.ts for m in ms), tuple(m.bpm for m in ms),
                  tuple(m.rpm for m in ms), tuple(rr))


def _uid() -> str:
    return "ed-" + uuid.uuid4().hex[:12]


def aplicar_recorte(repo, actividad_id: int, t_inicio: int, t_fin: int) -> bool:
    """Borra las mediciones fuera de [t_inicio, t_fin] y ajusta la actividad."""
    a = repo.obtener_actividad(actividad_id)
    if a is None or t_fin <= t_inicio:
        return False
    u, c = repo.usuario_id, repo.conexion
    ini, fin = int(max(a.inicio_ts, t_inicio)), int(min(a.fin_ts, t_fin))
    with c:
        c.execute("DELETE FROM mediciones WHERE usuario_id = ? AND actividad_id = ? AND (ts < ? OR ts > ?)",
                  (u, actividad_id, ini, fin))
        c.execute("UPDATE actividades SET inicio_ts = ?, fin_ts = ? WHERE usuario_id = ? AND id = ?",
                  (ini, fin, u, actividad_id))
    return True


def aplicar_division(repo, actividad_id: int, t_corte: int) -> Optional[int]:
    """Divide la actividad en dos; devuelve el id de la segunda parte."""
    a = repo.obtener_actividad(actividad_id)
    if a is None or not a.inicio_ts < t_corte < a.fin_ts:
        return None
    u, c = repo.usuario_id, repo.conexion
    with c:
        cur = c.execute("INSERT INTO actividades (usuario_id, uid, inicio_ts, fin_ts, tipo) VALUES (?, ?, ?, ?, ?)",
                        (u, _uid(), int(t_corte), a.fin_ts, a.tipo))
        nuevo = int(cur.lastrowid)
        c.execute("UPDATE mediciones SET actividad_id = ? WHERE usuario_id = ? AND actividad_id = ? AND ts >= ?",
                  (nuevo, u, actividad_id, int(t_corte)))
        c.execute("UPDATE actividades SET fin_ts = ? WHERE usuario_id = ? AND id = ?", (int(t_corte), u, actividad_id))
    return nuevo


def aplicar_fusion(repo, id_a: int, id_b: int) -> Optional[int]:
    """Funde dos actividades de la cuenta en la más antigua; devuelve su id."""
    a, b = repo.obtener_actividad(id_a), repo.obtener_actividad(id_b)
    if a is None or b is None or id_a == id_b:
        return None
    a, b = sorted((a, b), key=lambda x: x.inicio_ts)
    if b.inicio_ts < a.fin_ts:
        return None
    u, c = repo.usuario_id, repo.conexion
    with c:
        c.execute("UPDATE mediciones SET actividad_id = ? WHERE usuario_id = ? AND actividad_id = ?", (a.id, u, b.id))
        c.execute("UPDATE actividades SET fin_ts = ? WHERE usuario_id = ? AND id = ?", (b.fin_ts, u, a.id))
        for tabla, col in (("disciplinas_sesion", "sesion_id"), ("notas_sesion", "sesion_id")):
            c.execute(f"DELETE FROM {tabla} WHERE usuario_id = ? AND {col} = ?", (u, b.id))
        c.execute("DELETE FROM actividades WHERE usuario_id = ? AND id = ?", (u, b.id))
    return a.id


def aplicar_limpieza_rr(repo, actividad_id: int) -> int:
    """Corrige los artefactos de cada ventana R-R de la actividad (se guardan por ventanas). Devuelve cuántos."""
    a = repo.obtener_actividad(actividad_id)
    if a is None:
        return 0
    u, c = repo.usuario_id, repo.conexion
    total = 0
    with c:
        for ts, texto in c.execute("SELECT ts, rr FROM rr_ventanas WHERE usuario_id = ? AND ts >= ? AND ts < ?",
                                   (u, a.inicio_ts, a.fin_ts + 1)).fetchall():
            nuevo, n = corregir_artefactos_rr([float(x) for x in texto.split(",") if x])
            if n:
                c.execute("UPDATE rr_ventanas SET rr = ? WHERE usuario_id = ? AND ts = ?",
                          (",".join(f"{x:.1f}" for x in nuevo), u, ts))
                total += n
    return total
