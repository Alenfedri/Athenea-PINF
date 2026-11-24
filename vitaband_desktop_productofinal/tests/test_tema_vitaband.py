"""Identidad visual Verde Pino & Obsidiana: paleta, hoja QSS y aplicación global."""

import os
import re
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pyqtgraph as pg
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from ui import tema_vitaband as t

_app = QApplication.instance() or QApplication([])
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
NOMBRES = ("FONDO_OBSIDIANA", "TARJETA_PINO", "TARJETA_ELEVADA", "BORDE_BOSQUE", "VERDE_PINO", "ESMERALDA_ECG",
           "ESMERALDA_BRILLO", "ORO_CHAMPAN", "CORAL_PULSO", "TEXTO_MARFIL", "TEXTO_SALVIA")


class TestPaleta(unittest.TestCase):

    def test_constantes_hexadecimales_validas(self):
        for n in NOMBRES:
            self.assertRegex(getattr(t, n), HEX, n)
            self.assertTrue(QColor(getattr(t, n)).isValid(), n)
        for z in ("Z1", "Z2", "Z3", "Z4", "Z5"):
            self.assertRegex(t.COLORES_ZONAS[z], HEX, z)
        self.assertEqual(len(t.COLORES_ZONAS), 5)

    def test_valores_oficiales(self):
        self.assertEqual(t.FONDO_OBSIDIANA, "#090E0C")
        self.assertEqual(t.ESMERALDA_ECG, "#10B981")
        self.assertEqual(t.ORO_CHAMPAN, "#D4AF37")
        self.assertEqual(t.COLORES_ZONAS["Z2"], "#10B981")
        self.assertEqual(t.COLORES_ZONAS["Z5"], "#F43F5E")


class TestQss(unittest.TestCase):

    def test_existe_y_no_esta_vacio(self):
        ruta = Path(__file__).resolve().parents[1] / "styles" / "vitaband_pino.qss"
        self.assertTrue(ruta.exists())
        self.assertGreater(ruta.stat().st_size, 500)
        self.assertEqual(ruta, t.RUTA_QSS)

    def test_usa_la_paleta_y_las_llaves_estan_equilibradas(self):
        q = t.cargar_qss()
        for c in (t.FONDO_OBSIDIANA, t.TARJETA_PINO, t.ESMERALDA_ECG, t.VERDE_PINO, t.TEXTO_MARFIL):
            self.assertIn(c, q)
        self.assertEqual(q.count("{"), q.count("}"))
        for w in ("QPushButton", "QTabBar", "QTableWidget", "QComboBox", "QProgressBar", "QScrollBar"):
            self.assertIn(w, q)


class TestAplicacion(unittest.TestCase):

    def tearDown(self):
        _app.setStyleSheet("")

    def test_aplicar_tema_global_carga_sin_errores(self):
        self.assertTrue(t.aplicar_tema_global(_app))
        self.assertIn("#090E0C", _app.styleSheet())

    def test_configura_pyqtgraph(self):
        t.aplicar_tema_global(_app)
        self.assertEqual(QColor(pg.getConfigOption("background")), QColor(t.TARJETA_PINO))
        self.assertEqual(QColor(pg.getConfigOption("foreground")), QColor(t.TEXTO_SALVIA))
        self.assertTrue(pg.getConfigOption("antialias"))

    def test_sin_qss_no_falla(self):
        from unittest.mock import patch
        with patch.object(t, "RUTA_QSS", Path("/no/existe.qss")), patch("ui.tema_vitaband.cargar_qss",
                                                                          side_effect=FileNotFoundError):
            self.assertFalse(t.aplicar_tema_global(_app))

    def test_funciona_desde_otro_directorio(self):
        cwd = os.getcwd()
        try:
            os.chdir("/")
            self.assertTrue(t.aplicar_tema_global(_app))
        finally:
            os.chdir(cwd)

    def test_ventana_principal_con_el_tema(self):
        from unittest.mock import MagicMock
        from ui.main_window import MainWindow
        from viewmodel.vitaband_vm import VitaBandViewModel
        t.aplicar_tema_global(_app)
        vm = VitaBandViewModel(MagicMock())
        v = MainWindow(vm, "Ana")
        v.show()
        self.assertEqual(v.plot_widget.backgroundBrush().color(), QColor(t.TARJETA_PINO))
        self.assertEqual(v.curva_ecg.opts["pen"].color(), QColor(t.ESMERALDA_ECG))
        v.grab()
        v.close()
        vm.cerrar()

    def test_las_graficas_usan_la_paleta(self):
        from ui import grafica_cruce, grafica_ecg, grafica_serie, panel_comparador
        self.assertEqual(grafica_ecg.COLOR, t.ESMERALDA_ECG)
        self.assertEqual(grafica_serie.COLOR, t.ESMERALDA_ECG)
        self.assertEqual(grafica_cruce.COLOR_RPM, t.ESMERALDA_BRILLO)
        self.assertEqual(grafica_cruce.COLOR_UMBRAL, t.ORO_CHAMPAN)
        self.assertEqual(panel_comparador.COLOR_AHORA, t.ESMERALDA_ECG)
        self.assertEqual(t.ALFA_REJILLA, 0.15)

    def test_el_pdf_conserva_el_fondo_blanco(self):
        from services import exportar_pdf as pdf
        self.assertEqual(pdf.COLOR_ECG, QColor(t.ESMERALDA_ECG))
        self.assertEqual(pdf.TINTA, QColor("#111111"))


if __name__ == "__main__":
    unittest.main()
