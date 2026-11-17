"""Variabilidad de la frecuencia cardíaca (RMSSD) a partir del ECG de la banda pectoral.

Trabaja sobre el ECG filtrado a 100 Hz que llega en directo (el ECG histórico guardado es solo
una envolvente de 1 s y no contiene los latidos). Pasos:

  1. Se recoge una ventana de ``VENTANA_S`` segundos en reposo (``AcumuladorHrv``).
  2. Se detectan los picos R con umbral adaptativo y distancia refractaria mínima.
  3. Se obtienen los intervalos R-R en ms, se descartan los imposibles (< 300 o > 2000 ms) y
     los saltos bruscos entre latidos consecutivos (artefactos o latidos no detectados).
  4. Se calcula RMSSD = sqrt( 1/(N-1) · Σ (RR[i+1] − RR[i])² ).

Una ventana con ruido o con pocos latidos válidos se rechaza (``evaluar_ventana`` → None).
Es una medida orientativa: la HRV depende mucho de la edad y de cada persona.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

FS_HZ = 100                  # frecuencia de muestreo del ECG en directo
VENTANA_S = 60               # duración de cada ventana analizada
REFRACTARIO_S = 0.3          # distancia mínima entre dos latidos
RR_MIN_MS, RR_MAX_MS = 300.0, 2000.0
MAX_SALTO_RR = 0.25          # |RR[i+1]-RR[i]| respecto a su media; por encima es un artefacto
MIN_LATIDOS = 30             # picos mínimos en una ventana de 1 min
MIN_PARES = 20               # diferencias R-R válidas mínimas
MIN_FRACCION_VALIDA = 0.8    # parte de las diferencias que debe ser válida
MIN_SNR = 5.0                # altura típica de los picos / ruido (MAD) de la señal
TOLERANCIA_FS = 0.10         # desvío admitido entre la tasa real de llegada y los 100 Hz

ESTADO_OPTIMO = "Recuperación óptima"
ESTADO_EQUILIBRADO = "Estado equilibrado"
ESTADO_ESTRES = "Estrés fisiológico / Fatiga"


@dataclass(frozen=True)
class UmbralesHrv:
    """RMSSD (ms) en reposo. Valores de referencia generales, no individualizados."""
    bajo: float = 20.0           # por debajo: estrés fisiológico / fatiga
    alto: float = 50.0           # por encima: recuperación óptima
    min_ventanas: int = 3        # ventanas válidas necesarias para valorar un día
    ventanas_dia: int = 5        # se usan las primeras N ventanas del día


@dataclass(frozen=True)
class ResultadoHrv:
    ts: int                  # inicio de la ventana (segundo Unix)
    rmssd_ms: float
    fc_media: float          # BPM medio de los intervalos válidos
    latidos: int             # intervalos R-R válidos usados


# --------------------------------------------------
# DETECCIÓN DE PICOS R
# --------------------------------------------------

def _sin_linea_base(x: np.ndarray, fs: int) -> np.ndarray:
    """Resta una media móvil de 1 s (deriva lenta) y corrige la polaridad si la R es negativa."""
    n = fs
    relleno = np.pad(x, (n // 2, n - n // 2 - 1), mode="edge")
    base = np.convolve(relleno, np.ones(n) / n, mode="valid")
    y = x - base
    if abs(np.percentile(y, 1)) > abs(np.percentile(y, 99)):
        y = -y
    return y


def detectar_picos_r(senal: Sequence[float], fs: int = FS_HZ) -> np.ndarray:
    """Posiciones (en muestras, con interpolación parabólica) de los picos R."""
    y = _sin_linea_base(np.asarray(senal, dtype=float), fs)
    if y.size < 3:
        return np.empty(0)

    # Umbral adaptativo por bloques de 3 s, con un suelo global para no contar ruido de reposo
    suelo = 0.3 * max(float(np.percentile(y, 99)), 0.0)
    ancho = 3 * fs
    umbral = np.empty_like(y)
    for ini in range(0, y.size, ancho):
        bloque = y[ini:ini + ancho]
        umbral[ini:ini + ancho] = max(0.5 * float(bloque.max()), suelo)

    maximos = np.flatnonzero((y[1:-1] > y[:-2]) & (y[1:-1] >= y[2:]) & (y[1:-1] > umbral[1:-1])) + 1

    refractario = int(round(REFRACTARIO_S * fs))
    elegidos: list[int] = []
    for i in maximos:
        if elegidos and i - elegidos[-1] < refractario:
            if y[i] > y[elegidos[-1]]:           # dentro del periodo refractario manda el más alto
                elegidos[-1] = int(i)
            continue
        elegidos.append(int(i))

    picos = []
    for i in elegidos:
        a, b, c = y[i - 1], y[i], y[i + 1] if i + 1 < y.size else y[i]
        den = a - 2 * b + c
        picos.append(i + (0.5 * (a - c) / den if den != 0 else 0.0))
    return np.asarray(picos)


def alturas_picos(senal: Sequence[float], picos: np.ndarray, fs: int = FS_HZ) -> np.ndarray:
    y = _sin_linea_base(np.asarray(senal, dtype=float), fs)
    return y[np.clip(np.round(picos).astype(int), 0, y.size - 1)] if picos.size else np.empty(0)


# --------------------------------------------------
# R-R Y RMSSD
# --------------------------------------------------

def intervalos_rr_ms(picos: np.ndarray, fs: int = FS_HZ) -> np.ndarray:
    return np.diff(picos) * 1000.0 / fs


def rmssd(rr_ms: Sequence[float]) -> Optional[float]:
    """RMSSD = sqrt(1/(N-1) · Σ (RR[i+1]-RR[i])²); None con menos de 2 intervalos."""
    rr = np.asarray(rr_ms, dtype=float)
    if rr.size < 2:
        return None
    d = np.diff(rr)
    return float(math.sqrt(float(np.sum(d * d)) / (rr.size - 1)))


def evaluar_ventana(senal: Sequence[float], fs: int = FS_HZ, ts: int = 0) -> Optional[ResultadoHrv]:
    """RMSSD de una ventana de ECG, o None si hay ruido o pocos latidos válidos."""
    x = np.asarray(senal, dtype=float)
    if x.size < 10 * fs or not np.all(np.isfinite(x)) or float(np.ptp(x)) == 0.0:
        return None

    picos = detectar_picos_r(x, fs)
    if picos.size < MIN_LATIDOS * (x.size / fs) / VENTANA_S:
        return None

    # Calidad de la señal: los picos deben destacar claramente del ruido de fondo
    y = _sin_linea_base(x, fs)
    ruido = 1.4826 * float(np.median(np.abs(y - np.median(y))))
    altura = float(np.median(alturas_picos(x, picos, fs)))
    if ruido <= 0 or altura / ruido < MIN_SNR:
        return None

    rr = intervalos_rr_ms(picos, fs)
    ok = (rr >= RR_MIN_MS) & (rr <= RR_MAX_MS)
    a, b = rr[:-1], rr[1:]
    par_ok = ok[:-1] & ok[1:] & (np.abs(b - a) <= MAX_SALTO_RR * (a + b) / 2)
    if par_ok.size == 0 or par_ok.sum() < MIN_PARES or par_ok.mean() < MIN_FRACCION_VALIDA:
        return None

    d = (b - a)[par_ok]
    valor = float(math.sqrt(float(np.sum(d * d)) / d.size))
    usados = np.unique(np.concatenate([np.flatnonzero(par_ok), np.flatnonzero(par_ok) + 1]))
    return ResultadoHrv(int(ts), valor, float(60000.0 / np.mean(rr[usados])), int(usados.size))


# --------------------------------------------------
# VENTANAS EN DIRECTO
# --------------------------------------------------

class AcumuladorHrv:
    """Reúne ECG a 100 Hz en ventanas de 1 min y devuelve el resultado al completarse.

    Si la llegada de muestras no se corresponde con 100 Hz (paquetes perdidos o retrasados)
    la ventana se descarta: los milisegundos de R-R dejarían de ser fiables.
    """

    def __init__(self, fs: int = FS_HZ, ventana_s: int = VENTANA_S):
        self._fs = fs
        self._n = fs * ventana_s
        self._muestras: list[float] = []
        self._t0 = 0.0

    def reiniciar(self) -> None:
        self._muestras = []

    def agregar(self, t: float, valor: float) -> Optional[ResultadoHrv]:
        if not math.isfinite(valor):
            self.reiniciar()
            return None
        if not self._muestras:
            self._t0 = t
        self._muestras.append(valor)
        if len(self._muestras) < self._n:
            return None

        muestras, self._muestras = self._muestras, []
        transcurrido = t - self._t0
        if transcurrido <= 0 or abs(self._n / transcurrido - self._fs) > TOLERANCIA_FS * self._fs:
            return None
        return evaluar_ventana(muestras, self._fs, int(self._t0))


# --------------------------------------------------
# INDICADOR DE RECUPERACIÓN
# --------------------------------------------------

def clasificar(rmssd_ms: float, umbrales: UmbralesHrv = UmbralesHrv()) -> str:
    if rmssd_ms >= umbrales.alto:
        return ESTADO_OPTIMO
    if rmssd_ms < umbrales.bajo:
        return ESTADO_ESTRES
    return ESTADO_EQUILIBRADO


def _n(x: float, dec: int = 1) -> str:
    return f"{x:.{dec}f}".replace(".", ",")


def lineas_recuperacion(
    ventanas: Sequence[ResultadoHrv],
    base_ms: Optional[float] = None,
    umbrales: UmbralesHrv = UmbralesHrv(),
) -> list[str]:
    """Líneas de observación de un día a partir de sus ventanas válidas en reposo.

    Se usa la mediana de las primeras ``ventanas_dia`` ventanas del día. ``base_ms`` es la media
    de la HRV de los días anteriores (si la hay) para comparar con la propia persona.
    """
    if not ventanas:
        return []
    primeras = sorted(ventanas, key=lambda v: v.ts)[:umbrales.ventanas_dia]
    if len(primeras) < umbrales.min_ventanas:
        return [f"Recuperación: aún no hay ventanas válidas suficientes en reposo "
                f"({len(primeras)} de {umbrales.min_ventanas} minutos)."]

    valor = float(np.median([v.rmssd_ms for v in primeras]))
    lineas = [f"Recuperación: {clasificar(valor, umbrales)} (HRV en reposo, RMSSD {_n(valor)} ms, "
              f"mediana de {len(primeras)} min válidos)."]
    if base_ms is not None:
        signo = f"{valor - base_ms:+.1f}".replace(".", ",")
        lineas.append(f"Recuperación: {signo} ms respecto a tu media de días anteriores ({_n(base_ms)} ms).")
    lineas.append("Recuperación: la HRV varía mucho con la edad y entre personas; "
                  "es más útil compararla con tu propia evolución.")
    return lineas
