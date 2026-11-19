"""Alertas por umbral (Zona 5, temperatura, pérdida de contacto) en Tiempo real y Modo Entrenamiento."""

import os
import unittest
from dataclasses import replace
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from domain import alertas_umbral as au
from domain.calidad_contacto import CalidadContacto
from domain.ui_state import ConexionEstado, VitaBandUiState
from ui.main_window import MainWindow
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])


def estado(bpm="80.0 BPM", temp="36.50 °C", calidad=CalidadContacto.OPTIMO, conexion=ConexionEstado.CONECTADO):
    return replace(VitaBandUiState.inicial(), bpmTexto=bpm, tempTexto=temp, calidadContacto=calidad,
                   conexionEstado=conexion)


class Reloj:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def tipos(res):
    return [a.tipo for a in res.activas]


class TestSupervisor(unittest.TestCase):

    def setUp(self):
        self.reloj = Reloj()
        self.s = au.SupervisorAlertas(reloj=self.reloj)

    def test_zona_5_en_el_umbral_del_90_por_ciento(self):
        self.assertEqual(self.s.activas(estado(bpm="170.0 BPM")), ())                    # 89,5 %
        (a,) = self.s.activas(estado(bpm="171.0 BPM"))                                    # 90 % de 190
        self.assertEqual(a.tipo, au.ZONA5)
        self.assertIn("171", a.texto)

    def test_fc_max_propia(self):
        s = au.SupervisorAlertas(fc_max=150, reloj=self.reloj)
        self.assertEqual([a.tipo for a in s.activas(estado(bpm="135 BPM"))], [au.ZONA5])

    def test_temperatura_elevada_en_38(self):
        self.assertEqual(self.s.activas(estado(temp="37.99 °C")), ())
        (a,) = self.s.activas(estado(temp="38.00 °C"))
        self.assertEqual(a.tipo, au.TEMPERATURA)

    def test_perdida_de_contacto_solo_con_la_banda_conectada(self):
        self.assertEqual([a.tipo for a in self.s.activas(estado(calidad=CalidadContacto.SIN_SENAL))], [au.SIN_CONTACTO])
        for c in (ConexionEstado.DESCONECTADO, ConexionEstado.CONECTANDO, ConexionEstado.CALIBRANDO,
                  ConexionEstado.ERROR_COMUNICACION):
            self.assertEqual(self.s.activas(estado(calidad=CalidadContacto.SIN_SENAL, bpm="190 BPM", conexion=c)), ())

    def test_valores_sin_dato_no_disparan(self):
        for bpm, temp in (("--", "-- °C"), ("Calculando...", "nan °C"), ("", ""), ("0.0 BPM", "inf °C")):
            self.assertEqual(self.s.activas(estado(bpm=bpm, temp=temp)), (), (bpm, temp))

    def test_varias_a_la_vez(self):
        r = self.s.evaluar(estado(bpm="180 BPM", temp="38.4 °C", calidad=CalidadContacto.SIN_SENAL))
        self.assertEqual(set(tipos(r)), {au.ZONA5, au.TEMPERATURA, au.SIN_CONTACTO})
        self.assertEqual(len(r.sonar), 3)

    def test_cooldown_de_20_s_por_tipo(self):
        z5, temp = estado(bpm="180 BPM"), estado(bpm="180 BPM", temp="38.5 °C")
        self.assertEqual([a.tipo for a in self.s.evaluar(z5).sonar], [au.ZONA5])
        self.reloj.t += 19.9
        r = self.s.evaluar(z5)
        self.assertEqual(r.sonar, ())                                                     # banner sí, sonido no
        self.assertEqual(tipos(r), [au.ZONA5])
        r = self.s.evaluar(temp)                                                          # otro tipo: suena aunque Z5 esté en cooldown
        self.assertEqual([a.tipo for a in r.sonar], [au.TEMPERATURA])
        self.reloj.t += 0.1
        self.assertEqual([a.tipo for a in self.s.evaluar(z5).sonar], [au.ZONA5])          # pasaron 20 s

    def test_silenciado_no_suena_ni_consume_el_cooldown(self):
        self.s.silenciado = True
        r = self.s.evaluar(estado(bpm="180 BPM"))
        self.assertEqual((tipos(r), r.sonar), ([au.ZONA5], ()))                          # el banner sigue
        self.s.silenciado = False
        self.assertEqual([a.tipo for a in self.s.evaluar(estado(bpm="180 BPM")).sonar], [au.ZONA5])

    def test_sin_alertas_no_hay_nada(self):
        r = self.s.evaluar(estado())
        self.assertEqual((r.activas, r.sonar), ((), ()))


class TestVentana(unittest.TestCase):

    def setUp(self):
        self.vm = VitaBandViewModel(MagicMock())
        self.v = MainWindow(self.vm, "Ana")

    def tearDown(self):
        if getattr(self.v, "modo_entrenamiento", None):
            self.v.modo_entrenamiento.close()
        self.v.close()
        self.vm.cerrar()

    def emitir(self, **kw):
        self.vm.state_changed.emit(estado(**kw))

    def test_banner_y_pitido_en_tiempo_real(self):
        self.assertFalse(self.v.lbl_alerta.isVisibleTo(self.v))
        with patch("ui.main_window.QApplication.beep") as beep:
            self.emitir(bpm="180.0 BPM")
            self.assertTrue(self.v.lbl_alerta.isVisibleTo(self.v))
            self.assertIn("Zona 5", self.v.lbl_alerta.text())
            self.assertEqual(beep.call_count, 1)
            for _ in range(5):                                                            # ~33 Hz: no repite dentro del cooldown
                self.emitir(bpm="181.0 BPM")
            self.assertEqual(beep.call_count, 1)
            self.emitir(bpm="120.0 BPM")
            self.assertFalse(self.v.lbl_alerta.isVisibleTo(self.v))

    def test_pierde_contacto_y_temperatura(self):
        with patch("ui.main_window.QApplication.beep"):
            self.emitir(calidad=CalidadContacto.SIN_SENAL, temp="38.2 °C")
        self.assertIn("Temperatura elevada", self.v.lbl_alerta.text())
        self.assertIn("contacto", self.v.lbl_alerta.text())

    def test_boton_silenciar_y_activar(self):
        self.assertEqual(self.v.btn_sonido.text(), "Silenciar sonido")
        self.v.btn_sonido.click()
        self.assertTrue(self.v.alertas.silenciado)
        self.assertEqual(self.v.btn_sonido.text(), "Activar sonido")
        with patch("ui.main_window.QApplication.beep") as beep:
            self.emitir(bpm="185.0 BPM")
            beep.assert_not_called()
            self.assertTrue(self.v.lbl_alerta.isVisibleTo(self.v))                        # visual siempre
            self.v.btn_sonido.click()
            self.emitir(bpm="186.0 BPM")
            self.assertEqual(beep.call_count, 1)

    def test_modo_entrenamiento_muestra_la_alerta_y_comparte_el_silencio(self):
        with patch("ui.main_window.QApplication.beep") as beep:
            self.v.btn_entrenamiento.click()
            d = self.v.modo_entrenamiento
            self.assertFalse(d.lbl_alerta.isVisibleTo(d))
            self.emitir(bpm="182.0 BPM")
            self.assertTrue(d.lbl_alerta.isVisibleTo(d))
            self.assertIn("Zona 5", d.lbl_alerta.text())
            self.assertIn("FF5252", d.styleSheet())                                        # borde de aviso
            self.assertEqual(beep.call_count, 1)                                           # un solo pitido, no uno por vista
            d.btn_sonido.click()
            self.assertTrue(self.v.alertas.silenciado)
            self.assertEqual((d.btn_sonido.text(), self.v.btn_sonido.text()), ("Activar sonido",) * 2)
            self.emitir(bpm="120.0 BPM")
            self.assertFalse(d.lbl_alerta.isVisibleTo(d))
            self.assertNotIn("FF5252", d.styleSheet())

    def test_al_abrir_el_modo_con_una_alerta_ya_activa_se_ve(self):
        with patch("ui.main_window.QApplication.beep"):
            self.emitir(temp="38.1 °C")
            self.v.btn_entrenamiento.click()
        d = self.v.modo_entrenamiento
        self.assertTrue(d.lbl_alerta.isVisibleTo(d))
        self.assertIn("Temperatura", d.lbl_alerta.text())

    def test_desconectado_no_alerta(self):
        with patch("ui.main_window.QApplication.beep") as beep:
            self.emitir(bpm="190 BPM", conexion=ConexionEstado.DESCONECTADO, calidad=CalidadContacto.SIN_SENAL)
            beep.assert_not_called()
        self.assertFalse(self.v.lbl_alerta.isVisibleTo(self.v))


if __name__ == "__main__":
    unittest.main()
