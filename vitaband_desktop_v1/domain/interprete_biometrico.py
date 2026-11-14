"""Reglas de dominio de VitaBand, puras y sin dependencias de Qt ni de MQTT.

Aquí viven:
  * los mapeos de códigos del firmware (actividad, avisos),
  * el formateo de métricas para la interfaz,
  * la validación y el parseo de los paquetes de telemetría,
  * la interpretación del tópico ``vitaband/{device_id}/status``.

Al no importar PySide6 ni paho, todo es testeable con ``unittest`` y reutilizable
en una futura versión móvil.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional, Union

from domain.ui_state import ConexionEstado

# --------------------------------------------------
# CONSTANTES DE TEXTO Y CÓDIGOS
# --------------------------------------------------

CODIGO_SIN_CLASIFICAR = 255

TEXTO_CALCULANDO = "Calculando..."
TEXTO_TEMP_SIN_DATOS = "-- °C"
ACTIVIDAD_SIN_CLASIFICAR = "En transición / Sin clasificar"
AVISO_NINGUNO = "Sin avisos"

MAPA_ACTIVIDAD: dict[int, str] = {
    0: "Baja / Reposo",
    1: "Media",
    2: "Intensa",
    CODIGO_SIN_CLASIFICAR: ACTIVIDAD_SIN_CLASIFICAR,
}

MAPA_AVISOS: dict[int, str] = {
    0: "Aviso experimental: niveles bajos en reposo",
    1: "Aviso experimental: FC elevada en reposo",
    2: "Aviso experimental: FC y FR elevadas en reposo",
    CODIGO_SIN_CLASIFICAR: AVISO_NINGUNO,
}

# Rango fisiológicamente plausible para aceptar una media de BPM en el historial.
BPM_MIN_VALIDO = 20.0
BPM_MAX_VALIDO = 250.0

# Clave opcional del JSON de telemetría con la media temporal de BPM,
# que el firmware envía cada 10 s (paquete ampliado de 12 bytes).
CLAVE_MEDIA_BPM = "media_bpm"


# --------------------------------------------------
# DESCRIPCIÓN DE CÓDIGOS Y FORMATEO
# --------------------------------------------------

def describir_actividad(codigo: int) -> str:
    return MAPA_ACTIVIDAD.get(codigo, ACTIVIDAD_SIN_CLASIFICAR)


def describir_aviso(codigo: int) -> str:
    return MAPA_AVISOS.get(codigo, AVISO_NINGUNO)


def formatear_metrica(valor: float, unidad: str, decimales: int = 1) -> str:
    """Texto de una métrica vital; valores no finitos o <= 0 se muestran como cálculo en curso."""
    if not math.isfinite(valor) or valor <= 0:
        return TEXTO_CALCULANDO
    return f"{valor:.{decimales}f} {unidad}"


def formatear_temperatura(temp_c: float) -> str:
    if not math.isfinite(temp_c):
        return TEXTO_TEMP_SIN_DATOS
    return f"{temp_c:.2f} °C"


def validar_media_bpm(valor: Optional[float]) -> bool:
    """True si la media de BPM es finita y está en el rango plausible."""
    return (
        valor is not None
        and math.isfinite(valor)
        and BPM_MIN_VALIDO <= valor <= BPM_MAX_VALIDO
    )


# --------------------------------------------------
# TELEMETRÍA
# --------------------------------------------------

@dataclass(frozen=True)
class PaqueteTelemetria:
    ecg: float
    bpm: float
    rpm: float
    temp_c: float
    cod_actividad: int
    cod_aviso: int
    media_bpm: Optional[float] = None  # solo presente cada ~10 s


def parsear_telemetria(payload: Mapping[str, Any]) -> PaqueteTelemetria:
    """Convierte el JSON de telemetría en un paquete tipado.

    Lanza KeyError / ValueError / TypeError si el mensaje es malformado.
    """
    media_cruda = payload.get(CLAVE_MEDIA_BPM)
    return PaqueteTelemetria(
        ecg=float(payload["ecg"]),
        bpm=float(payload["bpm"]),
        rpm=float(payload["rpm"]),
        temp_c=float(payload["temp"]),
        cod_actividad=int(payload["activity"]),
        cod_aviso=int(payload["alert"]),
        media_bpm=None if media_cruda is None else float(media_cruda),
    )


# --------------------------------------------------
# CONTRATO DEL TÓPICO /status
# --------------------------------------------------

class EstadoPasarela(Enum):
    """Estados explícitos del tópico ``vitaband/{device_id}/status`` (QoS 1, retain)."""

    CALIBRATING = "CALIBRATING"
    READY = "READY"
    OFFLINE = "OFFLINE"  # también lo publica el Last Will de la pasarela


_ESTADO_A_CONEXION: dict[EstadoPasarela, ConexionEstado] = {
    EstadoPasarela.CALIBRATING: ConexionEstado.CALIBRANDO,
    EstadoPasarela.READY: ConexionEstado.CONECTADO,
    EstadoPasarela.OFFLINE: ConexionEstado.ERROR_COMUNICACION,
}


def interpretar_estado_pasarela(payload: Union[bytes, str]) -> Optional[EstadoPasarela]:
    """Interpreta el payload de /status.

    Formato canónico: ``{"state": "READY"}``. Se tolera también el texto plano
    (``READY``), habitual en mensajes de Last Will. Devuelve None si no se reconoce.
    """
    if isinstance(payload, (bytes, bytearray)):
        try:
            texto = bytes(payload).decode("utf-8")
        except UnicodeDecodeError:
            return None
    else:
        texto = payload

    texto = texto.strip()
    if not texto:
        return None

    candidato: Any = texto
    try:
        objeto = json.loads(texto)
    except ValueError:
        objeto = None

    if isinstance(objeto, dict):
        candidato = objeto.get("state")
    elif isinstance(objeto, str):
        candidato = objeto

    if not isinstance(candidato, str):
        return None

    try:
        return EstadoPasarela(candidato.strip().upper())
    except ValueError:
        return None


def conexion_desde_estado(estado: EstadoPasarela) -> ConexionEstado:
    return _ESTADO_A_CONEXION[estado]
