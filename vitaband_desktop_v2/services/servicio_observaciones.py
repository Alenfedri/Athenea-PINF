"""Genera y guarda las observaciones orientativas (RF-23, 24, 25, 29, 47, 48, 49).

Solo orquesta: la lógica y los textos viven en ``domain.observaciones``. Las
observaciones se guardan (RF-29) y solo se reescriben cuando el texto cambia.
Son informativas, no diagnósticos.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable

import statistics

from domain import hrv
from domain import observaciones as obs
from services.repositorio_historial import AMBITO_PERIODICO, RepositorioHistorial

DIAS_BASE = 7                   # días previos usados como referencia (evolución, patrones, FC reposo)
MAX_DIAS = 60
MAX_ACTIVIDADES = 100
_DIA = 86400


@dataclass(frozen=True)
class ResultadoObservaciones:
    diarias: int = 0            # observaciones diarias creadas o actualizadas
    actividades: int = 0        # observaciones de actividad creadas o actualizadas

    @property
    def total(self) -> int:
        return self.diarias + self.actividades


def _ts_dia(d: date) -> int:
    return int(datetime(d.year, d.month, d.day).timestamp())


class ServicioObservaciones:

    def __init__(
        self,
        repositorio: RepositorioHistorial,
        intervalo_registro_s: float = 10.0,
        umbrales: obs.Umbrales = obs.Umbrales(),
        reloj: Callable[[], float] = time.time,
    ):
        self._repo = repositorio
        self._intervalo_s = float(intervalo_registro_s)
        self._umbrales = umbrales
        self._reloj = reloj

    def actualizar_todo(self) -> ResultadoObservaciones:
        ahora = int(self._reloj())
        return ResultadoObservaciones(self._actualizar_diarias(ahora), self._actualizar_actividades(ahora))

    # ------------------------------------------------------------------

    def _actualizar_diarias(self, ahora: int) -> int:
        rango = self._repo.rango_periodico()
        if rango is None:
            return 0

        ultimo_dia = datetime.fromtimestamp(rango[1]).date()
        primer_dia = max(datetime.fromtimestamp(rango[0]).date(), ultimo_dia - timedelta(days=MAX_DIAS - 1))

        ini = _ts_dia(primer_dia - timedelta(days=DIAS_BASE))
        fin = _ts_dia(ultimo_dia + timedelta(days=1))
        por_dia: dict[date, list] = defaultdict(list)
        for m in self._repo.mediciones_rango(ini, fin, AMBITO_PERIODICO):
            por_dia[m.instante.date()].append(m)

        hrv_dia: dict[date, list[hrv.ResultadoHrv]] = defaultdict(list)
        for v in self._repo.hrv_rango(ini, fin):
            hrv_dia[datetime.fromtimestamp(v.ts).date()].append(v)

        cambios = 0
        dia = primer_dia
        while dia <= ultimo_dia:
            mediciones = por_dia.get(dia, [])
            if mediciones:
                anteriores = {d: por_dia[d] for k in range(1, DIAS_BASE + 1)
                              if (d := dia - timedelta(days=k)) in por_dia}
                lineas = obs.observacion_diaria(
                    dia, mediciones, anteriores, self._intervalo_s, ahora, self._umbrales,
                    self._lineas_hrv(dia, hrv_dia))
                if lineas and self._repo.guardar_observacion(
                    "DIARIA", dia.isoformat(), "\n".join(lineas),
                    _ts_dia(dia), _ts_dia(dia + timedelta(days=1)), ahora,
                ):
                    cambios += 1
            dia += timedelta(days=1)
        return cambios

    @staticmethod
    def _lineas_hrv(dia: date, hrv_dia: dict) -> list[str]:
        """Recuperación del día; la referencia propia es la media de los días previos con HRV."""
        previos = []
        for k in range(1, DIAS_BASE + 1):
            vs = hrv_dia.get(dia - timedelta(days=k))
            if vs and len(vs) >= hrv.UmbralesHrv.min_ventanas:
                primeras = sorted(vs, key=lambda v: v.ts)[:hrv.UmbralesHrv.ventanas_dia]
                previos.append(statistics.median(v.rmssd_ms for v in primeras))
        base = statistics.fmean(previos) if previos else None
        return hrv.lineas_recuperacion(hrv_dia.get(dia, []), base)

    def _actualizar_actividades(self, ahora: int) -> int:
        cambios = 0
        for act in self._repo.actividades_rango(0, ahora + _DIA)[:MAX_ACTIVIDADES]:
            if act.fin_ts > ahora:
                continue        # todavía en curso: se valorará al terminar
            previas = self._repo.mediciones_rango(act.inicio_ts - DIAS_BASE * _DIA, act.inicio_ts)
            referencia = obs.fc_reposo(previas, self._umbrales)
            lineas = obs.resumen_actividad(
                act, self._repo.mediciones_de_actividad(act.id), referencia, self._umbrales)
            if self._repo.guardar_observacion(
                "ACTIVIDAD", str(act.id), "\n".join(lineas),
                act.inicio_ts, act.fin_ts, ahora, actividad_id=act.id,
            ):
                cambios += 1
        return cambios
