"""Exportación del historial a CSV, pensada para abrirse con Excel en español (RF-19).

Formato: UTF-8 con BOM (para que Excel respete las tildes), separador ``;`` y
coma decimal. Si se va a leer con pandas: ``pd.read_csv(f, sep=";", decimal=",")``.
Las celdas sin dato (p. ej. sin temperatura) se dejan vacías.
"""

from __future__ import annotations

import csv
from typing import Iterable, Optional

from domain.modelos import (
    NIVEL_INTENSA,
    NIVEL_MEDIA,
    NIVEL_REPOSO,
    NIVEL_SIN_CLASIFICAR,
    Medicion,
)

CABECERA = ("fecha", "hora", "bpm", "rpm", "temp_c", "nivel_actividad", "etiqueta")

_NIVELES = {
    NIVEL_REPOSO: "reposo",
    NIVEL_MEDIA: "media",
    NIVEL_INTENSA: "intensa",
    NIVEL_SIN_CLASIFICAR: "sin clasificar",
}


def _num(v: Optional[float], decimales: int) -> str:
    return "" if v is None else f"{v:.{decimales}f}".replace(".", ",")


def exportar_historial_csv(registros: Iterable[Medicion], ruta: str) -> int:
    """Escribe las mediciones en ``ruta`` y devuelve cuántas se exportaron."""
    n = 0
    with open(ruta, "w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.writer(archivo, delimiter=";")
        escritor.writerow(CABECERA)
        for m in registros:
            instante = m.instante
            escritor.writerow((
                instante.strftime("%Y-%m-%d"),
                instante.strftime("%H:%M:%S"),
                _num(m.bpm, 1),
                _num(m.rpm, 1),
                _num(m.temp_c, 2),
                "" if m.nivel_actividad is None else _NIVELES.get(m.nivel_actividad, ""),
                m.etiqueta,
            ))
            n += 1
    return n
