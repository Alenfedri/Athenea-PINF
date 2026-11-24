"""Comparador de sesiones «Antes vs. Ahora»: dos actividades alineadas en el minuto 0.

Todo se calcula al vuelo con las mediciones de cada actividad; no se guarda nada.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Optional, Sequence

from domain.modelos import Actividad, Medicion

ANTES = "Antes"
AHORA = "Ahora"


@dataclass(frozen=True)
class SesionComparada:
    etiqueta: str                                   # «Antes» o «Ahora»
    actividad: Actividad
    bpm: tuple[tuple[float, float], ...]            # (minuto relativo, BPM)
    rpm: tuple[tuple[float, float], ...]            # (minuto relativo, RPM)
    mediciones: int
    bpm_medio: Optional[float]
    bpm_max: Optional[float]
    rpm_medio: Optional[float]

    @property
    def duracion_s(self) -> int:
        return self.actividad.duracion_s


@dataclass(frozen=True)
class Comparativa:
    antes: SesionComparada
    ahora: SesionComparada
    d_bpm_medio: Optional[float]                    # Ahora − Antes
    d_bpm_max: Optional[float]
    d_rpm_medio: Optional[float]
    d_duracion_s: int


def serie_relativa(
    mediciones: Sequence[Medicion], inicio_ts: int, variable: str,
) -> tuple[tuple[float, float], ...]:
    """(t_rel, valor) con t_rel = (t − inicio de la sesión) / 60, en minutos; la sesión arranca en 0."""
    pares = []
    for m in sorted(mediciones, key=lambda m: m.ts):
        v = m.bpm if variable == "bpm" else m.rpm
        if v is None or (variable == "bpm" and v <= 0):
            continue
        pares.append(((m.ts - inicio_ts) / 60.0, float(v)))
    return tuple(pares)


def _media(valores: Sequence[float]) -> Optional[float]:
    return statistics.fmean(valores) if valores else None


def _sesion(etiqueta: str, actividad: Actividad, mediciones: Sequence[Medicion]) -> SesionComparada:
    bpm = serie_relativa(mediciones, actividad.inicio_ts, "bpm")
    rpm = serie_relativa(mediciones, actividad.inicio_ts, "rpm")
    return SesionComparada(
        etiqueta, actividad, bpm, rpm, len(mediciones),
        _media([v for _, v in bpm]), max((v for _, v in bpm), default=None), _media([v for _, v in rpm]),
    )


def _resta(a: Optional[float], b: Optional[float]) -> Optional[float]:
    return None if a is None or b is None else a - b


def comparar(
    primera: tuple[Actividad, Sequence[Medicion]],
    segunda: tuple[Actividad, Sequence[Medicion]],
) -> Comparativa:
    """La más antigua es «Antes» y la más reciente «Ahora»; las diferencias son Ahora − Antes."""
    (a1, m1), (a2, m2) = sorted([primera, segunda], key=lambda p: (p[0].inicio_ts, p[0].id))
    antes, ahora = _sesion(ANTES, a1, m1), _sesion(AHORA, a2, m2)
    return Comparativa(
        antes, ahora,
        _resta(ahora.bpm_medio, antes.bpm_medio),
        _resta(ahora.bpm_max, antes.bpm_max),
        _resta(ahora.rpm_medio, antes.rpm_medio),
        ahora.duracion_s - antes.duracion_s,
    )
