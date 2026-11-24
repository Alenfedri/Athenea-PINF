"""Fisiología avanzada de la banda pectoral ECG: PMC (CTL/ATL/TSB), umbrales ventilatorios VT1/VT2
(DFA α1 sobre R-R + inflexión de la respiración) y curva de pulso máximo sostenido por duración.

Funciones puras con numpy; ``trimp_diario`` y ``curvas_por_temporada`` leen del repositorio (solo lectura).
Son estimaciones orientativas, no validadas con una banda real ni con pruebas de gases.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Mapping, Optional, Sequence

import numpy as np

from domain.zonas_actividad import FC_MAX_REFERENCIA

TAU_CTL, TAU_ATL = 42.0, 7.0
UMBRAL_ALFA1_VT1 = 0.75
DURACIONES_PICO_S = (5, 60, 300, 1200, 3600)
HUECO_MAX_S = 10                                  # más de 10 s sin dato no cuenta como esfuerzo sostenido
_DIA = 86400


# ------------------------------------------------------------------ PMC

@dataclass(frozen=True)
class PuntoPmc:
    fecha: date
    trimp: float
    ctl: float          # fitness crónico (τ = 42 d)
    atl: float          # fatiga aguda (τ = 7 d)
    tsb: float          # forma = CTL − ATL


def calcular_pmc(trimp_por_dia: Mapping[date, float], hasta: date, dias: int = 90) -> list[PuntoPmc]:
    """Media móvil exponencial diaria del TRIMP. Se calienta desde el primer día con datos (si hay
    historial anterior a la ventana) y devuelve solo los últimos ``dias`` (recomendado 42–90)."""
    if dias < 1:
        raise ValueError("La ventana debe tener al menos 1 día")
    inicio_ventana = hasta - timedelta(days=dias - 1)
    previos = [d for d in trimp_por_dia if d <= hasta]
    inicio = min([inicio_ventana] + previos)
    a_ctl, a_atl = 1 - math.exp(-1 / TAU_CTL), 1 - math.exp(-1 / TAU_ATL)
    ctl = atl = 0.0
    salida: list[PuntoPmc] = []
    d = inicio
    while d <= hasta:
        t = float(trimp_por_dia.get(d, 0.0))
        ctl += (t - ctl) * a_ctl
        atl += (t - atl) * a_atl
        if d >= inicio_ventana:
            salida.append(PuntoPmc(d, t, ctl, atl, ctl - atl))
        d += timedelta(days=1)
    return salida


def trimp_diario(repo, hasta: date, dias_historial: int = 180, fc_max: float = FC_MAX_REFERENCIA) -> dict[date, float]:
    """TRIMP por día de la cuenta activa (suma de sus actividades)."""
    from services.metricas_avanzadas import trimp_sesiones
    desde = int(datetime.combine(hasta - timedelta(days=dias_historial), datetime.min.time()).timestamp())
    fin = int(datetime.combine(hasta + timedelta(days=1), datetime.min.time()).timestamp())
    salida: dict[date, float] = {}
    for ts, t in trimp_sesiones(repo, desde, fin, fc_max):
        d = datetime.fromtimestamp(ts).date()
        salida[d] = salida.get(d, 0.0) + t
    return salida


# ------------------------------------------------------------------ DFA α1 y umbrales ventilatorios

def dfa_alfa1(rr_ms: Sequence[float], n_min: int = 4, n_max: int = 16) -> Optional[float]:
    """Exponente de escala a corto plazo (cajas de 4 a 16 latidos) de los R-R. None con pocos datos."""
    rr = np.asarray(rr_ms, dtype=float)
    if rr.size < 4 * n_max:
        return None
    y = np.cumsum(rr - rr.mean())
    tamanos, fluct = [], []
    for n in range(n_min, n_max + 1):
        k = y.size // n
        cajas = y[:k * n].reshape(k, n)
        x = np.arange(n)
        x0 = x - x.mean()
        pend = (cajas - cajas.mean(axis=1, keepdims=True)) @ x0 / (x0 @ x0)
        resid = cajas - cajas.mean(axis=1, keepdims=True) - pend[:, None] * x0
        f = math.sqrt(float((resid ** 2).mean()))
        if f > 0:
            tamanos.append(n)
            fluct.append(f)
    if len(tamanos) < 3:
        return None
    return float(np.polyfit(np.log(tamanos), np.log(fluct), 1)[0])


@dataclass(frozen=True)
class PuntoAlfa:
    t_s: float            # centro de la ventana (s desde el inicio de los R-R)
    alfa1: float
    bpm: float


@dataclass(frozen=True)
class UmbralVentilatorio:
    nombre: str           # "VT1" | "VT2"
    bpm: float
    t_s: float
    valor: float          # α1 (VT1) o RPM (VT2) en el cruce
    metodo: str


def _limpiar_rr(rr_ms: Sequence[float]) -> np.ndarray:
    rr = np.asarray(rr_ms, dtype=float)
    return rr[(rr >= 300) & (rr <= 2000)]


def alfa1_deslizante(rr_ms: Sequence[float], ventana_s: float = 120.0, paso_s: float = 20.0) -> list[PuntoAlfa]:
    """α1 y FC media en ventanas deslizantes de ``ventana_s`` segundos sobre los R-R."""
    rr = _limpiar_rr(rr_ms)
    t = np.cumsum(rr) / 1000.0
    salida, ini = [], 0.0
    while ini + ventana_s <= (t[-1] if t.size else 0):
        m = (t > ini) & (t <= ini + ventana_s)
        a = dfa_alfa1(rr[m])
        if a is not None:
            salida.append(PuntoAlfa(ini + ventana_s / 2, a, 60000.0 / float(rr[m].mean())))
        ini += paso_s
    return salida


def cruce_alfa1(puntos: Sequence[PuntoAlfa], objetivo: float = UMBRAL_ALFA1_VT1) -> Optional[UmbralVentilatorio]:
    """Primer cruce descendente de α1 por ``objetivo`` (interpolado) → VT1."""
    for a, b in zip(puntos, puntos[1:]):
        if a.alfa1 > objetivo >= b.alfa1:
            f = (a.alfa1 - objetivo) / (a.alfa1 - b.alfa1) if a.alfa1 != b.alfa1 else 0.0
            return UmbralVentilatorio("VT1", a.bpm + f * (b.bpm - a.bpm), a.t_s + f * (b.t_s - a.t_s),
                                      objetivo, "DFA α1 ≈ 0,75")
    return None


def inflexion_rpm(t_s: Sequence[float], rpm: Sequence[float], min_puntos: int = 6,
                  factor_pendiente: float = 1.5) -> Optional[tuple[float, float]]:
    """Punto de inflexión (t, rpm) de una recta a trozos de 2 tramos: el de menor error cuadrático,
    exigiendo que la pendiente del segundo tramo sea positiva y ≥ ``factor_pendiente`` × la del primero."""
    t, r = np.asarray(t_s, float), np.asarray(rpm, float)
    ok = np.isfinite(t) & np.isfinite(r) & (r > 0)
    t, r = t[ok], r[ok]
    n = t.size
    if n < 2 * min_puntos:
        return None
    mejor = None
    for k in range(min_puntos, n - min_puntos + 1):
        p1, p2 = np.polyfit(t[:k], r[:k], 1), np.polyfit(t[k - 1:], r[k - 1:], 1)
        sse = float(((np.polyval(p1, t[:k]) - r[:k]) ** 2).sum() + ((np.polyval(p2, t[k:]) - r[k:]) ** 2).sum())
        if mejor is None or sse < mejor[0]:
            mejor = (sse, k, p1[0], p2[0])
    _, k, s1, s2 = mejor
    if s2 <= 0 or s2 < factor_pendiente * max(s1, 1e-9):
        return None
    return float(t[k - 1]), float(r[k - 1])


def bpm_en(rr_ms: Sequence[float], t_s: float, semiancho_s: float = 15.0) -> Optional[float]:
    rr = _limpiar_rr(rr_ms)
    t = np.cumsum(rr) / 1000.0
    m = (t >= t_s - semiancho_s) & (t <= t_s + semiancho_s)
    return 60000.0 / float(rr[m].mean()) if m.any() else None


def detectar_umbrales_ventilatorios(rr_ms: Sequence[float], t_rpm_s: Sequence[float], rpm: Sequence[float]
                                    ) -> dict[str, Optional[UmbralVentilatorio]]:
    """VT1 por cruce de DFA α1 ≈ 0,75 y VT2 por la inflexión de la respiración, con la FC tomada de los R-R."""
    vt1 = cruce_alfa1(alfa1_deslizante(rr_ms))
    vt2 = None
    infl = inflexion_rpm(t_rpm_s, rpm)
    if infl is not None:
        fc = bpm_en(rr_ms, infl[0])
        if fc is not None:
            vt2 = UmbralVentilatorio("VT2", fc, infl[0], infl[1], "Inflexión de RPM")
    if vt1 and vt2 and vt2.bpm <= vt1.bpm:
        vt2 = None                                           # incoherente: VT2 debe quedar por encima de VT1
    return {"VT1": vt1, "VT2": vt2}


# ------------------------------------------------------------------ Curva de pulso máximo sostenido

def pico_sostenido(ts: Sequence[float], bpm: Sequence[float], duracion_s: int) -> Optional[float]:
    """Mayor media de BPM en ``duracion_s`` segundos continuos (huecos > 10 s rompen la ventana)."""
    t, b = np.asarray(ts, float), np.asarray(bpm, float)
    if t.size < 2:
        return None
    o = np.argsort(t)
    t, b = t[o], b[o]
    rejilla = np.arange(math.floor(t[0]), math.floor(t[-1]) + 1, dtype=float)
    v = np.interp(rejilla, t, b)
    idx = np.searchsorted(t, rejilla, side="right")                  # hueco: distancia a muestras vecinas
    izq = t[np.clip(idx - 1, 0, t.size - 1)]
    der = t[np.clip(idx, 0, t.size - 1)]
    valido = (rejilla - izq <= HUECO_MAX_S) & (der - rejilla <= HUECO_MAX_S) | (rejilla == izq)
    n = int(duracion_s)
    if v.size < n:
        return None
    c = np.concatenate([[0.0], np.cumsum(v)])
    medias = (c[n:] - c[:-n]) / n
    malos = np.concatenate([[0], np.cumsum(~valido)])
    sin_huecos = (malos[n:] - malos[:-n]) == 0
    return float(medias[sin_huecos].max()) if sin_huecos.any() else None


def calcular_curva_pico_hr(sesiones: Sequence[Sequence[tuple[float, float]]],
                           duraciones_s: Sequence[int] = DURACIONES_PICO_S) -> dict[int, Optional[float]]:
    """Para cada duración, el mejor pulso medio sostenido entre las sesiones dadas ((ts, bpm) por sesión)."""
    curva: dict[int, Optional[float]] = {}
    for d in duraciones_s:
        mejores = []
        for s in sesiones:
            if len(s) >= 2:
                p = pico_sostenido([x[0] for x in s], [x[1] for x in s], d)
                if p is not None:
                    mejores.append(p)
        curva[int(d)] = max(mejores) if mejores else None
    return curva


def curvas_por_temporada(repo, hoy: date) -> tuple[dict[int, Optional[float]], dict[int, Optional[float]]]:
    """(temporada actual = últimos 365 días, temporada anterior = los 365 previos)."""
    fin = int(datetime.combine(hoy + timedelta(days=1), datetime.min.time()).timestamp())
    corte, inicio = fin - 365 * _DIA, fin - 730 * _DIA

    def curva(desde, hasta):
        ses = [[(m.ts, m.bpm) for m in repo.mediciones_de_actividad(a.id) if m.bpm and m.bpm > 0]
               for a in repo.actividades_rango(desde, hasta)]
        return calcular_curva_pico_hr(ses)

    return curva(corte, fin), curva(inicio, corte)
