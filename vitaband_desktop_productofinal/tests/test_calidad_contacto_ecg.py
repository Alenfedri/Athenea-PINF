"""Calidad de contacto de la banda pectoral según el ECG en vivo."""

import os
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication

from domain.calidad_contacto import CalidadContacto as C, evaluar_calidad
from domain.ui_state import ConexionEstado, VitaBandUiState
from ui.main_window import MainWindow
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])


def ecg_limpio(segundos=4, ruido=5.0, rr=82, semilla=1, base=1600.0):
    n = int(segundos * 100)
    t = np.arange(n)
    x = np.full(n, base)
    for p in range(10, n - 5, rr):
        x += 400 * np.exp(-0.5 * ((t - p) / 2.0) ** 2)        # QRS de ~20 ms
        x += 80 * np.exp(-0.5 * ((t - p - 25) / 8.0) ** 2)    # onda T
    return x + np.random.default_rng(semilla).normal(0, ruido, n)


class TestClasificacion(unittest.TestCase):

    def test_senal_limpia_es_contacto_optimo(self):
        self.assertEqual(evaluar_calidad(ecg_limpio()), C.OPTIMO)
        self.assertEqual(evaluar_calidad(ecg_limpio(segundos=6, semilla=7)), C.OPTIMO)
        self.assertEqual(C.OPTIMO.value, "Contacto óptimo")

    def test_senal_cruda_con_deriva_lenta_sigue_siendo_optima(self):
        t = np.arange(400)
        x = ecg_limpio() + 60 * np.sin(2 * np.pi * 0.2 * t / 100)      # respiración / deriva suave
        self.assertEqual(evaluar_calidad(x), C.OPTIMO)

    def test_senal_plana_o_vacia_es_sin_senal(self):
        self.assertEqual(evaluar_calidad(np.full(400, 1600.0)), C.SIN_SENAL)
        self.assertEqual(evaluar_calidad(np.full(400, 1600.0) + np.random.default_rng(1).normal(0, 1, 400)),
                         C.SIN_SENAL)
        self.assertEqual(evaluar_calidad([]), C.SIN_SENAL)
        self.assertEqual(evaluar_calidad([1600.0] * 50), C.SIN_SENAL)        # menos de 2 s
        self.assertEqual(evaluar_calidad([float("nan")] * 400), C.SIN_SENAL)
        self.assertEqual(C.SIN_SENAL.value, "Sin señal")

    def test_sin_enlace_es_sin_senal_aunque_haya_muestras(self):
        self.assertEqual(evaluar_calidad(ecg_limpio(), enlace_activo=False), C.SIN_SENAL)

    def test_ruido_intenso_de_alta_frecuencia(self):
        self.assertEqual(evaluar_calidad(ecg_limpio(ruido=60)), C.RUIDO)
        self.assertEqual(evaluar_calidad(np.random.default_rng(2).normal(1600, 300, 400)), C.RUIDO)

    def test_picos_de_artefacto(self):
        x = ecg_limpio()
        for i in (60, 150, 230, 330):
            x[i] += 1400                                              # picos de una sola muestra
        self.assertEqual(evaluar_calidad(x), C.RUIDO)

    def test_saltos_bruscos_de_linea_base(self):
        x = ecg_limpio()
        x[200:] += 700                                               # escalón: el electrodo se despega
        self.assertEqual(evaluar_calidad(x), C.RUIDO)

    def test_saturacion_y_amplitud_no_fisiologica(self):
        x = ecg_limpio()
        x[100:130] = 4095
        self.assertEqual(evaluar_calidad(x), C.RUIDO)
        y = ecg_limpio()
        y[200] += 3000
        self.assertEqual(evaluar_calidad(y), C.RUIDO)

    def test_solo_cuenta_la_ventana_reciente(self):
        sucio = np.random.default_rng(3).normal(1600, 300, 600)
        self.assertEqual(evaluar_calidad(np.concatenate([sucio, ecg_limpio(4)])), C.OPTIMO)
        self.assertEqual(evaluar_calidad(np.concatenate([ecg_limpio(4), sucio])), C.RUIDO)

    def test_ninguna_posicion_de_la_ventana_da_falsa_alarma(self):
        # La ventana se desliza latido a latido: que acabe justo tras un QRS no debe contar como ruido
        x = ecg_limpio(segundos=10, semilla=4)
        for fin in range(200, 1001):
            self.assertEqual(evaluar_calidad(x[:fin]), C.OPTIMO, fin)

    def test_un_qrs_normal_no_se_confunde_con_un_pico(self):
        # Latidos estrechos y altos (QRS de ~20 ms, 800 ADC) siguen siendo contacto óptimo
        t = np.arange(400)
        x = np.full(400, 1600.0)
        for p in range(10, 395, 70):
            x += 800 * np.exp(-0.5 * ((t - p) / 2.0) ** 2)
        x += np.random.default_rng(5).normal(0, 4, 400)
        self.assertEqual(evaluar_calidad(x), C.OPTIMO)


class TestViewModel(unittest.TestCase):

    def setUp(self):
        self.vm = VitaBandViewModel(MagicMock())
        self.estados = []
        self.vm.state_changed.connect(self.estados.append)

    def tearDown(self):
        self.vm.cerrar()

    def enviar(self, ecg_valores):
        for v in ecg_valores:
            self.vm.on_paquete_telemetria(float(v), 72.0, 16.0, 36.5, 0, 0)

    def test_el_estado_inicial_es_sin_senal(self):
        self.assertEqual(VitaBandUiState.inicial().calidadContacto, C.SIN_SENAL)

    def test_ecg_limpio_llega_a_contacto_optimo(self):
        self.vm.conectar()
        self.enviar(ecg_limpio(segundos=6))
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.CONECTADO)
        self.assertEqual(self.vm.state.calidadContacto, C.OPTIMO)

    def test_ecg_plano_con_enlace_es_sin_senal(self):
        self.vm.conectar()
        self.enviar([1600.0] * 600)
        self.assertEqual(self.vm.state.calidadContacto, C.SIN_SENAL)
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.CONECTADO)

    def test_ruido_se_detecta_y_se_recupera(self):
        self.vm.conectar()
        self.enviar(ecg_limpio(segundos=6))
        self.enviar(np.random.default_rng(2).normal(1600, 300, 600))
        self.assertEqual(self.vm.state.calidadContacto, C.RUIDO)
        self.enviar(ecg_limpio(segundos=6, semilla=9))
        self.assertEqual(self.vm.state.calidadContacto, C.OPTIMO)

    def test_al_desconectar_vuelve_a_sin_senal(self):
        self.vm.conectar()
        self.enviar(ecg_limpio(segundos=6))
        self.vm.desconectar()
        self.assertEqual(self.vm.state.calidadContacto, C.SIN_SENAL)

    def test_al_cambiar_de_modo_ecg_se_reinicia(self):
        self.vm.conectar()
        self.enviar(ecg_limpio(segundos=6))
        self.vm.cambiarModoEcg(True)
        self.assertEqual(self.vm.state.calidadContacto, C.SIN_SENAL)

    def test_no_se_reevalua_en_cada_emision(self):
        self.vm.conectar()
        self.enviar(ecg_limpio(segundos=6))
        from unittest.mock import patch
        with patch("viewmodel.vitaband_vm.evaluar_calidad", return_value=C.OPTIMO) as f:
            self.enviar(ecg_limpio(segundos=1))                      # 100 muestras = ~33 emisiones
        self.assertLessEqual(f.call_count, 4)


class TestInsignia(unittest.TestCase):

    def setUp(self):
        self.vm = VitaBandViewModel(MagicMock())
        self.ventana = MainWindow(self.vm, "Ana")

    def tearDown(self):
        self.ventana.close()
        self.vm.cerrar()

    def estado(self, calidad, conexion=ConexionEstado.CONECTADO):
        base = VitaBandUiState.inicial()
        return VitaBandUiState(**{**base.__dict__, "conexionEstado": conexion, "calidadContacto": calidad})

    def test_sin_enlace_es_gris(self):
        self.ventana.render(VitaBandUiState.inicial())
        self.assertEqual(self.ventana.lbl_calidad.text(), "Sin señal")
        self.assertIn("#e3e3e3", self.ventana.lbl_calidad.styleSheet())

    def test_optimo_verde(self):
        self.ventana.render(self.estado(C.OPTIMO))
        self.assertEqual(self.ventana.lbl_calidad.text(), "Contacto óptimo")
        self.assertIn("#d7f0dd", self.ventana.lbl_calidad.styleSheet())

    def test_ruido_ambar_con_aviso_contra_falsas_alarmas(self):
        self.ventana.render(self.estado(C.RUIDO))
        self.assertEqual(self.ventana.lbl_calidad.text(), "Señal con ruido (revisa ajuste/humedad de la banda)")
        self.assertIn("#ffe8b0", self.ventana.lbl_calidad.styleSheet())
        self.assertIn("taquicardia", self.ventana.lbl_calidad.toolTip())

    def test_sin_senal_con_enlace_es_rojo(self):
        self.ventana.render(self.estado(C.SIN_SENAL))
        self.assertIn("#f8d4d4", self.ventana.lbl_calidad.styleSheet())

    def test_no_repinta_si_no_cambia(self):
        self.ventana.render(self.estado(C.OPTIMO))
        self.ventana.lbl_calidad.setStyleSheet("")                  # si repintara, lo restauraría
        self.ventana.render(self.estado(C.OPTIMO))
        self.assertEqual(self.ventana.lbl_calidad.styleSheet(), "")

    def test_con_el_viewmodel_real(self):
        self.vm.conectar()
        for v in ecg_limpio(segundos=6):
            self.vm.on_paquete_telemetria(float(v), 72.0, 16.0, 36.5, 0, 0)
        self.assertEqual(self.ventana.lbl_calidad.text(), "Contacto óptimo")


if __name__ == "__main__":
    unittest.main()
