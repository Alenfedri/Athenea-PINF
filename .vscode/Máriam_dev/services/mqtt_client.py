import json
import logging

import paho.mqtt.client as mqtt

from domain.ui_state import ConexionEstado


# Configuración del registro de errores
logger = logging.getLogger(__name__)


class MqttVitaBandService:

    def __init__(
        self,
        broker_host: str,
        broker_port: int = 1883,
        device_id: str = "vitaband-01"
    ):

        # Configuración del broker
        self.host = broker_host
        self.port = broker_port

        # Tópicos MQTT
        self.topic_telemetria = f"vitaband/{device_id}/telemetry"
        self.topic_status = f"vitaband/{device_id}/status"
        self.topic_control = f"vitaband/{device_id}/control"

        # Referencia al ViewModel
        self._vm = None

        # Control del ciclo de vida MQTT
        self._loop_iniciado = False
        self._cerrando = False

        # Crear cliente MQTT (API versión 2)
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2
        )

        # Registrar callbacks
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    # --------------------------------------------------
    # VINCULACIÓN CON VIEWMODEL
    # --------------------------------------------------

    def vincular_viewmodel(self, vm) -> None:
        self._vm = vm

    # --------------------------------------------------
    # CONEXIÓN MQTT
    # --------------------------------------------------

    def iniciar_conexion(self) -> None:

        if self._loop_iniciado:
            logger.warning("El bucle MQTT ya está iniciado")
            return

        self._cerrando = False

        try:

            resultado = self._client.connect_async(
            self.host,
            self.port,
            keepalive=30
            )

            if resultado != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(
                    f"No se pudo iniciar la conexión MQTT: {resultado}"
                )

            resultado = self._client.loop_start()

            if resultado != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(
                    f"No se pudo iniciar el bucle MQTT: {resultado}"
                )

            self._loop_iniciado = True

            logger.info("Iniciando conexión con el broker MQTT")

        except Exception:

            logger.exception("Error iniciando la conexión MQTT")

            self._emitir_estado(
                ConexionEstado.ERROR_COMUNICACION
            )

    # --------------------------------------------------
    # DESCONEXIÓN MQTT
    # --------------------------------------------------

    def cerrar_conexion(self) -> None:

        self._cerrando = True

        try:

            # Solicitar desconexión del broker
            self._client.disconnect()

        except Exception:

            logger.exception("Error cerrando la conexión MQTT")

        finally:

            # Detener el hilo de red
            if self._loop_iniciado:

                self._client.loop_stop()
                self._loop_iniciado = False

            logger.info("Conexión MQTT cerrada")

    # --------------------------------------------------
    # PUBLICAR COMANDOS DE CONTROL
    # --------------------------------------------------

    def publicar_control_ecg(self, comando: str) -> bool:

        # Solo se permiten los dos modos definidos
        if comando not in ("0", "1"):
            logger.warning("Comando ECG no válido: %s", comando)
            return False

        # Comprobar conexión
        if not self._client.is_connected():
            logger.warning(
                "No se puede publicar: MQTT no está conectado"
            )
            return False

        try:

            resultado = self._client.publish(
                self.topic_control,
                payload=comando,
                qos=1
            )

            if resultado.rc != mqtt.MQTT_ERR_SUCCESS:

                logger.error(
                    "Error publicando comando ECG: %s",
                    resultado.rc
                )

                return False

            logger.info("Comando ECG publicado: %s", comando)

            return True

        except Exception:

            logger.exception("Error publicando comando ECG")
            return False

    # --------------------------------------------------
    # COMUNICACIÓN SEGURA CON VIEWMODEL
    # --------------------------------------------------

    def _emitir_estado(self, estado: ConexionEstado) -> None:

        if self._vm is not None:

            # La señal se procesa mediante QueuedConnection
            self._vm.enlace_actualizado.emit(estado)

    # --------------------------------------------------
    # CALLBACK: CONEXIÓN ESTABLECIDA
    # --------------------------------------------------

    def _on_connect(
        self,
        client,
        userdata,
        flags,
        reason_code,
        properties
    ):

        if reason_code.is_failure:

            logger.error(
                "No se pudo conectar al broker MQTT: %s",
                reason_code
            )

            self._emitir_estado(
                ConexionEstado.ERROR_COMUNICACION
            )

            return

        logger.info("Conectado al broker MQTT")

        # Suscribirse a los tópicos del dispositivo
        resultado, mid = client.subscribe([
            (self.topic_telemetria, 0),
            (self.topic_status, 1)
        ])

        if resultado != mqtt.MQTT_ERR_SUCCESS:

            logger.error("Error al suscribirse a los tópicos MQTT")

            self._emitir_estado(
                ConexionEstado.ERROR_COMUNICACION
            )

            return

        logger.info(
            "Suscripciones MQTT solicitadas correctamente"
        )

        # IMPORTANTE:
        # Conectarse al broker no significa que el ESP32
        # haya terminado su calibración.
        # Esperamos el mensaje de estado del firmware.

    # --------------------------------------------------
    # CALLBACK: DESCONEXIÓN
    # --------------------------------------------------

    def _on_disconnect(
        self,
        client,
        userdata,
        disconnect_flags,
        reason_code,
        properties
    ):

        if self._cerrando:
            logger.info("Desconexión MQTT solicitada por la aplicación")
            return

        if reason_code.is_failure:

            logger.error(
                "Desconexión inesperada del broker MQTT: %s",
                reason_code
            )

            self._emitir_estado(
                ConexionEstado.ERROR_COMUNICACION
            )

    # --------------------------------------------------
    # CALLBACK: RECEPCIÓN DE MENSAJES
    # --------------------------------------------------

    def _on_message(self, client, userdata, msg):

        if self._vm is None:
            return

        try:

            # Decodificar JSON
            payload = json.loads(
                msg.payload.decode("utf-8")
            )

            # Comprobar estructura
            if not isinstance(payload, dict):
                logger.warning("Mensaje MQTT no válido: no es un objeto JSON")
                return

            # ------------------------------------------
            # MENSAJES DE ESTADO
            # ------------------------------------------

            if msg.topic == self.topic_status:

                estado = payload.get("state")

                if estado == "CALIBRATING":

                    logger.info("ESP32 en fase de calibración")

                    self._emitir_estado(
                        ConexionEstado.CALIBRANDO
                    )

                else:

                    logger.debug(
                        "Estado del ESP32 recibido: %s",
                        estado
                    )

            # ------------------------------------------
            # MENSAJES DE TELEMETRÍA
            # ------------------------------------------

            elif msg.topic == self.topic_telemetria:

                # Extraer y convertir datos
                ecg = float(payload["ecg"])
                bpm = float(payload["bpm"])
                rpm = float(payload["rpm"])
                temp_c = float(payload["temp"])

                cod_actividad = int(payload["activity"])
                cod_aviso = int(payload["alert"])

                # Enviar datos al ViewModel mediante señal Qt
                self._vm.telemetria_recibida.emit(
                    ecg,
                    bpm,
                    rpm,
                    temp_c,
                    cod_actividad,
                    cod_aviso
                )

        except (
            KeyError,
            ValueError,
            TypeError,
            UnicodeDecodeError
        ):
            logger.warning(
                "Mensaje MQTT malformado en el tópico %s",
                msg.topic
            )

        except Exception:

            logger.exception(
                "Error inesperado procesando mensaje MQTT"
            )
