"""Modo Escritorio: detecta estrés sostenido en reposo (RMSSD a la baja y respiración al alza)."""

from __future__ import annotations

import statistics
from collections import deque
from typing import Optional

VENTANA_DEFECTO_MIN = 20
CAIDA_RMSSD = 0.20             # el último tercio debe estar ≥ 20 % por debajo del primero
SUBIDA_RPM = 1.5               # y respirar ≥ 1,5 RPM más
MIN_PUNTOS_RMSSD = 2           # por tercio (llega 1 RMSSD por minuto)
ESPERA_TRAS_AVISO_S = 30 * 60

TEXTO_AVISO = ("Tu variabilidad cardíaca baja y respiras más rápido desde hace un rato: "
               "prueba una pausa activa o una sesión de Coherencia Cardíaca.")


class DetectorEstres:
    def __init__(self, ventana_min: float = VENTANA_DEFECTO_MIN):
        self.ventana_min = ventana_min
        self._rmssd: deque[tuple[float, float]] = deque()
        self._rpm: deque[tuple[float, float]] = deque()
        self._ultimo_aviso: Optional[float] = None

    def reiniciar(self) -> None:
        self._rmssd.clear()
        self._rpm.clear()

    def _recortar(self, ahora: float) -> None:
        limite = ahora - self.ventana_min * 60
        for d in (self._rmssd, self._rpm):
            while d and d[0][0] < limite:
                d.popleft()

    def actualizar(self, ahora: float, reposo: bool, rmssd: Optional[float] = None,
                   rpm: Optional[float] = None) -> bool:
        """True cuando hay que avisar. ``reposo`` False (esfuerzo, sin banda…) descarta la ventana."""
        if not reposo:
            self.reiniciar()
            return False
        if rpm and rpm > 0:
            self._rpm.append((ahora, rpm))
        if rmssd is None:
            self._recortar(ahora)
            return False
        self._rmssd.append((ahora, rmssd))
        self._recortar(ahora)
        if self._ultimo_aviso is not None and ahora - self._ultimo_aviso < ESPERA_TRAS_AVISO_S:
            return False
        if self._evaluar(ahora):
            self._ultimo_aviso = ahora
            self.reiniciar()
            return True
        return False

    def _evaluar(self, ahora: float) -> bool:
        ventana = self.ventana_min * 60
        if not self._rmssd or not self._rpm or ahora - self._rmssd[0][0] < 0.8 * ventana:
            return False
        t0, tercio = ahora - ventana, ventana / 3

        def media(d, a, b):
            v = [x for t, x in d if a <= t < b]
            return v

        r1, r3 = media(self._rmssd, t0, t0 + tercio), media(self._rmssd, ahora - tercio, ahora + 1)
        p1, p3 = media(self._rpm, t0, t0 + tercio), media(self._rpm, ahora - tercio, ahora + 1)
        if len(r1) < MIN_PUNTOS_RMSSD or len(r3) < MIN_PUNTOS_RMSSD or len(p1) < 10 or len(p3) < 10:
            return False
        base = statistics.fmean(r1)
        if base <= 0 or statistics.fmean(r3) > base * (1 - CAIDA_RMSSD):
            return False
        return statistics.fmean(p3) - statistics.fmean(p1) >= SUBIDA_RPM
