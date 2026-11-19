"""Análisis puro de series de mediciones: estadísticas, agrupación e interrupciones.

* RF-22: media, mínimo y máximo.
* RF-16: resumen de periodos largos agrupando por minuto, hora o día.
* RF-27: detección de interrupciones (periodos sin datos) para no dibujar como
  mediciones lo que no existe.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional, Sequence

from domain.modelos import NIVEL_SIN_CLASIFICAR, Medicion

VARIABLES = ("bpm", "rpm", "temp", "actividad")

NOMBRE_VARIABLE = {
    "bpm": "Frecuencia cardíaca",
    "rpm": "Frecuencia respiratoria",
    "temp": "Temperatura cutánea",
    "actividad": "Nivel de actividad",
}

UNIDAD_VARIABLE = {"bpm": "BPM", "rpm": "RPM", "temp": "°C", "actividad": ""}

SIN_AGRUPAR = "sin_agrupar"
RESOLUCIONES = ("minuto", "hora", "dia")

_SEGUNDOS_DIA = 86400


# --------------------------------------------------
# VARIABLES Y ESTADÍSTICAS (RF-22)
# --------------------------------------------------

def valor_de(m: Medicion, variable: str) -> Optional[float]:
    """Valor de una variable en una medición, o None si no existe o no es aplicable."""
    if variable == "bpm":
        v = m.bpm
    elif variable == "rpm":
        v = m.rpm
    elif variable == "temp":
        v = m.temp_c
    elif variable == "actividad":
        if m.nivel_actividad is None or m.nivel_actividad == NIVEL_SIN_CLASIFICAR:
            return None
        v = float(m.nivel_actividad)
    else:
        raise ValueError(f"Variable desconocida: {variable}")

    if v is None or not math.isfinite(v):
        return None
    return float(v)


def pares_de(mediciones: Iterable[Medicion], variable: str) -> list[tuple[int, float]]:
    """(ts, valor) de las mediciones que tienen un valor real para la variable."""
    pares = []
    for m in mediciones:
        v = valor_de(m, variable)
        if v is not None:
            pares.append((m.ts, v))
    return pares


@dataclass(frozen=True)
class Estadisticas:
    cantidad: int
    media: float
    minimo: float
    maximo: float


def estadisticas(valores: Iterable[float]) -> Optional[Estadisticas]:
    """Media, mínimo y máximo; None si no hay valores válidos."""
    validos = [v for v in valores if v is not None and math.isfinite(v)]
    if not validos:
        return None
    return Estadisticas(
        cantidad=len(validos),
        media=sum(validos) / len(validos),
        minimo=min(validos),
        maximo=max(validos),
    )


# --------------------------------------------------
# AGRUPACIÓN (RF-16)
# --------------------------------------------------

def inicio_cubo(ts: int, resolucion: str) -> int:
    d = datetime.fromtimestamp(ts)
    if resolucion == "minuto":
        d = d.replace(second=0, microsecond=0)
    elif resolucion == "hora":
        d = d.replace(minute=0, second=0, microsecond=0)
    elif resolucion == "dia":
        d = d.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        raise ValueError(f"Resolución desconocida: {resolucion}")
    return int(d.timestamp())


def siguiente_cubo(inicio: int, resolucion: str) -> int:
    d = datetime.fromtimestamp(inicio)
    paso = {"minuto": timedelta(minutes=1), "hora": timedelta(hours=1), "dia": timedelta(days=1)}
    if resolucion not in paso:
        raise ValueError(f"Resolución desconocida: {resolucion}")
    return int((d + paso[resolucion]).timestamp())


@dataclass(frozen=True)
class Cubo:
    inicio: int
    fin: int
    cantidad: int
    media: Optional[float]
    minimo: Optional[float]
    maximo: Optional[float]

    @property
    def vacio(self) -> bool:
        return self.cantidad == 0


def agrupar(
    pares: Sequence[tuple[int, float]], desde_ts: int, hasta_ts: int, resolucion: str
) -> list[Cubo]:
    """Agrupa (ts, valor) en cubos consecutivos; los cubos sin datos se devuelven vacíos."""
    por_cubo: dict[int, list[float]] = {}
    for ts, v in pares:
        if desde_ts <= ts < hasta_ts:
            por_cubo.setdefault(inicio_cubo(ts, resolucion), []).append(v)

    cubos: list[Cubo] = []
    actual = inicio_cubo(desde_ts, resolucion)
    while actual < hasta_ts:
        siguiente = siguiente_cubo(actual, resolucion)
        valores = por_cubo.get(actual)
        if valores:
            cubos.append(Cubo(actual, siguiente, len(valores),
                              sum(valores) / len(valores), min(valores), max(valores)))
        else:
            cubos.append(Cubo(actual, siguiente, 0, None, None, None))
        actual = siguiente
    return cubos


def resolucion_automatica(desde_ts: int, hasta_ts: int) -> str:
    """Resolución recomendada según la longitud del periodo (RF-16)."""
    dias = (hasta_ts - desde_ts) / _SEGUNDOS_DIA
    if dias <= 2:
        return SIN_AGRUPAR
    if dias <= 14:
        return "hora"
    return "dia"


# --------------------------------------------------
# INTERRUPCIONES (RF-27)
# --------------------------------------------------

@dataclass(frozen=True)
class Interrupcion:
    inicio: int
    fin: int

    @property
    def duracion_s(self) -> int:
        return self.fin - self.inicio


def umbral_interrupcion(timestamps: Sequence[int], minimo_s: float, factor: float = 3.0) -> float:
    """Separación a partir de la cual se considera que hay una interrupción.

    Se adapta al ritmo real de los datos (mediana de las separaciones) pero nunca
    baja de ``minimo_s``.
    """
    if len(timestamps) < 2:
        return float(minimo_s)
    dts = [b - a for a, b in zip(timestamps, timestamps[1:]) if b > a]
    if not dts:
        return float(minimo_s)
    return max(float(minimo_s), factor * statistics.median(dts))


def detectar_interrupciones(
    timestamps: Sequence[int], desde_ts: int, hasta_ts: int, umbral_s: float
) -> list[Interrupcion]:
    """Periodos sin datos dentro de [desde_ts, hasta_ts], incluidos los extremos."""
    if hasta_ts <= desde_ts:
        return []

    dentro = sorted(t for t in timestamps if desde_ts <= t <= hasta_ts)
    if not dentro:
        return [Interrupcion(desde_ts, hasta_ts)]

    huecos: list[Interrupcion] = []
    if dentro[0] - desde_ts > umbral_s:
        huecos.append(Interrupcion(desde_ts, dentro[0]))
    for a, b in zip(dentro, dentro[1:]):
        if b - a > umbral_s:
            huecos.append(Interrupcion(a, b))
    if hasta_ts - dentro[-1] > umbral_s:
        huecos.append(Interrupcion(dentro[-1], hasta_ts))
    return huecos


def serie_con_huecos(
    pares: Sequence[tuple[int, float]], umbral_s: float
) -> tuple[list[float], list[float]]:
    """x, y con un NaN intercalado en cada interrupción para que la línea se corte."""
    xs: list[float] = []
    ys: list[float] = []
    anterior: Optional[int] = None
    for ts, v in pares:
        if anterior is not None and ts - anterior > umbral_s:
            xs.append(anterior + 1.0)
            ys.append(float("nan"))
        xs.append(float(ts))
        ys.append(float(v))
        anterior = ts
    return xs, ys


# --------------------------------------------------
# AYUDAS DE FECHA
# --------------------------------------------------

def rango_de_dias(desde, hasta) -> tuple[int, int]:
    """[00:00 de ``desde``, 00:00 del día siguiente a ``hasta``) en segundos Unix locales."""
    ini = datetime(desde.year, desde.month, desde.day)
    fin = datetime(hasta.year, hasta.month, hasta.day) + timedelta(days=1)
    return int(ini.timestamp()), int(fin.timestamp())
