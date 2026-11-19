"""Calidad de contacto de la banda pectoral a partir de la ventana reciente de ECG en directo.

Se evalúa en memoria (nada se guarda) sobre los últimos segundos de señal:

  * SIN_SENAL: no hay enlace, faltan muestras o la señal es plana (pico-pico mínimo).
  * RUIDO: saturación, amplitud no fisiológica, saltos de línea base, ruido de alta frecuencia o
    picos aislados de una sola muestra (típico de electrodos secos o de movimiento).
  * OPTIMO: línea base estable y amplitud dentro de lo normal.

Los umbrales son estimaciones para el ECG de 12 bits del firmware (0–4095, filtrado centrado en
~1600) y no se han contrastado con una banda real.
"""

from __future__ import annotations

from enum import Enum
from typing import Sequence

import numpy as np

FS_HZ = 100
VENTANA_S = 4                    # segundos recientes que se analizan
MIN_MUESTRAS = 2 * FS_HZ         # con menos de 2 s no se valora

PTP_MIN = 20.0                   # ADC; por debajo la señal es plana
PTP_MAX = 2500.0                 # ADC; por encima la amplitud no es fisiológica
SAT_BAJA, SAT_ALTA = 2.0, 4093.0
MAX_FRACCION_SATURADA = 0.01
MAX_DERIVA_RELATIVA = 0.5        # pico-pico de la línea base (media de 0,5 s) / pico-pico total
MAX_RUIDO_RELATIVO = 0.05        # ruido de muestra a muestra / pico-pico
IMPULSO_MIN = 300.0              # ADC sobre la línea base para contar un pico aislado
IMPULSO_NITIDEZ = 0.85           # los vecinos caen ≥ 85 % del pico: un QRS real es más ancho
MAX_IMPULSOS = 2


class CalidadContacto(Enum):
    OPTIMO = "Contacto óptimo"
    RUIDO = "Señal con ruido (revisa ajuste/humedad de la banda)"
    SIN_SENAL = "Sin señal"


def _linea_base(x: np.ndarray, n: int = FS_HZ // 2) -> np.ndarray:
    relleno = np.pad(x, (n // 2, n - n // 2 - 1), mode="edge")
    return np.convolve(relleno, np.ones(n) / n, mode="valid")


def evaluar_calidad(
    muestras: Sequence[float], enlace_activo: bool = True, fs: int = FS_HZ,
) -> CalidadContacto:
    if not enlace_activo:
        return CalidadContacto.SIN_SENAL
    x = np.asarray(muestras, dtype=float)[-VENTANA_S * fs:]
    x = x[np.isfinite(x)]
    if x.size < MIN_MUESTRAS:
        return CalidadContacto.SIN_SENAL

    ptp = float(np.ptp(x))
    if ptp < PTP_MIN:
        return CalidadContacto.SIN_SENAL

    if ptp > PTP_MAX or np.mean((x <= SAT_BAJA) | (x >= SAT_ALTA)) > MAX_FRACCION_SATURADA:
        return CalidadContacto.RUIDO

    base = _linea_base(x)
    # La deriva se mide sin los bordes (allí la media móvil se tira del último latido y falsea el resultado)
    centro_base = base[FS_HZ // 4: -(FS_HZ // 4)]
    if float(np.ptp(centro_base)) > MAX_DERIVA_RELATIVA * ptp:       # saltos de línea base
        return CalidadContacto.RUIDO

    d = np.diff(x)
    ruido = 1.4826 * float(np.median(np.abs(d - np.median(d)))) / np.sqrt(2)   # robusto frente a los QRS
    if ruido > MAX_RUIDO_RELATIVO * ptp:
        return CalidadContacto.RUIDO

    desv = x - base
    centro = np.abs(desv[1:-1])
    vecinos = np.minimum(np.abs(x[1:-1] - x[:-2]), np.abs(x[1:-1] - x[2:]))
    impulsos = (centro > IMPULSO_MIN) & (vecinos >= IMPULSO_NITIDEZ * centro) \
        & (np.sign(x[1:-1] - x[:-2]) == np.sign(x[1:-1] - x[2:]))
    if int(impulsos.sum()) >= MAX_IMPULSOS:
        return CalidadContacto.RUIDO

    return CalidadContacto.OPTIMO
