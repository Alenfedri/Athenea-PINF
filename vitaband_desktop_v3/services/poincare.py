"""Diagrama de Poincaré (RR n vs RR n+1) con SD1/SD2 y marcado de latidos atípicos."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

from domain import hrv

MIN_PARES = 10


def rr_de_ventana(senal: Sequence[float], fs: int = hrv.FS_HZ) -> Optional[list[float]]:
    """Intervalos R-R (ms) de una ventana de ECG, o None si hay ruido o pocos latidos.

    Conserva también los intervalos fuera de rango: es el diagrama quien los marca como atípicos.
    """
    x = np.asarray(senal, dtype=float)
    if x.size < 10 * fs or not np.all(np.isfinite(x)) or float(np.ptp(x)) == 0.0:
        return None
    picos = hrv.detectar_picos_r(x, fs)
    if picos.size < 10:
        return None
    y = hrv._sin_linea_base(x, fs)
    ruido = 1.4826 * float(np.median(np.abs(y - np.median(y))))
    altura = float(np.median(hrv.alturas_picos(x, picos, fs)))
    if ruido <= 0 or altura / ruido < hrv.MIN_SNR:
        return None
    return [float(v) for v in hrv.intervalos_rr_ms(picos, fs)]


class AcumuladorRr:
    """Como ``hrv.AcumuladorHrv`` pero devuelve (inicio, R-R) y vale a cualquier nivel de actividad."""

    def __init__(self, fs: int = hrv.FS_HZ, ventana_s: int = hrv.VENTANA_S):
        self._fs, self._n = fs, fs * ventana_s
        self._muestras: list[float] = []
        self._t0 = 0.0

    def reiniciar(self) -> None:
        self._muestras = []

    def agregar(self, t: float, valor: float) -> Optional[tuple[int, list[float]]]:
        if not math.isfinite(valor):
            self.reiniciar()
            return None
        if not self._muestras:
            self._t0 = t
        self._muestras.append(valor)
        if len(self._muestras) < self._n:
            return None
        muestras, self._muestras = self._muestras, []
        dt = t - self._t0
        if dt <= 0 or abs(self._n / dt - self._fs) > hrv.TOLERANCIA_FS * self._fs:
            return None
        rr = rr_de_ventana(muestras, self._fs)
        return None if rr is None else (int(self._t0), rr)


def par_atipico(a: float, b: float) -> bool:
    """Par fuera del rango fisiológico o con un salto brusco (latido ectópico o artefacto)."""
    if not (hrv.RR_MIN_MS <= a <= hrv.RR_MAX_MS and hrv.RR_MIN_MS <= b <= hrv.RR_MAX_MS):
        return True
    return abs(b - a) > hrv.MAX_SALTO_RR * (a + b) / 2


@dataclass(frozen=True)
class Poincare:
    x: tuple[float, ...]                 # pares normales
    y: tuple[float, ...]
    atipicos_x: tuple[float, ...]        # pares marcados
    atipicos_y: tuple[float, ...]
    sd1: Optional[float]
    sd2: Optional[float]

    @property
    def n(self) -> int:
        return len(self.x)

    @property
    def n_atipicos(self) -> int:
        return len(self.atipicos_x)

    @property
    def cociente(self) -> Optional[float]:
        return None if not self.sd1 or self.sd2 is None else self.sd1 / self.sd2

    def texto(self) -> str:
        if self.sd1 is None or self.sd2 is None:
            return f"Datos insuficientes para SD1/SD2 ({self.n} pares válidos; mínimo {MIN_PARES})."
        return (f"SD1 {self.sd1:.1f} ms · SD2 {self.sd2:.1f} ms · SD1/SD2 {self.cociente:.2f} · "
                f"{self.n} latidos, {self.n_atipicos} atípicos")


def calcular_poincare(ventanas: Sequence[Sequence[float]]) -> Poincare:
    """Los pares se forman dentro de cada ventana (nunca entre ventanas separadas en el tiempo)."""
    x, y, ax, ay = [], [], [], []
    for rr in ventanas:
        for a, b in zip(rr[:-1], rr[1:]):
            (ax if par_atipico(a, b) else x).append(a)
            (ay if par_atipico(a, b) else y).append(b)
    sd1 = sd2 = None
    if len(x) >= MIN_PARES:
        px, py = np.asarray(x), np.asarray(y)
        sd1 = float(np.std((py - px) / math.sqrt(2), ddof=1))
        sd2 = float(np.std((py + px) / math.sqrt(2), ddof=1))
    return Poincare(tuple(x), tuple(y), tuple(ax), tuple(ay), sd1, sd2)
