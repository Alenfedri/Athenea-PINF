"""Exportación de una actividad a TCX (TrainingCenterDatabase v2), legible por Strava y Garmin.

Cada medición con FC válida es un Trackpoint; las RPM de la banda pectoral van en ``Cadence``
(el esquema solo admite 0–254). No hay posición GPS ni distancia: son ceros.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Sequence

from domain.modelos import Actividad, Medicion

NS = "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def construir_tcx(actividad: Actividad, mediciones: Sequence[Medicion]) -> ET.Element:
    ms = sorted((m for m in mediciones if m.bpm and m.bpm > 0), key=lambda m: m.ts)
    ET.register_namespace("", NS)
    raiz = ET.Element(f"{{{NS}}}TrainingCenterDatabase")
    acts = ET.SubElement(raiz, f"{{{NS}}}Activities")
    act = ET.SubElement(acts, f"{{{NS}}}Activity", Sport="Other")
    ET.SubElement(act, f"{{{NS}}}Id").text = _iso(actividad.inicio_ts)
    lap = ET.SubElement(act, f"{{{NS}}}Lap", StartTime=_iso(actividad.inicio_ts))

    def el(padre, nombre, texto):
        ET.SubElement(padre, f"{{{NS}}}{nombre}").text = str(texto)

    el(lap, "TotalTimeSeconds", f"{float(actividad.duracion_s):.1f}")
    el(lap, "DistanceMeters", "0.0")
    el(lap, "Calories", 0)
    if ms:
        for nombre, valor in (("AverageHeartRateBpm", round(sum(m.bpm for m in ms) / len(ms))),
                              ("MaximumHeartRateBpm", round(max(m.bpm for m in ms)))):
            el(ET.SubElement(lap, f"{{{NS}}}{nombre}"), "Value", valor)
    el(lap, "Intensity", "Active")
    el(lap, "TriggerMethod", "Manual")
    pista = ET.SubElement(lap, f"{{{NS}}}Track")
    for m in ms:
        tp = ET.SubElement(pista, f"{{{NS}}}Trackpoint")
        el(tp, "Time", _iso(m.ts))
        el(ET.SubElement(tp, f"{{{NS}}}HeartRateBpm"), "Value", int(round(m.bpm)))
        if m.rpm is not None and m.rpm >= 0:
            el(tp, "Cadence", min(254, int(round(m.rpm))))
    return raiz


def exportar_tcx(actividad: Actividad, mediciones: Sequence[Medicion], ruta: str) -> int:
    """Escribe el TCX en ``ruta`` y devuelve el número de trackpoints."""
    raiz = construir_tcx(actividad, mediciones)
    ET.indent(raiz)
    ET.ElementTree(raiz).write(ruta, encoding="UTF-8", xml_declaration=True)
    return len(raiz.findall(f".//{{{NS}}}Trackpoint"))
