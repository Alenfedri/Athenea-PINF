"""Zonas cardíacas (Z1–Z5) y umbral de fatiga de una actividad.

Todo se calcula en el momento a partir de las mediciones (BPM y RPM) de la actividad; no se guarda nada.
Son estimaciones orientativas: dependen de la FC máx. de referencia y no sustituyen una prueba de esfuerzo.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Optional, Sequence

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from domain.modelos import Medicion

FC_MAX_REFERENCIA = 190                    # BPM; cambiar aquí para otra referencia
LIMITES_ZONAS = (0.60, 0.70, 0.80, 0.90)   # fracciones de la FC máx.: fronteras Z1|Z2, Z2|Z3, Z3|Z4, Z4|Z5
NOMBRES_ZONAS = ("Z1", "Z2", "Z3", "Z4", "Z5")
RANGOS_ZONAS = ("< 60 %", "60–70 %", "70–80 %", "80–90 %", "≥ 90 %")

MIN_MEDICIONES_ZONAS = 2
FACTOR_HUECO = 3.0                         # un hueco mayor que 3× el intervalo típico no cuenta como tiempo

# Umbral de fatiga
MIN_DURACION_S = 480                       # menos de 8 min: no hay base para estimarlo
MIN_PUNTOS = 30
MIN_PUNTOS_BASE = 8
SUAVIZADO = 5                              # puntos de la mediana móvil
FACTOR_COCIENTE = 1.25                     # RPM/BPM por encima de 1,25× su línea base…
SOSTENIDO_S = 90                           # …durante al menos 90 s…
ZONA_MINIMA = LIMITES_ZONAS[1]             # …estando en Z3 o superior (≥ 70 %)


# --------------------------------------------------
# ZONAS
# --------------------------------------------------

def zona_de(bpm: float, fc_max: float = FC_MAX_REFERENCIA) -> int:
    """Índice de zona 0..4 (Z1..Z5)."""
    fraccion = bpm / fc_max
    return sum(fraccion >= limite for limite in LIMITES_ZONAS)


@dataclass(frozen=True)
class ReparticionZonas:
    segundos: tuple[float, float, float, float, float]
    fc_max: float

    @property
    def total_s(self) -> float:
        return float(sum(self.segundos))

    @property
    def porcentajes(self) -> tuple[float, ...]:
        t = self.total_s
        return tuple(100.0 * s / t for s in self.segundos) if t > 0 else (0.0,) * 5


def _intervalo_tipico(ts: Sequence[int]) -> float:
    pasos = [b - a for a, b in zip(ts, ts[1:]) if b > a]
    return float(median(pasos)) if pasos else 0.0


def repartir_zonas(
    mediciones: Sequence[Medicion], fc_max: float = FC_MAX_REFERENCIA,
) -> Optional[ReparticionZonas]:
    """Tiempo en cada zona. Cada medición vale hasta la siguiente (como mucho ``FACTOR_HUECO`` × el
    intervalo típico); los huecos grandes no cuentan. None si no hay datos suficientes."""
    ms = sorted((m for m in mediciones if m.bpm and m.bpm > 0), key=lambda m: m.ts)
    if len(ms) < MIN_MEDICIONES_ZONAS:
        return None
    tipico = _intervalo_tipico([m.ts for m in ms])
    if tipico <= 0:
        return None

    segundos = [0.0] * 5
    for actual, siguiente in zip(ms, ms[1:] + [None]):
        paso = tipico if siguiente is None else siguiente.ts - actual.ts
        if paso > FACTOR_HUECO * tipico:
            paso = tipico
        segundos[zona_de(actual.bpm, fc_max)] += paso
    return ReparticionZonas(tuple(segundos), float(fc_max))


# --------------------------------------------------
# UMBRAL DE FATIGA (BPM + RPM)
# --------------------------------------------------

@dataclass(frozen=True)
class UmbralFatiga:
    ts: int
    minuto: int            # desde el inicio de la actividad
    bpm: float
    rpm: float
    cociente: float        # RPM/BPM suavizado en ese instante
    base: float            # RPM/BPM de referencia

    @property
    def texto(self) -> str:
        return f"Umbral fatiga: min {self.minuto} · {self.bpm:.0f} BPM / {self.rpm:.0f} RPM"


@dataclass(frozen=True)
class ResultadoUmbral:
    umbral: Optional[UmbralFatiga]
    motivo: str = ""       # por qué no hay umbral (vacío si lo hay)


def _mediana_movil(x: np.ndarray, k: int) -> np.ndarray:
    if x.size < k:
        return x.copy()
    relleno = np.pad(x, (k // 2, k - k // 2 - 1), mode="edge")
    return np.median(sliding_window_view(relleno, k), axis=1)


def detectar_umbral_fatiga(
    mediciones: Sequence[Medicion], inicio_ts: int, fc_max: float = FC_MAX_REFERENCIA,
) -> ResultadoUmbral:
    """Primer instante, ya en Z3 o más, en que la respiración se dispara respecto al pulso.

    Se compara RPM/BPM (suavizado con una mediana móvil) con su línea base, tomada de los puntos en
    Z1–Z2 (o del primer 20 % si no hay bastantes). El disparo cuenta si se mantiene ``SOSTENIDO_S``.
    """
    pts = sorted((m for m in mediciones if m.bpm and m.bpm > 0 and m.rpm and m.rpm > 0), key=lambda m: m.ts)
    if len(pts) < MIN_PUNTOS:
        return ResultadoUmbral(None, "No hay datos de respiración suficientes para estimar el umbral de fatiga.")
    if pts[-1].ts - pts[0].ts < MIN_DURACION_S:
        return ResultadoUmbral(None, "Actividad demasiado corta para estimar el umbral de fatiga.")

    ts = np.array([m.ts for m in pts], dtype=float)
    bpm = _mediana_movil(np.array([m.bpm for m in pts]), SUAVIZADO)
    rpm = _mediana_movil(np.array([m.rpm for m in pts]), SUAVIZADO)
    cociente = rpm / bpm

    bajos = bpm < LIMITES_ZONAS[1] * fc_max                    # Z1–Z2
    if bajos.sum() >= MIN_PUNTOS_BASE:
        base = float(np.median(cociente[bajos]))
    else:
        n = max(MIN_PUNTOS_BASE, int(0.2 * len(pts)))
        base = float(np.median(cociente[:n]))
    limite = FACTOR_COCIENTE * base

    por_encima = cociente > limite
    en_zona = bpm >= ZONA_MINIMA * fc_max
    for i in np.flatnonzero(por_encima & en_zona):
        fin = ts[i] + SOSTENIDO_S
        if ts[-1] < fin:
            break                                   # ya no queda tiempo para comprobar que se sostiene
        ventana = (ts >= ts[i]) & (ts <= fin)
        if np.all(por_encima[ventana]):
            minuto = int(round((ts[i] - inicio_ts) / 60))
            return ResultadoUmbral(UmbralFatiga(
                int(ts[i]), minuto, float(bpm[i]), float(rpm[i]), float(cociente[i]), base))
    return ResultadoUmbral(None, "No se aprecia un disparo claro de la respiración respecto al pulso.")


@dataclass(frozen=True)
class AnalisisActividad:
    zonas: Optional[ReparticionZonas]
    umbral: ResultadoUmbral


def analizar_actividad(mediciones: Sequence[Medicion], inicio_ts: int, fc_max: float = FC_MAX_REFERENCIA) -> AnalisisActividad:
    return AnalisisActividad(repartir_zonas(mediciones, fc_max), detectar_umbral_fatiga(mediciones, inicio_ts, fc_max))
