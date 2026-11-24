"""Estrés cognitivo por ECG de la banda pectoral: clasifica (BPM, RMSSD) en calma, tensión o estrés sostenido.

Estimación orientativa (umbrales de la literatura de HRV a corto plazo), no validada con una banda real ni clínica.
"""
from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional

RMSSD_CALMA_MS = 38.0           # ≥ 38 ms y pulso estable → calma / foco
RMSSD_ESTRES_MS = 26.0          # < 26 ms (con pulso elevado) → estrés
BPM_ESTRES = 95.0               # pulso absoluto que cuenta como «elevado»
SUBIDA_ESTRES_BPM = 15.0        # o +15 BPM sobre el basal
SUBIDA_MODERADA_BPM = 8.0       # subida moderada sobre el basal → tensión
SOSTENIDO_S = 20.0              # el estrés debe mantenerse 20 s continuos
ENFRIAMIENTO_S = 300.0          # 5 min entre alertas automáticas
SALTO_MAX_S = 5.0               # un hueco mayor (desconexión) no se contabiliza como tiempo en un estado
VENTANA_S = 60.0                # ventana deslizante de muestras

CALMA, TENSION, ESTRES = "calma", "tension", "estres"
ESTADOS = (CALMA, TENSION, ESTRES)
COLORES = {CALMA: "#10B981", TENSION: "#F59E0B", ESTRES: "#EF4444"}
NOMBRES = {CALMA: "Foco calmado", TENSION: "Tensión", ESTRES: "Estrés sostenido"}


def clasificar_instante(bpm: Optional[float], rmssd: Optional[float], basal: Optional[float] = None) -> Optional[str]:
    """Estado instantáneo (sin la condición de duración); None si falta algún dato."""
    if bpm is None or rmssd is None or bpm <= 0 or rmssd <= 0:
        return None
    subida = None if basal is None else bpm - basal
    pulso_alto = bpm > BPM_ESTRES or (subida is not None and subida >= SUBIDA_ESTRES_BPM)
    if rmssd < RMSSD_ESTRES_MS and pulso_alto:
        return ESTRES
    moderada = subida is not None and subida >= SUBIDA_MODERADA_BPM
    if rmssd >= RMSSD_CALMA_MS and not moderada and not pulso_alto:
        return CALMA
    return TENSION


@dataclass(frozen=True)
class Lectura:
    estado: Optional[str]
    alerta: bool                 # True cuando hay que lanzar la pausa automática
    bpm: Optional[float]
    rmssd: Optional[float]


class MonitorEstresCognitivo:
    """Ventana deslizante de muestras; acumula segundos por estado y detecta estrés sostenido."""

    def __init__(self, reloj: Optional[Callable[[], float]] = None):
        self._reloj = reloj
        self._muestras: deque = deque()                 # (t, bpm, rmssd)
        self._calmas: deque = deque(maxlen=300)         # BPM de los instantes en calma → pulso basal
        self._desde_estres: Optional[float] = None
        self._ultima_alerta: Optional[float] = None
        self._t_prev: Optional[float] = None
        self._estado_prev: Optional[str] = None
        self.acumulado = {e: 0.0 for e in ESTADOS}
        self.estado: Optional[str] = None
        self.basal_manual: Optional[float] = None

    @property
    def basal(self) -> Optional[float]:
        if self.basal_manual is not None:
            return self.basal_manual
        return statistics.median(self._calmas) if len(self._calmas) >= 10 else None

    def reiniciar(self) -> None:
        self._muestras.clear()
        self._desde_estres = self._t_prev = self._estado_prev = None
        self.estado = None

    def vaciar_acumulado(self) -> dict:
        previo, self.acumulado = self.acumulado, {e: 0.0 for e in ESTADOS}
        return previo

    def actualizar(self, bpm: Optional[float], rmssd: Optional[float], t: Optional[float] = None) -> Lectura:
        t = float(t if t is not None else self._reloj())
        # Tiempo en el estado anterior (los huecos largos, p. ej. banda desconectada, no cuentan)
        if self._t_prev is not None and self._estado_prev is not None and 0 < t - self._t_prev <= SALTO_MAX_S:
            self.acumulado[self._estado_prev] += t - self._t_prev
        estado = clasificar_instante(bpm, rmssd, self.basal)
        self._t_prev, self._estado_prev, self.estado = t, estado, estado
        if estado is None:
            self._desde_estres = None
            return Lectura(None, False, bpm, rmssd)
        self._muestras.append((t, bpm, rmssd))
        while self._muestras and self._muestras[0][0] < t - VENTANA_S:
            self._muestras.popleft()
        if estado == CALMA:
            self._calmas.append(bpm)
        if estado != ESTRES:
            self._desde_estres = None
            return Lectura(estado, False, bpm, rmssd)
        if self._desde_estres is None:
            self._desde_estres = t
        alerta = (t - self._desde_estres >= SOSTENIDO_S
                  and (self._ultima_alerta is None or t - self._ultima_alerta >= ENFRIAMIENTO_S))
        if alerta:
            self._ultima_alerta = t
        return Lectura(estado, alerta, bpm, rmssd)
