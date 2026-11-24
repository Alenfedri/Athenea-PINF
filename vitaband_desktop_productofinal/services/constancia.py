"""Constancia de entrenamiento: minutos y kcal por día, niveles del mapa de calor, objetivo y rachas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Mapping, Optional

from services.calculos_fisiologicos import PerfilFisiologico, kcal_actividad
from services.metricas_avanzadas import trimp
from services.repositorio_historial import RepositorioHistorial

SEMANAS_MAPA = 12
NIVELES_MIN = (1, 15, 30, 60)            # límites inferiores de los niveles 1..4 (0 = sin actividad)
OBJETIVO_DEFECTO_MIN = 150


@dataclass
class DiaActividad:
    minutos: float = 0.0
    kcal: float = 0.0
    trimp: float = 0.0
    sesiones: int = 0


def nivel(minutos: float) -> int:
    """0 (nada) a 4 (≥ 60 min)."""
    return sum(minutos >= lim for lim in NIVELES_MIN)


def lunes(d: date) -> date:
    return d - timedelta(days=d.weekday())


def primer_dia_mapa(hoy: date) -> date:
    """Lunes de hace 11 semanas: el mapa ocupa 12 columnas semanales, la última es la actual."""
    return lunes(hoy) - timedelta(weeks=SEMANAS_MAPA - 1)


def resumen_dias(repo: RepositorioHistorial, desde: date, hoy: date,
                 perfil: Optional[PerfilFisiologico] = None) -> dict[date, DiaActividad]:
    ini = int(datetime(desde.year, desde.month, desde.day).timestamp())
    fin = int(datetime(hoy.year, hoy.month, hoy.day).timestamp()) + 86400
    dias: dict[date, DiaActividad] = {}
    for a in repo.actividades_rango(ini, fin):
        ms = repo.mediciones_de_actividad(a.id)
        d = dias.setdefault(datetime.fromtimestamp(a.inicio_ts).date(), DiaActividad())
        d.minutos += a.duracion_s / 60.0
        d.kcal += kcal_actividad(ms, perfil) or 0.0
        d.trimp += trimp(ms) or 0.0
        d.sesiones += 1
    return dias


def minutos_semana(dias: Mapping[date, DiaActividad], semana_lunes: date) -> float:
    return sum(dias[d].minutos for d in (semana_lunes + timedelta(days=i) for i in range(7)) if d in dias)


def racha_semanas(dias: Mapping[date, DiaActividad], hoy: date, objetivo_min: float) -> int:
    """Semanas consecutivas cumpliendo el objetivo. La semana en curso suma si ya lo cumple; si aún no,
    no rompe la racha."""
    semana = lunes(hoy)
    n = 1 if minutos_semana(dias, semana) >= objetivo_min else 0
    semana -= timedelta(weeks=1)
    primera = min(dias, default=hoy)
    while semana + timedelta(days=6) >= primera and minutos_semana(dias, semana) >= objetivo_min:
        n += 1
        semana -= timedelta(weeks=1)
    return n


def racha_dias(dias: Mapping[date, DiaActividad], hoy: date) -> int:
    """Días seguidos con actividad. Si hoy aún no hay, se cuenta desde ayer."""
    d = hoy if dias.get(hoy) and dias[hoy].minutos > 0 else hoy - timedelta(days=1)
    n = 0
    while dias.get(d) and dias[d].minutos > 0:
        n += 1
        d -= timedelta(days=1)
    return n


def kcal_semana(dias: Mapping[date, DiaActividad], hoy: date) -> float:
    return sum(v.kcal for d, v in dias.items() if hoy - timedelta(days=6) <= d <= hoy)
