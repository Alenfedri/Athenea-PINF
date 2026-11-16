import csv
import os
import tempfile
import unittest
from datetime import datetime

from services.exportacion_csv import CABECERA, exportar_historial_csv
from domain.modelos import Medicion


class TestExportacionCsv(unittest.TestCase):

    def exportar(self, registros):
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "x.csv")
            n = exportar_historial_csv(registros, ruta)
            with open(ruta, "rb") as f:
                crudo = f.read()
            with open(ruta, encoding="utf-8-sig", newline="") as f:
                filas = list(csv.reader(f, delimiter=";"))
        return n, crudo, filas

    def test_vacio_solo_lleva_cabecera(self):
        n, _, filas = self.exportar([])
        self.assertEqual(n, 0)
        self.assertEqual(filas, [list(CABECERA)])

    def test_filas_y_formato(self):
        ts = lambda h, m, seg: int(datetime(2026, 11, 13, h, m, seg).timestamp())
        regs = [
            Medicion(1, "a", ts(9, 0, 0), 72.46, 15.04, 36.567, 0, "PERIODICO", None),
            Medicion(2, "b", ts(9, 0, 10), 150.0, None, None, 2, "AMBOS", 7),
            Medicion(3, "c", ts(9, 0, 20), 80.0, None, None, 255, "PERIODICO", None),
            Medicion(4, "d", ts(9, 0, 30), 81.0, None, None, None, "PERIODICO", None),
        ]
        n, crudo, filas = self.exportar(regs)
        self.assertEqual(n, 4)
        self.assertTrue(crudo.startswith(b"\xef\xbb\xbf"))           # BOM para Excel
        self.assertEqual(filas[0], list(CABECERA))
        self.assertEqual(filas[1], ["2026-11-13", "09:00:00", "72,5", "15,0", "36,57", "reposo", "PERIODICO"])
        self.assertEqual(filas[2], ["2026-11-13", "09:00:10", "150,0", "", "", "intensa", "AMBOS"])
        self.assertEqual(filas[3][5], "sin clasificar")
        self.assertEqual(filas[4][5], "")

if __name__ == "__main__":
    unittest.main()
