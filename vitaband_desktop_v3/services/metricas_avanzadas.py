"""Métricas biométricas avanzadas de la banda pectoral: TRIMP, carga aguda:crónica, HRR-60 s,
deriva cardíaca y tendencias semanales.

Las funciones puras trabajan con listas de ``Medicion``; ``carga_entrenamiento`` y
``tarjetas_semanales`` leen del repositorio (solo lectura). Todo son estimaciones orientativas,
no validadas clínicamente ni con una banda real.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Optional, Sequence

from domain import observaciones as obs
from domain.modelos import Medicion
from domain.zonas_actividad import FC_MAX_REFERENCIA, repartir_zonas
from services.repositorio_historial import AMBITO_PERIODICO, RepositorioHistorial

_DIA = 86400
PESOS_TRIMP = (1, 2, 3, 4, 5)

# Carga aguda:crónica
RATIO_BAJO, RATIO_ALTO = 0.8, 1.3
DIAS_MIN_HISTORIAL = 14                  # con menos historial, no hay base crónica fiable
UMBRAL_FIJO_BAJO, UMBRAL_FIJO_ALTO = 75.0, 300.0     # TRIMP semanal (estimación)
CARGA_BAJA, CARGA_OPTIMA, CARGA_RIESGO = "Carga baja", "Carga óptima", "Riesgo de sobreentrenamiento"
SIN_DATOS = "Sin datos"

# HRR-60
HRR_TOLERANCIA_S = 30

# Deriva cardíaca
DERIVA_MIN_DURACION_S = 20 * 60
DERIVA_MIN_PUNTOS_MITAD = 6
DERIVA_SUBIDA_BPM = 0.05
DERIVA_RPM_ESTABLE = 0.10
DERIVA_DELTA_TEMP = 0.4
DERIVA_TEMP_ALTA = 37.8


# ---------------------------------------------------------------- TRIMP

def trimp(mediciones: Sequence[Medicion], fc_max: float = FC_MAX_REFERENCIA) -> Optional[float]:
    """TRIMP por zonas: 1·min(Z1) + 2·min(Z2) + 3·min(Z3) + 4·min(Z4) + 5·min(Z5). None sin datos."""
    rep = repartir_zonas(mediciones, fc_max)
    if rep is None:
        return None
    return sum(p * s / 60.0 for p, s in zip(PESOS_TRIMP, rep.segundos))


@dataclass(frozen=True)
class EstadoCarga:
    aguda: float                       # TRIMP de los últimos 7 días
    cronica: float                     # media semanal de los últimos 28 días
    ratio: Optional[float]             # aguda / crónica (None si se usan umbrales fijos)
    estado: str
    umbrales_fijos: bool

    @property
    def texto(self) -> str:
        if self.estado == SIN_DATOS:
            return "Carga de entrenamiento: sin sesiones en los últimos 28 días."
        base = (f"TRIMP 7 días: {self.aguda:.0f}"
                + (f" · ratio {self.ratio:.2f}".replace(".", ",") if self.ratio is not None
                   else " · pocos datos: umbrales fijos"))
        return f"{self.estado} ({base})"


def clasificar_ratio(ratio: float) -> str:
    return CARGA_BAJA if ratio < RATIO_BAJO else CARGA_RIESGO if ratio > RATIO_ALTO else CARGA_OPTIMA


def estado_carga(sesiones: Sequence[tuple[int, float]], ahora: int) -> EstadoCarga:
    """``sesiones``: (inicio_ts, trimp). Compara 7 días con la media semanal de 28."""
    validas = [(t, v) for t, v in sesiones if v is not None and t <= ahora]
    en28 = [(t, v) for t, v in validas if t > ahora - 28 * _DIA]
    if not en28:
        return EstadoCarga(0.0, 0.0, None, SIN_DATOS, False)
    aguda = sum(v for t, v in en28 if t > ahora - 7 * _DIA)
    cronica = sum(v for _, v in en28) / 4.0
    primera = min(t for t, _ in validas)
    if ahora - primera < DIAS_MIN_HISTORIAL * _DIA or cronica <= 0:
        estado = (CARGA_BAJA if aguda < UMBRAL_FIJO_BAJO
                  else CARGA_RIESGO if aguda > UMBRAL_FIJO_ALTO else CARGA_OPTIMA)
        return EstadoCarga(aguda, cronica, None, estado, True)
    ratio = aguda / cronica
    return EstadoCarga(aguda, cronica, ratio, clasificar_ratio(ratio), False)


def trimp_sesiones(repo: RepositorioHistorial, desde: int, hasta: int,
                   fc_max: float = FC_MAX_REFERENCIA) -> list[tuple[int, float]]:
    salida = []
    for a in repo.actividades_rango(desde, hasta):
        t = trimp(repo.mediciones_de_actividad(a.id), fc_max)
        if t is not None:
            salida.append((a.inicio_ts, t))
    return salida


def carga_entrenamiento(repo: RepositorioHistorial, ahora: int, fc_max: float = FC_MAX_REFERENCIA) -> EstadoCarga:
    # Se mira de más atrás para saber cuánto historial hay
    return estado_carga(trimp_sesiones(repo, 0, ahora + 1, fc_max), ahora)


# ---------------------------------------------------------------- HRR-60

def hrr60(mediciones: Sequence[Medicion]) -> Optional[int]:
    """BPM pico − BPM 60 s después. None si la sesión termina antes (o no hay muestra cercana)."""
    ms = sorted((m for m in mediciones if m.bpm and m.bpm > 0), key=lambda m: m.ts)
    if len(ms) < 2:
        return None
    pico = max(ms, key=lambda m: (m.bpm, -m.ts))          # primer máximo
    despues = next((m for m in ms if m.ts >= pico.ts + 60), None)
    if despues is None or despues.ts - (pico.ts + 60) > HRR_TOLERANCIA_S:
        return None
    return int(round(pico.bpm - despues.bpm))


def texto_hrr60(valor: Optional[int]) -> str:
    return "N/D" if valor is None else f"{valor} BPM"


# ---------------------------------------------------------------- Deriva cardíaca

@dataclass(frozen=True)
class Deriva:
    bpm_1: float
    bpm_2: float
    subida_pct: float
    rpm_variacion_pct: float
    temp_1: Optional[float]
    temp_2: Optional[float]

    @property
    def texto(self) -> str:
        t = (f"; temperatura {self.temp_1:.1f} → {self.temp_2:.1f} °C".replace(".", ",")
             if self.temp_1 is not None and self.temp_2 is not None else "")
        return (f"Deriva cardíaca: la FC media subió un {self.subida_pct:.0f} % entre la primera y la segunda "
                f"mitad ({self.bpm_1:.0f} → {self.bpm_2:.0f} BPM) con respiración estable{t}. Posible fatiga "
                "térmica o deshidratación; es una estimación orientativa, no un diagnóstico.")


def _media(vals: Sequence[float]) -> Optional[float]:
    return statistics.fmean(vals) if vals else None


def deriva_cardiaca(mediciones: Sequence[Medicion], inicio_ts: int, fin_ts: int) -> Optional[Deriva]:
    """Detecta deriva en sesiones de ≥ 20 min (None si no se cumplen todas las condiciones)."""
    if fin_ts - inicio_ts < DERIVA_MIN_DURACION_S:
        return None
    ms = sorted((m for m in mediciones if m.bpm and m.bpm > 0 and inicio_ts <= m.ts <= fin_ts), key=lambda m: m.ts)
    mitad = inicio_ts + (fin_ts - inicio_ts) / 2
    a, b = [m for m in ms if m.ts < mitad], [m for m in ms if m.ts >= mitad]
    if len(a) < DERIVA_MIN_PUNTOS_MITAD or len(b) < DERIVA_MIN_PUNTOS_MITAD:
        return None
    bpm1, bpm2 = _media([m.bpm for m in a]), _media([m.bpm for m in b])
    if bpm1 <= 0 or round((bpm2 - bpm1) / bpm1, 6) < DERIVA_SUBIDA_BPM:
        return None
    r1, r2 = _media([m.rpm for m in a if m.rpm]), _media([m.rpm for m in b if m.rpm])
    if not r1 or not r2:
        return None                                       # sin respiración no se puede decir que sea estable
    rpm_var = (r2 - r1) / r1
    if abs(round(rpm_var, 6)) >= DERIVA_RPM_ESTABLE:
        return None
    t1, t2 = _media([m.temp_c for m in a if m.temp_c is not None]), _media([m.temp_c for m in b if m.temp_c is not None])
    if t1 is None or t2 is None:
        return None
    if not (round(t2 - t1, 6) >= DERIVA_DELTA_TEMP or t2 >= DERIVA_TEMP_ALTA):
        return None
    return Deriva(bpm1, bpm2, (bpm2 - bpm1) / bpm1 * 100, rpm_var * 100, t1, t2)


# ---------------------------------------------------------------- Tarjetas semanales

@dataclass(frozen=True)
class Tarjeta:
    nombre: str
    unidad: str
    actual: Optional[float]
    anterior: Optional[float]
    mejor_si_sube: Optional[bool]       # None: sin juicio (p. ej. minutos activos)

    @property
    def delta(self) -> Optional[float]:
        return None if self.actual is None or self.anterior is None else self.actual - self.anterior

    @property
    def pct(self) -> Optional[float]:
        d = self.delta
        return None if d is None or not self.anterior else d / self.anterior * 100

    @property
    def flecha(self) -> str:
        d = self.delta
        return "–" if d is None or abs(d) < 1e-9 else "▲" if d > 0 else "▼"

    @property
    def color(self) -> str:
        d = self.delta
        if d is None or abs(d) < 1e-9 or self.mejor_si_sube is None:
            return "#777777"
        return "#1e8e3e" if (d > 0) == self.mejor_si_sube else "#c0392b"


def tarjetas_semanales(repo: RepositorioHistorial, ahora: int,
                       fc_max: float = FC_MAX_REFERENCIA) -> list[Tarjeta]:
    """Últimos 7 días frente a los 7 anteriores: minutos activos, TRIMP, HRV y FC en reposo."""
    cortes = (ahora - 14 * _DIA, ahora - 7 * _DIA, ahora + 1)
    ventanas = ((cortes[1], cortes[2]), (cortes[0], cortes[1]))        # (actual, anterior)

    def minutos(v):
        acts = repo.actividades_rango(*v)
        return sum(a.duracion_s for a in acts) / 60.0 if acts else None

    def carga(v):
        s = trimp_sesiones(repo, *v, fc_max)
        return sum(x for _, x in s) if s else None

    def hrv_media(v):
        return _media([r.rmssd_ms for r in repo.hrv_rango(*v)])

    def reposo(v):
        return obs.fc_reposo(repo.mediciones_rango(*v, AMBITO_PERIODICO))

    def par(f):
        return f(ventanas[0]), f(ventanas[1])

    return [Tarjeta("Minutos activos", "min", *par(minutos), None),
            Tarjeta("Carga acumulada (TRIMP)", "", *par(carga), None),
            Tarjeta("HRV media (RMSSD)", "ms", *par(hrv_media), True),
            Tarjeta("FC en reposo media", "BPM", *par(reposo), False)]
