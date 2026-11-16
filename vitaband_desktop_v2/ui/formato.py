"""Formateo de fechas, duraciones e interrupciones para la interfaz."""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from domain.analisis import Interrupcion
from domain.observaciones import formatear_duracion

FORMATO_FECHA_HORA = "%d/%m/%Y %H:%M:%S"


def fecha_hora(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime(FORMATO_FECHA_HORA)


def fecha_hora_corta(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%d/%m %H:%M")


def duracion(segundos: int) -> str:
    return formatear_duracion(segundos)


def texto_interrupciones(interrupciones: Sequence[Interrupcion], maximo: int = 5) -> str:
    """Resumen de los periodos sin datos (RF-27)."""
    if not interrupciones:
        return "Sin interrupciones en el registro."
    total = sum(i.duracion_s for i in interrupciones)
    lineas = [f"{len(interrupciones)} interrupción(es) · {duracion(total)} sin datos (sombreado naranja)"]
    for i in interrupciones[:maximo]:
        lineas.append(f"  {fecha_hora_corta(i.inicio)} → {fecha_hora_corta(i.fin)} ({duracion(i.duracion_s)})")
    if len(interrupciones) > maximo:
        lineas.append(f"  … y {len(interrupciones) - maximo} más")
    return "\n".join(lineas)
