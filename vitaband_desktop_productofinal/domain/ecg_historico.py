"""Representación compacta del ECG histórico (RF-33) y reducción para su vista (RF-34).

Decisión de diseño (el DAC deja el nivel de detalle "a determinar"):
  * Se guarda, por cada SEGUNDO, el valor mínimo y máximo de la señal (su
    envolvente). Es suficiente para ver la forma general y los artefactos de un
    periodo, y ocupa ~4 bytes por segundo (~340 KB por día de registro continuo).
  * No es la señal completa a 100 Hz: no permite medir la morfología de cada latido.
  * Los segundos se agrupan en bloques de un minuto (60 pares min/max en int16).
    Un segundo sin dato se codifica con NODATA, para distinguirlo de una señal real.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

NODATA = -32768
SEGUNDOS_POR_BLOQUE = 60
VALORES_POR_BLOQUE = SEGUNDOS_POR_BLOQUE * 2
BYTES_POR_BLOQUE = VALORES_POR_BLOQUE * 2
_FORMATO = f"<{VALORES_POR_BLOQUE}h"


@dataclass(frozen=True)
class SegundoEcg:
    ts: int          # segundo Unix (UTC)
    minimo: int
    maximo: int


def _a_int16(v: float) -> int:
    return max(-32767, min(32767, int(round(v))))


class AcumuladorEcg:
    """Convierte muestras sueltas en envolventes de un segundo."""

    def __init__(self) -> None:
        self._ts: Optional[int] = None
        self._min = 0.0
        self._max = 0.0

    def agregar(self, ts: int, valor: float) -> list[SegundoEcg]:
        """Añade una muestra; devuelve los segundos que quedan completos."""
        if not math.isfinite(valor):
            return []

        completos: list[SegundoEcg] = []
        if self._ts is not None and ts != self._ts:
            completos.append(self._cerrar())

        if self._ts is None:
            self._ts, self._min, self._max = ts, valor, valor
        else:
            self._min = min(self._min, valor)
            self._max = max(self._max, valor)
        return completos

    def vaciar(self) -> list[SegundoEcg]:
        """Cierra el segundo en curso (p. ej. al cortarse el enlace)."""
        return [self._cerrar()] if self._ts is not None else []

    def _cerrar(self) -> SegundoEcg:
        seg = SegundoEcg(self._ts, _a_int16(self._min), _a_int16(self._max))
        self._ts = None
        return seg


# --------------------------------------------------
# BLOQUES DE UN MINUTO
# --------------------------------------------------

def bloque_vacio() -> list[int]:
    return [NODATA] * VALORES_POR_BLOQUE


def empaquetar(valores: Sequence[int]) -> bytes:
    if len(valores) != VALORES_POR_BLOQUE:
        raise ValueError("Bloque ECG con tamaño incorrecto")
    return struct.pack(_FORMATO, *valores)


def desempaquetar(datos: bytes) -> list[int]:
    if len(datos) != BYTES_POR_BLOQUE:
        raise ValueError("Bloque ECG corrupto")
    return list(struct.unpack(_FORMATO, datos))


def minuto_de(ts: int) -> int:
    return ts // SEGUNDOS_POR_BLOQUE


def fusionar(existente: list[int], segundos: Sequence[SegundoEcg]) -> list[int]:
    """Rellena solo los segundos sin dato: lo ya guardado nunca se sobrescribe (sin duplicar)."""
    bloque = list(existente)
    for s in segundos:
        i = (s.ts % SEGUNDOS_POR_BLOQUE) * 2
        if bloque[i] == NODATA:
            bloque[i] = s.minimo
            bloque[i + 1] = s.maximo
    return bloque


def segundos_de_bloque(minuto: int, valores: Sequence[int]) -> list[SegundoEcg]:
    salida = []
    for seg in range(SEGUNDOS_POR_BLOQUE):
        mn, mx = valores[seg * 2], valores[seg * 2 + 1]
        if mn != NODATA:
            salida.append(SegundoEcg(minuto * SEGUNDOS_POR_BLOQUE + seg, mn, mx))
    return salida


# --------------------------------------------------
# REDUCCIÓN PARA LA VISTA COMPACTA (RF-34)
# --------------------------------------------------

@dataclass(frozen=True)
class EcgReducido:
    x: np.ndarray            # centro de cada intervalo (segundos Unix)
    minimo: np.ndarray       # NaN donde no hay datos
    maximo: np.ndarray
    ancho_s: float           # ancho de cada intervalo
    segundos_con_dato: int

    @property
    def tiene_datos(self) -> bool:
        return self.segundos_con_dato > 0


def reducir(
    segundos: Sequence[SegundoEcg], desde_ts: int, hasta_ts: int, n_bins: int
) -> EcgReducido:
    """Resume los segundos almacenados en ``n_bins`` intervalos (mín. y máx. por intervalo).

    El número de intervalos se limita a la duración en segundos, de modo que cada
    intervalo cubre al menos un segundo.
    """
    span = max(1, hasta_ts - desde_ts)
    n = max(1, min(int(n_bins), span))
    minimos = np.full(n, np.nan)
    maximos = np.full(n, np.nan)

    contados = 0
    for s in segundos:
        i = int((s.ts - desde_ts) * n / span)
        if 0 <= i < n:
            contados += 1
            minimos[i] = s.minimo if np.isnan(minimos[i]) else min(minimos[i], s.minimo)
            maximos[i] = s.maximo if np.isnan(maximos[i]) else max(maximos[i], s.maximo)

    ancho = span / n
    x = desde_ts + (np.arange(n) + 0.5) * ancho
    return EcgReducido(x, minimos, maximos, ancho, contados)
