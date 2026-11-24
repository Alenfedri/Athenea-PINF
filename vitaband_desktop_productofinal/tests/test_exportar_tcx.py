"""Exportación TCX (TrainingCenterDatabase v2)."""

import os
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET

from domain.modelos import Actividad, Medicion
from services import exportar_tcx as tcx

NS = "{http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2}"
T0 = 1_763_452_800                        # 2025-11-18T08:00:00Z


def med(i, bpm, rpm=18.0):
    return Medicion(i, f"m{i}", T0 + i * 10, bpm, rpm, 36.5, 1, "ACTIVIDAD", 1)


def actividad(dur=600):
    return Actividad(1, "a1", T0, T0 + dur, "carrera")


class TestTcx(unittest.TestCase):

    def test_estructura_y_valores(self):
        raiz = tcx.construir_tcx(actividad(), [med(0, 120.4), med(1, 150.6, 22.4), med(2, 140)])
        self.assertEqual(raiz.tag, NS + "TrainingCenterDatabase")
        act = raiz.find(f"{NS}Activities/{NS}Activity")
        self.assertEqual(act.get("Sport"), "Other")
        self.assertEqual(act.find(NS + "Id").text, "2025-11-18T08:00:00Z")
        lap = act.find(NS + "Lap")
        self.assertEqual(lap.get("StartTime"), "2025-11-18T08:00:00Z")
        self.assertEqual(lap.find(NS + "TotalTimeSeconds").text, "600.0")
        self.assertEqual(lap.find(f"{NS}MaximumHeartRateBpm/{NS}Value").text, "151")
        self.assertEqual(lap.find(f"{NS}AverageHeartRateBpm/{NS}Value").text, "137")
        puntos = lap.findall(f"{NS}Track/{NS}Trackpoint")
        self.assertEqual(len(puntos), 3)
        self.assertEqual(puntos[1].find(f"{NS}HeartRateBpm/{NS}Value").text, "151")
        self.assertEqual(puntos[1].find(NS + "Cadence").text, "22")
        self.assertEqual(puntos[1].find(NS + "Time").text, "2025-11-18T08:00:10Z")

    def test_orden_de_los_elementos_segun_el_esquema(self):
        lap = tcx.construir_tcx(actividad(), [med(0, 120)]).find(f".//{NS}Lap")
        self.assertEqual([e.tag.replace(NS, "") for e in lap],
                         ["TotalTimeSeconds", "DistanceMeters", "Calories", "AverageHeartRateBpm",
                          "MaximumHeartRateBpm", "Intensity", "TriggerMethod", "Track"])
        tp = lap.find(f".//{NS}Trackpoint")
        self.assertEqual([e.tag.replace(NS, "") for e in tp], ["Time", "HeartRateBpm", "Cadence"])

    def test_tiempos_iso_utc(self):
        raiz = tcx.construir_tcx(Actividad(1, "a", 0, 60, None), [Medicion(1, "x", 0, 100, None, None, 1, "ACTIVIDAD", 1)])
        for t in raiz.iter(NS + "Time"):
            self.assertRegex(t.text, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual(raiz.find(f".//{NS}Time").text, "1970-01-01T00:00:00Z")

    def test_omite_bpm_invalidos_y_rpm_ausentes_y_limita_cadence(self):
        ms = [med(0, 0), med(1, 130, None), med(2, 131, 400.0), med(3, 132, 0.0)]
        puntos = tcx.construir_tcx(actividad(), ms).findall(f".//{NS}Trackpoint")
        self.assertEqual(len(puntos), 3)                                   # el de BPM 0 no entra
        self.assertIsNone(puntos[0].find(NS + "Cadence"))
        self.assertEqual(puntos[1].find(NS + "Cadence").text, "254")
        self.assertEqual(puntos[2].find(NS + "Cadence").text, "0")

    def test_se_ordena_por_tiempo(self):
        puntos = tcx.construir_tcx(actividad(), [med(2, 130), med(0, 120), med(1, 125)]).findall(f".//{NS}Time")
        tiempos = [p.text for p in puntos]
        self.assertEqual(tiempos, sorted(tiempos))

    def test_actividad_sin_mediciones(self):
        raiz = tcx.construir_tcx(actividad(), [])
        self.assertEqual(raiz.findall(f".//{NS}Trackpoint"), [])
        self.assertIsNone(raiz.find(f".//{NS}AverageHeartRateBpm"))

    def test_archivo_valido(self):
        ruta = os.path.join(tempfile.mkdtemp(), "a.tcx")
        n = tcx.exportar_tcx(actividad(), [med(i, 120 + i) for i in range(50)], ruta)
        self.assertEqual(n, 50)
        with open(ruta, "rb") as f:
            cabecera = f.read(60)
        self.assertTrue(cabecera.startswith(b"<?xml version='1.0' encoding='UTF-8'?>"))
        raiz = ET.parse(ruta).getroot()
        self.assertEqual(raiz.tag, NS + "TrainingCenterDatabase")
        self.assertEqual(len(raiz.findall(f".//{NS}Trackpoint")), 50)
        self.assertIn('xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"', open(ruta, encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main()
