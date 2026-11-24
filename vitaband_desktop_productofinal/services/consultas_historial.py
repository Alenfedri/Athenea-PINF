"""Consultas de solo lectura sobre el historial, listas para la interfaz (RF-13..16, 22, 27, 34, 45).

Reúne repositorio + análisis de dominio y devuelve estructuras inmutables. No
contiene lógica de pantalla ni de Qt.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from domain import analisis
from domain import ecg_historico as ecg
from domain.modelos import Actividad, Medicion, ObservacionGuardada
from services.repositorio_historial import (
    AMBITO_PERIODICO,
    RepositorioHistorial,
)

MAX_SPAN_ECG_S = 7 * 86400        # rango máximo que se reduce de una vez
_AUTO = "auto"
RESOLUCIONES_VALIDAS = (_AUTO, analisis.SIN_AGRUPAR) + analisis.RESOLUCIONES


@dataclass(frozen=True)
class SerieHistorica:
    variable: str
    desde_ts: int
    hasta_ts: int
    resolucion: str                                   # SIN_AGRUPAR | minuto | hora | dia (ya resuelta)
    mediciones: tuple[Medicion, ...]
    pares: tuple[tuple[int, float], ...]              # (ts, valor) de la variable
    cubos: tuple[analisis.Cubo, ...]                  # vacío si resolucion == SIN_AGRUPAR
    interrupciones: tuple[analisis.Interrupcion, ...]
    umbral_interrupcion_s: float
    estadisticas: Optional[analisis.Estadisticas]

    @property
    def tiempo_sin_datos_s(self) -> int:
        return sum(i.duracion_s for i in self.interrupciones)

    @property
    def agrupada(self) -> bool:
        return self.resolucion != analisis.SIN_AGRUPAR


@dataclass(frozen=True)
class ResumenActividad:
    actividad: Actividad
    mediciones: int
    fc: Optional[analisis.Estadisticas]


@dataclass(frozen=True)
class DetalleActividad:
    actividad: Actividad
    mediciones: tuple[Medicion, ...]
    estadisticas: dict[str, Optional[analisis.Estadisticas]]    # por variable
    interrupciones: tuple[analisis.Interrupcion, ...]
    observacion: Optional[ObservacionGuardada]
    ecg: tuple[ecg.SegundoEcg, ...]


class ConsultasHistorial:

    def __init__(
        self,
        repositorio: RepositorioHistorial,
        intervalo_registro_s: float = 10.0,
        reloj: Callable[[], float] = time.time,
    ):
        self._repo = repositorio
        self._intervalo_s = float(intervalo_registro_s)
        self._reloj = reloj

    # ------------------------------------------------------------------ periódico

    def rango_disponible(self) -> Optional[tuple[int, int]]:
        """(primer ts, último ts) del historial periódico."""
        return self._repo.rango_periodico()

    def mediciones(self, desde_ts: int, hasta_ts: int, ambito: Optional[str] = AMBITO_PERIODICO) -> list[Medicion]:
        return self._repo.mediciones_rango(desde_ts, hasta_ts, ambito)

    def serie(
        self,
        variable: str,
        desde_ts: int,
        hasta_ts: int,
        resolucion: str = _AUTO,
        ambito: Optional[str] = AMBITO_PERIODICO,
    ) -> SerieHistorica:
        if variable not in analisis.VARIABLES:
            raise ValueError(f"Variable desconocida: {variable}")
        if resolucion not in RESOLUCIONES_VALIDAS:
            raise ValueError(f"Resolución desconocida: {resolucion}")
        if hasta_ts <= desde_ts:
            raise ValueError("El rango debe tener fin posterior al inicio")

        mediciones = self._repo.mediciones_rango(desde_ts, hasta_ts, ambito)
        pares = analisis.pares_de(mediciones, variable)

        if resolucion == _AUTO:
            resolucion = analisis.resolucion_automatica(desde_ts, hasta_ts)
        cubos = analisis.agrupar(pares, desde_ts, hasta_ts, resolucion) \
            if resolucion != analisis.SIN_AGRUPAR else []

        # Las interrupciones solo se buscan donde pudo haber datos: desde el primer
        # registro del historial hasta ahora, no antes de que se empezara a medir (RF-27).
        timestamps = [m.ts for m in mediciones]
        umbral = analisis.umbral_interrupcion(timestamps, 3 * self._intervalo_s)
        ini, fin = desde_ts, min(hasta_ts, int(self._reloj()))
        if ambito == AMBITO_PERIODICO:
            global_ = self._repo.rango_periodico()
            if global_ is None:
                fin = ini                              # sin ningún dato: nada que marcar
            else:
                ini = max(ini, global_[0])
        interrupciones = analisis.detectar_interrupciones(timestamps, ini, fin, umbral)

        return SerieHistorica(
            variable, desde_ts, hasta_ts, resolucion,
            tuple(mediciones), tuple(pares), tuple(cubos), tuple(interrupciones), umbral,
            analisis.estadisticas(v for _, v in pares),
        )

    def ecg(self, desde_ts: int, hasta_ts: int, n_bins: int = 600) -> ecg.EcgReducido:
        """ECG histórico reducido para la vista compacta (RF-34)."""
        if hasta_ts - desde_ts > MAX_SPAN_ECG_S:
            raise ValueError("Rango de ECG demasiado largo; elige un periodo de hasta 7 días")
        return ecg.reducir(self._repo.ecg_rango(desde_ts, hasta_ts), desde_ts, hasta_ts, n_bins)

    def observaciones(self, desde_ts: int, hasta_ts: int, tipo: Optional[str] = None) -> list[ObservacionGuardada]:
        return self._repo.observaciones_rango(desde_ts, hasta_ts, tipo)

    # ------------------------------------------------------------------ actividades

    def actividades(self, desde_ts: int, hasta_ts: int) -> list[ResumenActividad]:
        """Actividades con inicio en el rango, de la más reciente a la más antigua (RF-45)."""
        salida = []
        for a in self._repo.actividades_rango(desde_ts, hasta_ts):
            ms = self._repo.mediciones_de_actividad(a.id)
            salida.append(ResumenActividad(a, len(ms), analisis.estadisticas(m.bpm for m in ms)))
        return salida

    def detalle_actividad(self, actividad_id: int) -> Optional[DetalleActividad]:
        actividad = self._repo.obtener_actividad(actividad_id)
        if actividad is None:
            return None
        ms = self._repo.mediciones_de_actividad(actividad_id)
        ts = [m.ts for m in ms]
        return DetalleActividad(
            actividad,
            tuple(ms),
            {v: analisis.estadisticas(v_ for _, v_ in analisis.pares_de(ms, v)) for v in analisis.VARIABLES},
            tuple(analisis.detectar_interrupciones(
                ts, actividad.inicio_ts, actividad.fin_ts, analisis.umbral_interrupcion(ts, 5))),
            self._repo.observacion_actividad(actividad_id),
            tuple(self._repo.ecg_rango(actividad.inicio_ts, actividad.fin_ts + 1)),
        )
