import os
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication

from domain.ui_state import ConexionEstado
from services.repositorio_historial import RepositorioHistorial
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QCoreApplication.instance() or QCoreApplication([])


def paquete(vm, n=3, bpm=72.0, ecg=1600.0):
    for _ in range(n):
        vm.on_paquete_telemetria(ecg, bpm, 15.0, 36.5, 0, 255)


class TestViewModel(unittest.TestCase):

    def setUp(self):
        self.mqtt = MagicMock()
        self.mqtt.publicar_control_ecg.return_value = True
        self.repo = RepositorioHistorial(":memory:")
        self.vm = VitaBandViewModel(self.mqtt, ventana_segundos=6, repositorio=self.repo)

    def tearDown(self):
        self.repo.cerrar()

    # --- B: reinicio del modo ECG ---

    def test_conectar_y_desconectar_reinician_modo_ecg(self):
        self.vm.conectar()
        self.vm.on_estado_enlace_actualizado(ConexionEstado.CONECTADO)
        self.vm.cambiarModoEcg(True)
        self.assertTrue(self.vm.state.modoEcgCrudo)

        self.vm.desconectar()
        self.assertFalse(self.vm.state.modoEcgCrudo)

        self.vm.conectar()
        self.assertFalse(self.vm.state.modoEcgCrudo)
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.CONECTANDO)

    def test_reconexion_automatica_reinicia_modo_ecg(self):
        self.vm.conectar()
        self.vm.on_estado_enlace_actualizado(ConexionEstado.CONECTADO)
        self.vm.cambiarModoEcg(True)
        self.vm.on_estado_enlace_actualizado(ConexionEstado.ERROR_COMUNICACION)
        self.vm.on_estado_enlace_actualizado(ConexionEstado.CONECTANDO)
        self.assertFalse(self.vm.state.modoEcgCrudo)

    def test_modo_ecg_no_cambia_si_la_publicacion_falla(self):
        self.vm.conectar()
        self.vm.on_estado_enlace_actualizado(ConexionEstado.CONECTADO)
        self.mqtt.publicar_control_ecg.return_value = False
        self.vm.cambiarModoEcg(True)
        self.assertFalse(self.vm.state.modoEcgCrudo)

    # --- C: OFFLINE y telemetría rezagada ---

    def test_offline_limpia_buffer_y_metricas(self):
        self.vm.conectar()
        self.vm.on_estado_enlace_actualizado(ConexionEstado.CONECTADO)
        paquete(self.vm)
        self.assertTrue(self.vm.state.ecgMuestras)
        self.assertEqual(self.vm.state.bpmTexto, "72.0 BPM")

        self.vm.on_estado_enlace_actualizado(ConexionEstado.ERROR_COMUNICACION)
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.ERROR_COMUNICACION)
        self.assertEqual(self.vm.state.ecgMuestras, ())
        self.assertEqual(self.vm.state.bpmTexto, "--")
        self.assertEqual(self.vm.state.tempTexto, "-- °C")

    def test_telemetria_rezagada_no_resucita_tras_desconectar(self):
        self.vm.conectar()
        self.vm.on_estado_enlace_actualizado(ConexionEstado.CONECTADO)
        self.vm.desconectar()
        paquete(self.vm)
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.DESCONECTADO)
        self.assertEqual(self.vm.state.ecgMuestras, ())

    def test_evento_de_enlace_rezagado_tras_desconectar_se_ignora(self):
        self.vm.conectar()
        self.vm.desconectar()
        self.vm.on_estado_enlace_actualizado(ConexionEstado.CONECTADO)
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.DESCONECTADO)

    def test_telemetria_durante_calibracion_no_pisa_el_estado(self):
        self.vm.conectar()
        self.vm.on_estado_enlace_actualizado(ConexionEstado.CALIBRANDO)
        paquete(self.vm)
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.CALIBRANDO)
        self.vm.on_estado_enlace_actualizado(ConexionEstado.CONECTADO)
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.CONECTADO)

    def test_telemetria_sin_status_pasa_de_conectando_a_conectado(self):
        self.vm.conectar()
        paquete(self.vm)
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.CONECTADO)

    # --- D: media BPM e historial ---

    def test_media_bpm_se_guarda_y_actualiza_pendientes(self):
        self.vm.conectar()
        self.vm.on_estado_enlace_actualizado(ConexionEstado.CONECTADO)
        self.vm.on_media_bpm(71.5)
        self.vm.on_media_bpm(0.0)      # inválida
        self.vm.on_media_bpm(float("nan"))
        self.assertEqual(self.repo.contar_pendientes(), 1)
        self.assertEqual(self.vm.state.pendientesSync, 1)

    def test_media_bpm_sin_enlace_no_se_guarda(self):
        self.vm.on_media_bpm(71.5)  # DESCONECTADO
        self.assertEqual(self.repo.contar_pendientes(), 0)

    def test_pendientes_iniciales_desde_el_repositorio(self):
        self.repo.guardar_media_bpm(70.0)
        vm2 = VitaBandViewModel(self.mqtt, repositorio=self.repo)
        self.assertEqual(vm2.state.pendientesSync, 1)

    # --- Señales en cola (flujo real entre hilos) ---

    def test_senales_en_cola(self):
        self.vm.conectar()
        self.vm.enlace_actualizado.emit(ConexionEstado.CONECTADO)
        for _ in range(3):
            self.vm.telemetria_recibida.emit(1600.0, 70.0, 14.0, 36.4, 1, 255)
        self.vm.media_bpm_recibida.emit(70.0)
        _app.processEvents()
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.CONECTADO)
        self.assertEqual(self.vm.state.nivelActividad, "Media")
        self.assertEqual(self.vm.state.pendientesSync, 1)

    def test_ventana_invalida(self):
        with self.assertRaises(ValueError):
            VitaBandViewModel(self.mqtt, ventana_segundos=0)


if __name__ == "__main__":
    unittest.main()
