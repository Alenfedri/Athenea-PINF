"""Modo Entrenamiento: apertura/cierre, actualización en vivo y zonas Z1–Z5."""

import os
import unittest
from dataclasses import replace
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from domain.calidad_contacto import CalidadContacto
from domain.ui_state import ConexionEstado, VitaBandUiState
from ui.main_window import MainWindow
from ui import modo_entrenamiento as me
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])


def estado(bpm="--", rpm="--", conexion=ConexionEstado.CONECTADO, calidad=CalidadContacto.OPTIMO):
    return replace(VitaBandUiState.inicial(), bpmTexto=bpm, rpmTexto=rpm,
                   conexionEstado=conexion, calidadContacto=calidad)


class TestModoEntrenamiento(unittest.TestCase):

    def setUp(self):
        self.vm = VitaBandViewModel(MagicMock())
        self.ventana = MainWindow(self.vm, "Ana")

    def tearDown(self):
        if getattr(self.ventana, "modo_entrenamiento", None):
            self.ventana.modo_entrenamiento.close()
        self.ventana.close()
        self.vm.cerrar()

    def abrir(self):
        self.ventana.btn_entrenamiento.click()
        return self.ventana.modo_entrenamiento

    def emitir(self, **kw):
        self.vm.state_changed.emit(estado(**kw))

    # --- apertura y cierre ---
    def test_boton_abre_y_boton_salir_cierra(self):
        from PySide6.QtWidgets import QPushButton                                  # ahora vive en «Modos de Pantalla ▾»
        self.assertIn(self.ventana.btn_entrenamiento, self.ventana.menu_pantalla.findChildren(QPushButton))
        d = self.abrir()
        self.assertTrue(d.isVisible())
        self.assertTrue(d.isFullScreen())
        d.btn_salir.click()
        self.assertFalse(d.isVisible())

    def test_esc_cierra(self):
        d = self.abrir()
        QTest.keyClick(d, Qt.Key.Key_Escape)
        self.assertFalse(d.isVisible())

    def test_la_vista_normal_sigue_intacta(self):
        self.abrir()
        self.emitir(bpm="75.0 BPM", rpm="16.0 RPM")
        self.assertEqual(self.ventana.lbl_bpm.text(), "FC: 75.0 BPM")
        self.assertEqual(self.ventana.lbl_rpm.text(), "FR: 16.0 RPM")

    def test_tras_cerrar_deja_de_actualizarse(self):
        d = self.abrir()
        self.emitir(bpm="100.0 BPM")
        d.close()
        self.emitir(bpm="150.0 BPM")
        self.assertEqual(d.lbl_bpm.text(), "100")

    def test_reabrir_funciona_y_muestra_el_estado_actual(self):
        self.abrir().close()
        self.vm._state = estado(bpm="130.0 BPM")
        d = self.abrir()
        self.assertEqual(d.lbl_bpm.text(), "130")

    # --- actualización en vivo y zonas ---
    def test_bpm_rpm_y_zona_en_vivo_para_cada_zona(self):
        d = self.abrir()
        # FC máx. 190: límites 114 / 133 / 152 / 171
        casos = ((100, 0), (120, 1), (140, 2), (160, 3), (180, 4))
        for bpm, zona in casos:
            self.emitir(bpm=f"{bpm}.0 BPM", rpm="22.0 RPM")
            nombre, fondo, texto = me.ZONAS[zona]
            self.assertEqual(d.lbl_bpm.text(), str(bpm))
            self.assertEqual(d.lbl_rpm.text(), "22")
            self.assertEqual(d.lbl_zona.text(), nombre)
            self.assertEqual(d.zona_actual, zona)
            self.assertIn(fondo, d.lbl_zona.styleSheet())
            self.assertTrue(nombre.startswith(f"Z{zona + 1}"))

    def test_colores_distintos_por_zona(self):
        self.assertEqual(len({z[1] for z in me.ZONAS}), 5)
        self.assertEqual(me.ZONAS[2][0], "Z3 · Aeróbico")

    def test_fronteras_de_zona(self):
        d = self.abrir()
        for bpm, zona in ((113, 0), (114, 1), (132, 1), (133, 2), (151, 2), (152, 3), (170, 3), (171, 4)):
            self.emitir(bpm=f"{bpm} BPM")
            self.assertEqual(d.zona_actual, zona, bpm)

    def test_fc_max_personalizada(self):
        d = me.DialogoEntrenamiento(self.vm, fc_max=200)
        d.actualizar(estado(bpm="140 BPM"))                    # 70 % de 200 → Z3
        self.assertEqual(d.zona_actual, 2)

    def test_tamanos_gigantes(self):
        d = self.abrir()
        self.assertGreaterEqual(d.lbl_bpm.font().pointSize(), 100)
        self.assertGreaterEqual(d.lbl_rpm.font().pointSize(), 64)
        self.assertTrue(d.lbl_bpm.font().bold())
        self.assertIn("#0A0A0A", d.styleSheet())

    # --- sin señal ---
    def test_sin_senal_muestra_guiones_y_no_falla(self):
        d = self.abrir()
        for bpm, rpm in (("--", "--"), ("Calculando...", "--"), ("0.0 BPM", "nan RPM"), ("", ""), ("abc", "x")):
            self.emitir(bpm=bpm, rpm=rpm)
            self.assertEqual((d.lbl_bpm.text(), d.lbl_rpm.text()), ("--", "--"), bpm)
            self.assertIsNone(d.zona_actual)
            self.assertEqual(d.lbl_zona.text(), "Sin zona")

    def test_calibrando_no_muestra_valores(self):
        d = self.abrir()
        self.emitir(bpm="80.0 BPM", rpm="15.0 RPM", conexion=ConexionEstado.CALIBRANDO)
        self.assertEqual((d.lbl_bpm.text(), d.lbl_rpm.text()), ("--", "--"))

    def test_estado_de_la_banda_y_contacto(self):
        d = self.abrir()
        self.emitir(bpm="90 BPM", conexion=ConexionEstado.CONECTADO, calidad=CalidadContacto.RUIDO)
        self.assertIn("CONECTADO", d.lbl_conexion.text())
        self.assertIn(CalidadContacto.RUIDO.value, d.lbl_calidad.text())
        self.emitir(conexion=ConexionEstado.DESCONECTADO, calidad=CalidadContacto.SIN_SENAL)
        self.assertIn("DESCONECTADO", d.lbl_conexion.text())

    def test_numero(self):
        self.assertEqual(me.numero("72.6 BPM"), 72.6)
        self.assertEqual(me.numero("16,5 RPM"), 16.5)
        for malo in ("--", "", "inf BPM", "-3 BPM", None):
            self.assertIsNone(me.numero(malo))


if __name__ == "__main__":
    unittest.main()
