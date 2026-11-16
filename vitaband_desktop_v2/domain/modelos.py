"""Modelos de datos del dominio (sin Qt ni base de datos)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

# RF-43: a qué historial pertenece una medición
ETIQUETA_PERIODICO = "PERIODICO"
ETIQUETA_ACTIVIDAD = "ACTIVIDAD"
ETIQUETA_AMBOS = "AMBOS"
ETIQUETAS = (ETIQUETA_PERIODICO, ETIQUETA_ACTIVIDAD, ETIQUETA_AMBOS)

# Códigos de nivel de actividad del firmware
NIVEL_REPOSO = 0
NIVEL_MEDIA = 1
NIVEL_INTENSA = 2
NIVEL_SIN_CLASIFICAR = 255
NIVELES_VALIDOS = (NIVEL_REPOSO, NIVEL_MEDIA, NIVEL_INTENSA, NIVEL_SIN_CLASIFICAR)


@dataclass(frozen=True)
class Medicion:
    id: int
    uid: str
    ts: int                              # segundos Unix (UTC)
    bpm: float
    rpm: Optional[float]
    temp_c: Optional[float]
    nivel_actividad: Optional[int]
    etiqueta: str
    actividad_id: Optional[int]

    @property
    def instante(self) -> datetime:
        """Fecha y hora local de la medición (RF-13)."""
        return datetime.fromtimestamp(self.ts)

    @property
    def media_bpm(self) -> float:
        return self.bpm

    @property
    def es_periodica(self) -> bool:
        return self.etiqueta in (ETIQUETA_PERIODICO, ETIQUETA_AMBOS)

    @property
    def es_de_actividad(self) -> bool:
        return self.etiqueta in (ETIQUETA_ACTIVIDAD, ETIQUETA_AMBOS)


@dataclass(frozen=True)
class Actividad:
    id: int
    uid: str
    inicio_ts: int
    fin_ts: int
    tipo: Optional[str]                  # RF-50 (opcional): p. ej. "carrera"

    @property
    def duracion_s(self) -> int:
        return max(0, self.fin_ts - self.inicio_ts)

    @property
    def inicio(self) -> datetime:
        return datetime.fromtimestamp(self.inicio_ts)

    @property
    def fin(self) -> datetime:
        return datetime.fromtimestamp(self.fin_ts)


@dataclass(frozen=True)
class ObservacionGuardada:
    id: int
    tipo: str                            # "DIARIA" | "ACTIVIDAD"
    clave: str                           # fecha ISO (diaria) o id de actividad
    actividad_id: Optional[int]
    periodo_inicio_ts: int
    periodo_fin_ts: int
    texto: str                           # líneas separadas por \n
    generada_ts: int

    @property
    def lineas(self) -> list[str]:
        return self.texto.split("\n")
