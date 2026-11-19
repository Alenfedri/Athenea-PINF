import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from domain.ui_state import ConexionEstado
from services.mqtt_client import MqttVitaBandService


class FakeSignal:
    def __init__(self):
        self.emitidos = []

    def emit(self, *args):
        self.emitidos.append(args)


class FakeVm:
    def __init__(self):
        self.enlace_actualizado = FakeSignal()
        self.telemetria_recibida = FakeSignal()
        self.media_bpm_recibida = FakeSignal()


def mensaje(topic, payload):
    if not isinstance(payload, (bytes, str)):
        payload = json.dumps(payload)
    if isinstance(payload, str):
        payload = payload.encode()
    return SimpleNamespace(topic=topic, payload=payload)


class TestMqttService(unittest.TestCase):

    def setUp(self):
        self.svc = MqttVitaBandService("localhost", 1883, "vitaband-01")
        self.vm = FakeVm()
        self.svc.vincular_viewmodel(self.vm)
        self.svc._client = MagicMock()
        # paho: loop_start() devuelve MQTT_ERR_SUCCESS (0) y connect_async() None
        self.svc._client.loop_start.return_value = 0
        self.svc._client.connect_async.return_value = None

    # --- A: ciclo de vida ---

    def test_primera_conexion_no_llama_a_disconnect(self):
        self.svc.iniciar_conexion()
        self.svc._client.disconnect.assert_not_called()
        self.svc._client.loop_stop.assert_not_called()
        self.assertTrue(self.svc._loop_iniciado)

    def test_cerrar_sin_haber_conectado_no_llama_a_disconnect(self):
        self.svc.cerrar_conexion()
        self.svc._client.disconnect.assert_not_called()

    def test_cerrar_tras_conectar_si_desconecta_y_para_el_bucle(self):
        self.svc.iniciar_conexion()
        self.svc.cerrar_conexion()
        self.svc._client.disconnect.assert_called_once()
        self.svc._client.loop_stop.assert_called_once()
        self.assertFalse(self.svc._loop_iniciado)

    def test_conectar_dos_veces_reinicia_el_bucle(self):
        self.svc.iniciar_conexion()
        self.assertTrue(self.svc._loop_iniciado)

        # Simula fallo + el usuario pulsa Conectar sin Desconectar antes
        self.svc.iniciar_conexion()

        self.assertEqual(self.svc._client.loop_start.call_count, 2)
        self.assertEqual(self.svc._client.loop_stop.call_count, 1)
        self.assertEqual(self.svc._client.connect_async.call_count, 2)
        self.assertTrue(self.svc._loop_iniciado)
        self.assertFalse(self.svc._cerrando)
        self.assertEqual(self.vm.enlace_actualizado.emitidos, [])

    def test_connect_async_none_no_es_error(self):
        # paho: connect_async() devuelve None
        self.svc._client.connect_async.return_value = None
        self.svc.iniciar_conexion()
        self.assertEqual(self.vm.enlace_actualizado.emitidos, [])

    def test_fallo_al_arrancar_emite_error(self):
        self.svc._client.connect_async.side_effect = OSError("boom")
        self.svc.iniciar_conexion()
        self.assertEqual(
            self.vm.enlace_actualizado.emitidos,
            [(ConexionEstado.ERROR_COMUNICACION,)],
        )

    def test_rechazo_del_broker_emite_error_una_sola_vez(self):
        self.svc.iniciar_conexion()
        rc = SimpleNamespace(is_failure=True)
        self.svc._on_connect(self.svc._client, None, None, rc, None)
        # El disconnect posterior no debe duplicar el error
        self.svc._on_disconnect(self.svc._client, None, None, rc, None)
        self.assertEqual(
            self.vm.enlace_actualizado.emitidos,
            [(ConexionEstado.ERROR_COMUNICACION,)],
        )
        # ...y se puede volver a conectar
        self.svc.iniciar_conexion()
        self.assertFalse(self.svc._fallo_conexion)

    def test_conexion_ok_emite_conectando_y_se_suscribe(self):
        self.svc._client.subscribe.return_value = (0, 1)
        rc = SimpleNamespace(is_failure=False)
        self.svc._on_connect(self.svc._client, None, None, rc, None)
        self.assertEqual(self.vm.enlace_actualizado.emitidos, [(ConexionEstado.CONECTANDO,)])
        self.svc._client.subscribe.assert_called_once()

    def test_desconexion_inesperada_emite_error(self):
        self.svc.iniciar_conexion()
        rc = SimpleNamespace(is_failure=True)
        self.svc._on_disconnect(self.svc._client, None, None, rc, None)
        self.assertEqual(
            self.vm.enlace_actualizado.emitidos,
            [(ConexionEstado.ERROR_COMUNICACION,)],
        )

    def test_desconexion_pedida_por_app_no_emite(self):
        self.svc.cerrar_conexion()
        rc = SimpleNamespace(is_failure=True)
        self.svc._on_disconnect(self.svc._client, None, None, rc, None)
        self.assertEqual(self.vm.enlace_actualizado.emitidos, [])

    # --- C: estados de /status ---

    def test_status_calibrating_ready_offline(self):
        for estado, esperado in (
            ("CALIBRATING", ConexionEstado.CALIBRANDO),
            ("READY", ConexionEstado.CONECTADO),
            ("OFFLINE", ConexionEstado.ERROR_COMUNICACION),
        ):
            self.svc._on_message(None, None, mensaje(self.svc.topic_status, {"state": estado}))
            self.assertEqual(self.vm.enlace_actualizado.emitidos[-1], (esperado,))

    def test_status_offline_texto_plano_del_last_will(self):
        self.svc._on_message(None, None, mensaje(self.svc.topic_status, "OFFLINE"))
        self.assertEqual(
            self.vm.enlace_actualizado.emitidos,
            [(ConexionEstado.ERROR_COMUNICACION,)],
        )

    def test_status_desconocido_se_ignora(self):
        self.svc._on_message(None, None, mensaje(self.svc.topic_status, {"state": "???"}))
        self.assertEqual(self.vm.enlace_actualizado.emitidos, [])

    # --- D: telemetría y media ---

    BASE = {"ecg": 1600, "bpm": 70, "rpm": 14, "temp": 36.4, "activity": 1, "alert": 255}

    def test_telemetria_normal_no_emite_media(self):
        self.svc._on_message(None, None, mensaje(self.svc.topic_telemetria, self.BASE))
        self.assertEqual(self.vm.telemetria_recibida.emitidos, [(1600.0, 70.0, 14.0, 36.4, 1, 255)])
        self.assertEqual(self.vm.media_bpm_recibida.emitidos, [])

    def test_telemetria_con_media_emite_ambas(self):
        self.svc._on_message(
            None, None, mensaje(self.svc.topic_telemetria, {**self.BASE, "media_bpm": 71.5})
        )
        self.assertEqual(len(self.vm.telemetria_recibida.emitidos), 1)
        self.assertEqual(self.vm.media_bpm_recibida.emitidos, [(71.5,)])

    def test_telemetria_malformada_no_rompe(self):
        self.svc._on_message(None, None, mensaje(self.svc.topic_telemetria, b"no es json"))
        self.svc._on_message(None, None, mensaje(self.svc.topic_telemetria, {"ecg": 1}))
        self.svc._on_message(None, None, mensaje(self.svc.topic_telemetria, [1, 2]))
        self.assertEqual(self.vm.telemetria_recibida.emitidos, [])

    # --- Publicación de control ---

    def test_publicar_control(self):
        self.svc._client.is_connected.return_value = True
        self.svc._client.publish.return_value = SimpleNamespace(rc=0)
        self.assertTrue(self.svc.publicar_control_ecg("1"))
        self.assertFalse(self.svc.publicar_control_ecg("2"))
        self.svc._client.is_connected.return_value = False
        self.assertFalse(self.svc.publicar_control_ecg("0"))


if __name__ == "__main__":
    unittest.main()
