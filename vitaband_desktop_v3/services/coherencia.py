"""Coherencia cardíaca: respiración guiada (6 RPM por defecto) y su índice de sincronización."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

DURACIONES_MIN = (2, 3, 5)
RPM_GUIA = 6.0
MIN_DATOS_S = 30             # menos de esto no hay índice fiable
BANDA_HZ = 0.015             # ancho alrededor de la frecuencia guiada


def periodo_s(rpm: float = RPM_GUIA) -> float:
    return 60.0 / rpm


def onda_objetivo(t: float, rpm: float = RPM_GUIA) -> float:
    """0 = exhalación completa, 1 = inhalación completa; con 6 RPM: 5 s inhalar, 5 s exhalar."""
    return 0.5 - 0.5 * math.cos(2 * math.pi * t / periodo_s(rpm))


def fase(t: float, rpm: float = RPM_GUIA) -> str:
    return "Inhala" if (t % periodo_s(rpm)) < periodo_s(rpm) / 2 else "Exhala"


@dataclass(frozen=True)
class ResultadoCoherencia:
    indice: Optional[float]          # % de la oscilación de BPM que sigue la frecuencia guiada
    rpm_medio: Optional[float]
    bpm_medio: Optional[float]
    amplitud_bpm: Optional[float]   # pico a pico de la oscilación de BPM
    duracion_s: float

    def texto(self) -> str:
        if self.indice is None:
            return "Datos insuficientes para calcular la coherencia (se necesitan al menos 30 s con pulso)."
        nivel = "alta" if self.indice >= 60 else "media" if self.indice >= 30 else "baja"
        return f"Coherencia {self.indice:.0f} % ({nivel}) · pulso medio {self.bpm_medio:.0f} BPM"


def indice_coherencia(bpm: Sequence[tuple[float, float]], rpm: float = RPM_GUIA) -> Optional[float]:
    """% de la potencia de la oscilación de BPM concentrada en ±0,015 Hz de la frecuencia guiada.

    ``bpm``: (segundos desde el inicio, BPM). Se remuestrea a 1 Hz, se quita la media y se usa la DFT.
    """
    datos = sorted((t, v) for t, v in bpm if v and v > 0 and math.isfinite(v))
    if len(datos) < 8 or datos[-1][0] - datos[0][0] < MIN_DATOS_S:
        return None
    t = np.array([d[0] for d in datos])
    v = np.array([d[1] for d in datos])
    rejilla = np.arange(math.ceil(t[0]), math.floor(t[-1]) + 1, 1.0)
    s = np.interp(rejilla, t, v)
    s = s - s.mean()
    ventana = np.hanning(s.size)
    espectro = np.abs(np.fft.rfft(s * ventana)) ** 2
    f = np.fft.rfftfreq(s.size, d=1.0)
    total = float(espectro[(f >= 0.04) & (f <= 0.4)].sum())
    if total <= 0:
        return 0.0
    f0 = rpm / 60.0
    pico = float(espectro[(f >= f0 - BANDA_HZ) & (f <= f0 + BANDA_HZ)].sum())
    return max(0.0, min(100.0, 100.0 * pico / total))


def resultado(bpm: Sequence[tuple[float, float]], rpm_medidas: Sequence[float], duracion_s: float,
              rpm: float = RPM_GUIA) -> ResultadoCoherencia:
    validos = [v for _, v in bpm if v and v > 0]
    rpms = [r for r in rpm_medidas if r and r > 0]
    return ResultadoCoherencia(
        indice_coherencia(bpm, rpm),
        float(np.mean(rpms)) if rpms else None,
        float(np.mean(validos)) if validos else None,
        float(max(validos) - min(validos)) if validos else None,
        float(duracion_s))
