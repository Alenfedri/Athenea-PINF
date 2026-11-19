"""Alertas por umbral en directo: Zona 5, temperatura elevada y pérdida de contacto de la banda.

``evaluar`` devuelve las alertas activas (para el banner, mientras dure la condición) y las que
deben sonar ahora: como mucho una vez cada ``COOLDOWN_S`` por tipo y nunca en silencio.
Solo se evalúa con la banda CONECTADA.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from domain.calidad_contacto import CalidadContacto
from domain.ui_state import ConexionEstado, VitaBandUiState
from domain.zonas_actividad import FC_MAX_REFERENCIA, LIMITES_ZONAS

COOLDOWN_S = 20.0
TEMP_ELEVADA_C = 38.0

ZONA5, TEMPERATURA, SIN_CONTACTO = "ZONA5", "TEMPERATURA", "SIN_CONTACTO"
ORDEN = (ZONA5, TEMPERATURA, SIN_CONTACTO)


@dataclass(frozen=True)
class Alerta:
    tipo: str
    texto: str


@dataclass(frozen=True)
class ResultadoAlertas:
    activas: tuple[Alerta, ...] = ()
    sonar: tuple[Alerta, ...] = ()


def _primer_numero(texto: str) -> Optional[float]:
    try:
        v = float(texto.split()[0].replace(",", "."))
    except (ValueError, AttributeError, IndexError):
        return None
    return v if v == v and abs(v) != float("inf") else None


class SupervisorAlertas:

    def __init__(self, fc_max: float = FC_MAX_REFERENCIA, reloj: Callable[[], float] = time.monotonic):
        self.fc_max = float(fc_max)
        self.silenciado = False
        self._reloj = reloj
        self._ultimo: dict[str, float] = {}

    def activas(self, state: VitaBandUiState) -> tuple[Alerta, ...]:
        if state.conexionEstado != ConexionEstado.CONECTADO:
            return ()
        salida = []
        bpm = _primer_numero(state.bpmTexto)
        if bpm is not None and bpm > 0 and bpm >= LIMITES_ZONAS[-1] * self.fc_max:
            salida.append(Alerta(ZONA5, f"Zona 5: {bpm:.0f} BPM (≥ 90 % de la FC máx.)"))
        temp = _primer_numero(state.tempTexto)
        if temp is not None and temp >= TEMP_ELEVADA_C:
            salida.append(Alerta(TEMPERATURA, f"Temperatura elevada: {temp:.1f} °C".replace(".", ",")))
        if state.calidadContacto == CalidadContacto.SIN_SENAL:
            salida.append(Alerta(SIN_CONTACTO, "Pérdida de contacto de la banda pectoral"))
        return tuple(salida)

    def evaluar(self, state: VitaBandUiState) -> ResultadoAlertas:
        activas = self.activas(state)
        sonar = []
        if not self.silenciado:
            ahora = self._reloj()
            for a in activas:
                ultimo = self._ultimo.get(a.tipo)
                if ultimo is None or ahora - ultimo >= COOLDOWN_S:
                    self._ultimo[a.tipo] = ahora
                    sonar.append(a)
        return ResultadoAlertas(activas, tuple(sonar))
