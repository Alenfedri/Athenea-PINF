"""Disciplinas deportivas de las actividades y récords personales (PRs) por disciplina."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Optional, Sequence

from domain.zonas_actividad import repartir_zonas

DISCIPLINAS = ("Carrera", "Rodillo/Ciclismo", "Fuerza", "Caminata", "Otra")
MIN_DURACION_MIN = 10          # sesiones más cortas no optan a PR
MIN_Z2_S = 300                 # el PR de Z2 exige al menos 5 min en Z2
FRANJAS = ((10, 30, "10–30 min"), (30, 60, "30–60 min"), (60, 10_000, "más de 60 min"))


@dataclass(frozen=True)
class ResumenSesion:
    id: int
    disciplina: Optional[str]
    duracion_min: float
    bpm_medio: Optional[float]
    z2_s: float


def resumen_sesion(repo, actividad, disciplina: Optional[str]) -> ResumenSesion:
    ms = repo.mediciones_de_actividad(actividad.id)
    bpm = [m.bpm for m in ms if m.bpm and m.bpm > 0]
    z = repartir_zonas(ms)
    return ResumenSesion(actividad.id, disciplina, actividad.duracion_s / 60.0,
                         statistics.fmean(bpm) if bpm else None, z.segundos[1] if z else 0.0)


def resumenes(repo, desde_ts: int, hasta_ts: int) -> list[ResumenSesion]:
    etiquetas = repo.disciplinas()
    return [resumen_sesion(repo, a, etiquetas.get(a.id)) for a in repo.actividades_rango(desde_ts, hasta_ts)]


def franja(minutos: float) -> Optional[str]:
    for lo, hi, nombre in FRANJAS:
        if lo <= minutos < hi:
            return nombre
    return None


def records_personales(sesiones: Sequence[ResumenSesion]) -> dict[int, list[str]]:
    """{id de sesión: textos de PR}. Solo sesiones con disciplina y con al menos otra con la que compararse.

    * Un empate exacto no es récord.
    * Menor BPM medio a esfuerzo equivalente: misma disciplina y misma franja de duración.
    * Mayor tiempo en Z2: misma disciplina.
    """
    prs: dict[int, list[str]] = {}
    grupos: dict[tuple, list[ResumenSesion]] = {}
    for s in sesiones:
        if s.disciplina and s.bpm_medio and s.duracion_min >= MIN_DURACION_MIN and franja(s.duracion_min):
            grupos.setdefault((s.disciplina, franja(s.duracion_min)), []).append(s)
    for (disc, fr), g in grupos.items():
        if len(g) >= 2:
            mejor = min(g, key=lambda s: s.bpm_medio)
            if sum(1 for s in g if s.bpm_medio == mejor.bpm_medio) == 1:          # un empate no es récord
                prs.setdefault(mejor.id, []).append(f"PR menor BPM medio en {disc} ({fr})")
    por_disc: dict[str, list[ResumenSesion]] = {}
    for s in sesiones:
        if s.disciplina and s.z2_s >= MIN_Z2_S:
            por_disc.setdefault(s.disciplina, []).append(s)
    for disc, g in por_disc.items():
        if len(g) >= 2:
            mejor = max(g, key=lambda s: s.z2_s)
            if sum(1 for s in g if s.z2_s == mejor.z2_s) == 1:
                prs.setdefault(mejor.id, []).append(f"PR más tiempo en Z2 en {disc} ({mejor.z2_s / 60:.0f} min)")
    return prs


def aviso_comparacion(disc_a: Optional[str], disc_b: Optional[str]) -> Optional[str]:
    if disc_a and disc_b and disc_a != disc_b:
        return (f"Atención: comparas sesiones de distinta disciplina ({disc_a} frente a {disc_b}); "
                "las diferencias de pulso pueden deberse al tipo de esfuerzo.")
    return None
