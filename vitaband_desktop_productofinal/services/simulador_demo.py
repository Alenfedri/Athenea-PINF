"""Modo Demo: genera telemetría sintética realista (ECG a 100 Hz con complejo P-QRS-T, BPM, respiración) para
presentaciones sin banda física. Sin Qt ni SQLite: solo produce paquetes (ecg, bpm, rpm, temp_c, cod_actividad, cod_aviso)."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

FS = 100                                           # Hz, como la banda pectoral


@dataclass(frozen=True)
class Escenario:
    nombre: str
    bpm: float
    rpm: float
    temp_c: float
    cod_actividad: int
    variabilidad_ms: float                         # desviación del R-R (baja = estrés)
    amplitud_rsa: float                            # arritmia sinusal respiratoria en BPM


ESCENARIOS = {
    "Reposo": Escenario("Reposo", 62.0, 12.0, 33.6, 0, 45.0, 4.0),
    "Esfuerzo Z3": Escenario("Esfuerzo Z3", 145.0, 28.0, 35.4, 3, 12.0, 1.5),
    "Estrés Escritorio": Escenario("Estrés Escritorio", 88.0, 18.0, 33.9, 0, 14.0, 1.0),
}


def _gauss(u: float, mu: float, sd: float) -> float:
    return math.exp(-((u - mu) ** 2) / (2 * sd * sd))


def complejo_pqrst(u: float, rr_s: float = 0.8) -> float:
    """Latido normalizado (R = 1) en la fase u ∈ [0, 1); anchuras fijas en segundos para que el pico R siempre se muestree."""
    def g(mu: float, sd_s: float) -> float:
        return _gauss(u, mu, sd_s / rr_s)
    return 0.14 * g(0.18, 0.040) - 0.16 * g(0.34, 0.014) + 1.0 * g(0.37, 0.014) - 0.28 * g(0.40, 0.016) + 0.26 * g(0.62, 0.070)


class GeneradorDemo:
    def __init__(self, escenario: str = "Reposo", semilla: int = 7):
        self.escenario = ESCENARIOS.get(escenario, ESCENARIOS["Reposo"])
        self._rnd = random.Random(semilla)
        self._n = 0                                # muestras emitidas
        self._fase = 0.0                           # progreso del latido actual (0..1)
        self._rr_s = 60.0 / self.escenario.bpm
        self.rr_ms: list[float] = []               # R-R generados (para pruebas)

    @property
    def tiempo(self) -> float:
        return self._n / FS

    def _bpm_instantaneo(self) -> float:
        e = self.escenario
        return e.bpm + e.amplitud_rsa * math.sin(2 * math.pi * (e.rpm / 60.0) * self.tiempo)

    def siguiente(self) -> tuple[float, float, float, float, int, int]:
        e = self.escenario
        bpm = self._bpm_instantaneo()
        self._fase += 1.0 / (FS * self._rr_s)
        if self._fase >= 1.0:
            self._fase -= 1.0
            rr = 60.0 / bpm + self._rnd.gauss(0, e.variabilidad_ms / 1000.0)
            self._rr_s = min(max(rr, 0.35), 1.8)
            self.rr_ms.append(self._rr_s * 1000.0)
        ruido = self._rnd.gauss(0, 0.012)
        deriva = 0.03 * math.sin(2 * math.pi * 0.2 * self.tiempo)         # línea de base con la respiración
        ecg = 2048.0 + 600.0 * (complejo_pqrst(self._fase, self._rr_s) + ruido + deriva)
        self._n += 1
        rpm = e.rpm + self._rnd.gauss(0, 0.2)
        return ecg, round(bpm, 1), round(rpm, 1), e.temp_c, e.cod_actividad, 0
