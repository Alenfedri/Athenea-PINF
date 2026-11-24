"""Divulgación progresiva: los widgets existentes se reubican en menús / sub-pestañas / paneles colapsables."""
import os
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from ui.main_window import MainWindow
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])


class TestDivulgacion(unittest.TestCase):
    def setUp(self):
        self.v = MainWindow(VitaBandViewModel(MagicMock()), "Ana", "ana@correo.es")
        self.v.show()

    def tearDown(self):
        self.v.close()

    def test_cabecera_minimalista(self):
        self.assertEqual(self.v.lbl_titulo.text(), "VitaBand · Banda Pectoral ECG")
        self.assertTrue(self.v.lbl_punto_conexion.isVisibleTo(self.v))
        textos = [a.text() for a in self.v.menu_cuenta.actions()]
        for t in ("Perfil fisiológico", "Exportar informe PDF", "Exportar Backup (.zip)", "Cerrar sesión",
                  "Anonimizar datos personales"):
            self.assertIn(t, textos)
        self.assertFalse(self.v.btn_cerrar_sesion.isVisibleTo(self.v))

    def test_acciones_del_menu_disparan_los_botones_originales(self):
        pulsado = []
        self.v.btn_cerrar_sesion.clicked.connect(lambda: pulsado.append(1))
        next(a for a in self.v.menu_cuenta.actions() if a.text() == "Cerrar sesión").trigger()
        self.assertEqual(pulsado, [1])
        acc = self.v.accion_anonimizar
        acc.setChecked(True)
        self.assertTrue(self.v.chk_anonimizar.isChecked())
        self.v.chk_anonimizar.setChecked(False)
        self.assertFalse(acc.isChecked())

    def test_cockpit_tarjetas_y_menus(self):
        for t in (self.v.tarjeta_bpm, self.v.tarjeta_rpm, self.v.tarjeta_zona):
            self.assertEqual(t.property("card"), "true")
            self.assertEqual(t.layout().contentsMargins().left(), 16)
        self.assertIs(self.v.lbl_ratio.parent(), self.v.tarjeta_rpm)
        self.assertEqual(self.v.btn_menu_entrenamiento.text(), "Entrenamiento ▾")
        self.assertEqual(self.v.btn_menu_pantalla.text(), "Modos de Pantalla ▾")
        en = self.v.menu_entrenamiento.findChildren(QPushButton)
        pa = self.v.menu_pantalla.findChildren(QPushButton)
        for b in (self.v.btn_coherencia, self.v.btn_ortostatico):
            self.assertIn(b, en)
        for b in (self.v.btn_pip, self.v.btn_entrenamiento, self.v.btn_sonido):
            self.assertIn(b, pa)
        for b in (self.v.btn_conectar, self.v.btn_desconectar, self.v.btn_lap):
            self.assertTrue(b.isVisibleTo(self.v))

    def test_zona_actual_en_la_tarjeta(self):
        self.assertEqual(self.v.lbl_zona_actual.text(), "Zona: —")

    def test_acoplamiento_colapsado_por_defecto(self):
        self.assertFalse(self.v.panel_acoplamiento.isVisibleTo(self.v))
        self.v.btn_acoplamiento.click()
        self.assertTrue(self.v.panel_acoplamiento.isVisibleTo(self.v))
        self.assertIn("Ocultar", self.v.btn_acoplamiento.text())
        self.v.btn_acoplamiento.click()
        self.assertFalse(self.v.panel_acoplamiento.isVisibleTo(self.v))
        self.assertEqual(self.v.btn_acoplamiento.text(), "Ver Acoplamiento Pulso-Respiración ▾")

    def test_actividades_subpestanas_y_menu_exportar(self):
        va = self.v.vista_actividades
        textos = [va.pestanas_grafica.tabText(i) for i in range(va.pestanas_grafica.count())]
        self.assertEqual(textos, ["Resumen y Curvas", "Laboratorio ECG (Forense y Poincaré)"])
        self.assertEqual(va.btn_exportar.text(), "Exportar y Compartir ▾")
        acciones = [a.text() for a in va.menu_exportar.actions() if a.text()]
        for t in ("Informe PDF clínico", "Historial CSV", "Anonimizar datos personales (SHA-256)"):
            self.assertIn(t, acciones)
        self.assertIn(va.btn_tcx, va.menu_exportar.findChildren(QPushButton))
        self.assertIn(va.btn_tarjeta, va.menu_exportar.findChildren(QPushButton))
        self.assertIn("D4AF37", va.lbl_prs.styleSheet())


if __name__ == "__main__":
    unittest.main()
