"""Cociente pulso-respiración (BPM/RPM): óptimo en torno a 4:1; < 3:1 sostenido sugiere hiperventilación."""

from __future__ import annotations

from typing import Optional, Sequence

OPTIMO = 4.0
UMBRAL_BAJO = 3.0
SOSTENIDO_S = 60.0
TEXTO_ALERTA = ("Ratio pulso/respiración bajo (< 3:1) sostenido: posible hiperventilación o fatiga "
                "respiratoria temprana. Es solo un indicio, no un diagnóstico.")


def ratio(bpm: Optional[float], rpm: Optional[float]) -> Optional[float]:
    if not bpm or not rpm or bpm <= 0 or rpm <= 0:
        return None
    return bpm / rpm


def texto_ratio(r: Optional[float]) -> str:
    return "N/D" if r is None else f"{r:.1f} : 1"


def estado(r: Optional[float]) -> str:
    if r is None:
        return ""
    if r < UMBRAL_BAJO:
        return "bajo"
    return "óptimo" if 3.5 <= r <= 4.5 else "aceptable"


def ratio_medio(mediciones: Sequence) -> tuple[Optional[float], float]:
    """(BPM medio / RPM medio, % de muestras con ratio < 3:1) de una lista de mediciones."""
    pares = [(m.bpm, m.rpm) for m in mediciones if ratio(m.bpm, m.rpm) is not None]
    if not pares:
        return None, 0.0
    r = ratio(sum(p[0] for p in pares) / len(pares), sum(p[1] for p in pares) / len(pares))
    bajos = sum(1 for b, p in pares if b / p < UMBRAL_BAJO)
    return r, 100.0 * bajos / len(pares)


class MonitorRatio:
    """Alerta cuando el ratio lleva ``SOSTENIDO_S`` segundos seguidos por debajo de 3:1."""

    def __init__(self, sostenido_s: float = SOSTENIDO_S):
        self._sostenido = sostenido_s
        self._desde: Optional[float] = None
        self.ratio: Optional[float] = None

    @property
    def alerta(self) -> bool:
        return self._desde is not None and self._ultimo - self._desde >= self._sostenido

    def actualizar(self, ahora: float, bpm: Optional[float], rpm: Optional[float]) -> None:
        self._ultimo = ahora
        self.ratio = ratio(bpm, rpm)
        if self.ratio is None or self.ratio >= UMBRAL_BAJO:
            self._desde = None
        elif self._desde is None:
            self._desde = ahora

    def reiniciar(self) -> None:
        self._desde, self.ratio, self._ultimo = None, None, 0.0

    _ultimo = 0.0
