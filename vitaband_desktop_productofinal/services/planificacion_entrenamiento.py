"""Entrenamiento estructurado por bloques (con su ejecutor en vivo) y calendario planificado vs. ejecutado.

Las zonas se expresan como índice 0..4 (Z1..Z5), igual que ``PilotoZonaObjetivo``. El calendario guarda sus
sesiones en la tabla propia ``sesiones_planificadas`` (solo de la cuenta activa) y compara con lo registrado
por la banda pectoral en SQLite (solo lectura sobre actividades/mediciones).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional, Sequence, Union

NOMBRES_ZONA = ("Z1", "Z2", "Z3", "Z4", "Z5")


# ------------------------------------------------------------------ Entrenamiento estructurado

@dataclass(frozen=True)
class Bloque:
    nombre: str
    duracion_s: int
    zona: int                      # 0..4

    def __post_init__(self):
        if self.duracion_s <= 0:
            raise ValueError("La duración del bloque debe ser positiva")
        if not 0 <= self.zona <= 4:
            raise ValueError("La zona debe estar entre Z1 y Z5")


@dataclass(frozen=True)
class Repeticion:
    veces: int
    bloques: tuple[Bloque, ...]

    def __post_init__(self):
        if self.veces < 1 or not self.bloques:
            raise ValueError("Una repetición necesita al menos 1 vez y 1 bloque")


Paso = Union[Bloque, Repeticion]


class EntrenamientoEstructurado:
    """p. ej. ``10 min Z1 + 4 × [4 min Z4 / 2 min Z1] + 5 min Z1``."""

    def __init__(self, nombre: str = "Entrenamiento", pasos: Sequence[Paso] = ()):
        self.nombre = nombre
        self.pasos: list[Paso] = list(pasos)

    def bloques_planos(self) -> list[Bloque]:
        salida: list[Bloque] = []
        for p in self.pasos:
            if isinstance(p, Repeticion):
                for i in range(p.veces):
                    salida += [Bloque(f"{b.nombre} ({i + 1}/{p.veces})", b.duracion_s, b.zona) for b in p.bloques]
            else:
                salida.append(p)
        return salida

    @property
    def duracion_total_s(self) -> int:
        return sum(b.duracion_s for b in self.bloques_planos())

    def resumen(self) -> str:
        partes = []
        for p in self.pasos:
            if isinstance(p, Repeticion):
                partes.append(f"{p.veces} × [" + " / ".join(f"{b.duracion_s / 60:g} min {NOMBRES_ZONA[b.zona]}"
                                                           for b in p.bloques) + "]")
            else:
                partes.append(f"{p.duracion_s / 60:g} min {NOMBRES_ZONA[p.zona]}")
        return " + ".join(partes)

    def a_dict(self) -> dict:
        def b(x): return {"nombre": x.nombre, "duracion_s": x.duracion_s, "zona": x.zona}
        return {"nombre": self.nombre, "pasos": [
            {"veces": p.veces, "bloques": [b(x) for x in p.bloques]} if isinstance(p, Repeticion) else b(p)
            for p in self.pasos]}

    @classmethod
    def desde_dict(cls, d: dict) -> "EntrenamientoEstructurado":
        def b(x): return Bloque(str(x["nombre"]), int(x["duracion_s"]), int(x["zona"]))
        return cls(d.get("nombre", "Entrenamiento"), [
            Repeticion(int(p["veces"]), tuple(b(x) for x in p["bloques"])) if "bloques" in p else b(p)
            for p in d.get("pasos", [])])


@dataclass(frozen=True)
class EstadoEjecucion:
    indice: int
    bloque: Optional[Bloque]
    restante_bloque_s: float
    progreso_bloque: float         # 0..1
    progreso_total: float          # 0..1
    zona: Optional[int]
    terminado: bool
    cambio_de_bloque: bool


class EjecutorBloques:
    """Avanza por los bloques según el reloj. ``actualizar(ahora)`` devuelve el estado y, si se le pasa el
    piloto (``PilotoZonaObjetivo``) o un callback, sincroniza la zona objetivo al cambiar de bloque."""

    def __init__(self, entrenamiento: EntrenamientoEstructurado):
        self.bloques = entrenamiento.bloques_planos()
        if not self.bloques:
            raise ValueError("El entrenamiento no tiene bloques")
        self.total_s = float(sum(b.duracion_s for b in self.bloques))
        self._t0: Optional[float] = None
        self._indice_previo = -1
        self.terminado = False

    @property
    def activo(self) -> bool:
        return self._t0 is not None and not self.terminado

    def iniciar(self, ahora: float) -> None:
        self._t0, self._indice_previo, self.terminado = float(ahora), -1, False

    def detener(self) -> None:
        self._t0, self.terminado = None, False

    def actualizar(self, ahora: float, piloto=None) -> EstadoEjecucion:
        if self._t0 is None:
            raise RuntimeError("El entrenamiento no se ha iniciado")
        t = max(0.0, float(ahora) - self._t0)
        if t >= self.total_s:
            self.terminado = True
            est = EstadoEjecucion(len(self.bloques) - 1, None, 0.0, 1.0, 1.0, None, True,
                                  self._indice_previo != len(self.bloques))
            self._indice_previo = len(self.bloques)
            if piloto is not None:
                piloto.zona = None
            return est
        acum = 0.0
        for i, b in enumerate(self.bloques):
            if t < acum + b.duracion_s:
                dentro = t - acum
                cambio = i != self._indice_previo
                self._indice_previo = i
                if cambio and piloto is not None:
                    piloto.zona = b.zona
                return EstadoEjecucion(i, b, b.duracion_s - dentro, dentro / b.duracion_s, t / self.total_s,
                                       b.zona, False, cambio)
            acum += b.duracion_s
        raise AssertionError("inalcanzable")


# ------------------------------------------------------------------ Calendario planificado vs. ejecutado

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS sesiones_planificadas (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL,
    fecha      TEXT    NOT NULL,
    nombre     TEXT    NOT NULL,
    minutos    REAL    NOT NULL,
    trimp      REAL,
    plan       TEXT
);
CREATE INDEX IF NOT EXISTS idx_plan_usuario_fecha ON sesiones_planificadas (usuario_id, fecha);
"""


@dataclass(frozen=True)
class SesionPlanificada:
    id: int
    fecha: date
    nombre: str
    minutos: float
    trimp: Optional[float]
    plan: Optional[dict]


@dataclass(frozen=True)
class Cumplimiento:
    lunes: date
    sesiones_plan: int
    sesiones_real: int
    minutos_plan: float
    minutos_real: float
    trimp_plan: float
    trimp_real: float
    pct: Optional[float]           # None si no hay nada planificado esa semana


def lunes_de(d: date) -> date:
    return d - timedelta(days=d.weekday())


class GestorCalendarioPlanificado:
    def __init__(self, repo):
        self._repo = repo
        self._c = repo.conexion
        self._u = repo.usuario_id
        with self._c:
            self._c.executescript(_ESQUEMA)

    def agendar(self, fecha: date, nombre: str, minutos: float, trimp: Optional[float] = None,
                entrenamiento: Optional[EntrenamientoEstructurado] = None) -> int:
        if minutos <= 0:
            raise ValueError("Los minutos planificados deben ser positivos")
        plan = json.dumps(entrenamiento.a_dict()) if entrenamiento else None
        with self._c:
            cur = self._c.execute(
                "INSERT INTO sesiones_planificadas (usuario_id, fecha, nombre, minutos, trimp, plan) "
                "VALUES (?, ?, ?, ?, ?, ?)", (self._u, fecha.isoformat(), nombre.strip() or "Sesión", float(minutos),
                                               None if trimp is None else float(trimp), plan))
        return int(cur.lastrowid)

    def agendar_unica(self, fecha: date, nombre: str, minutos: float, trimp: Optional[float] = None,
                      entrenamiento: Optional[EntrenamientoEstructurado] = None) -> Optional[int]:
        """Como `agendar`, pero devuelve None sin insertar si ya hay una sesión con el mismo título y duración ese día."""
        nombre = nombre.strip() or "Sesión"
        ya = self._c.execute("SELECT id FROM sesiones_planificadas WHERE usuario_id = ? AND fecha = ? AND nombre = ? "
                             "AND minutos = ?", (self._u, fecha.isoformat(), nombre, float(minutos))).fetchone()
        if ya:
            return None
        return self.agendar(fecha, nombre, minutos, trimp, entrenamiento)

    def mover(self, sesion_id: int, fecha: date) -> bool:
        with self._c:
            return self._c.execute("UPDATE sesiones_planificadas SET fecha = ? WHERE usuario_id = ? AND id = ?",
                                   (fecha.isoformat(), self._u, sesion_id)).rowcount > 0

    def fijar_objetivo_hoy(self, sesion_id: int, hoy: date) -> None:
        """Marca la sesión como objetivo del día (la usa el Susurrador en Vivo)."""
        with self._c:
            self._c.execute("CREATE TABLE IF NOT EXISTS app_meta (clave TEXT PRIMARY KEY, valor TEXT NOT NULL)")
            self._c.execute("INSERT INTO app_meta (clave, valor) VALUES (?, ?) ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
                            (f"objetivo_hoy_{self._u}", f"{hoy.isoformat()}|{sesion_id}"))

    def eliminar(self, sesion_id: int) -> bool:
        with self._c:
            return self._c.execute("DELETE FROM sesiones_planificadas WHERE usuario_id = ? AND id = ?",
                                   (self._u, sesion_id)).rowcount > 0

    def entre(self, desde: date, hasta: date) -> list[SesionPlanificada]:
        filas = self._c.execute(
            "SELECT id, fecha, nombre, minutos, trimp, plan FROM sesiones_planificadas "
            "WHERE usuario_id = ? AND fecha >= ? AND fecha <= ? ORDER BY fecha, id",
            (self._u, desde.isoformat(), hasta.isoformat())).fetchall()
        return [SesionPlanificada(f[0], date.fromisoformat(f[1]), f[2], f[3], f[4],
                                  json.loads(f[5]) if f[5] else None) for f in filas]

    def del_mes(self, anio: int, mes: int) -> list[SesionPlanificada]:
        ini = date(anio, mes, 1)
        fin = (date(anio + (mes == 12), mes % 12 + 1, 1)) - timedelta(days=1)
        return self.entre(ini, fin)

    def cumplimiento_semanal(self, dia: date) -> Cumplimiento:
        """Compara lo planificado en la semana (lunes–domingo) de ``dia`` con lo registrado en SQLite.
        % = media de min(real/plan, 1) sobre las magnitudes planificadas (sesiones, minutos y, si se fijó, TRIMP)."""
        from services.metricas_avanzadas import trimp_sesiones
        lunes = lunes_de(dia)
        plan = self.entre(lunes, lunes + timedelta(days=6))
        ini = int(datetime.combine(lunes, datetime.min.time()).timestamp())
        fin = int(datetime.combine(lunes + timedelta(days=7), datetime.min.time()).timestamp())
        acts = self._repo.actividades_rango(ini, fin)
        min_real = sum(a.duracion_s for a in acts) / 60.0
        trimp_real = sum(t for _, t in trimp_sesiones(self._repo, ini, fin))
        n_plan, m_plan = len(plan), sum(p.minutos for p in plan)
        t_plan = sum(p.trimp or 0.0 for p in plan)
        ratios = []
        if n_plan:
            ratios += [min(len(acts) / n_plan, 1.0), min(min_real / m_plan, 1.0)]
            if t_plan > 0:
                ratios.append(min(trimp_real / t_plan, 1.0))
        pct = 100.0 * sum(ratios) / len(ratios) if ratios else None
        return Cumplimiento(lunes, n_plan, len(acts), m_plan, min_real, t_plan, trimp_real, pct)
