import json
import logging

import paho.mqtt.client as mqtt

from domain.interprete_biometrico import (
    conexion_desde_estado,
    interpretar_estado_pasarela,
    parsear_telemetria,
)
from domain.ui_state import ConexionEstado


# Configuración del registro de errores
logger = logging.getLogger(__name__)


class MqttVitaBandService:
    """Cliente MQTT de VitaBand.

    Contrato de tópicos (ver docs/contrato_mqtt.md):
      * vitaband/{id}/telemetry  QoS 0  -> JSON con ecg, bpm, rpm, temp, activity, alert
                                           (+ media_bpm opcional cada 10 s)
      * vitaband/{id}/status     QoS 1, retain, con Last Will "OFFLINE"
                                 -> CALIBRATING | READY | OFFLINE
      * vitaband/{id}/control    QoS 1 -> "0" (filtrada) | "1" (cruda)
    """

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
        # True cuando el broker rechaza la conexión: evita notificar dos veces
        # el error (on_connect + on_disconnect).
        self._fallo_conexion = False

        # Crear cliente MQTT (API versión 2)
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2
        )

        # Reintentos automáticos de reconexión (1 s .. 10 s)
        self._client.reconnect_delay_set(min_delay=1, max_delay=10)

        # Registrar callbacks
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_connect_fail = self._on_connect_fail
        self._client.on_message = self._on_message

    # --------------------------------------------------
    # VINCULACIÓN CON VIEWMODEL
    # --------------------------------------------------

    def vincular_viewmodel(self, vm) -> None:
        self._vm = vm

    # --------------------------------------------------
    # CICLO DE VIDA MQTT
    # --------------------------------------------------

    def _detener_bucle(self) -> None:
        """Deja el cliente en reposo: sin sesión y sin hilo de red.

        Debe llamarse SIEMPRE desde un hilo distinto al de red de paho
        (hilo de la UI), nunca desde un callback.
        """
        self._cerrando = True

        # Solo hay algo que cerrar si el bucle llegó a iniciarse: en la primera
        # conexión no se llama a disconnect() sobre un cliente que nunca conectó.
        if not self._loop_iniciado:
            return

        try:
            self._client.disconnect()
        except Exception:
            logger.exception("Error solicitando la desconexión MQTT")

        try:
            self._client.loop_stop()
        except Exception:
            logger.exception("Error deteniendo el bucle MQTT")
        finally:
            self._loop_iniciado = False

    def iniciar_conexion(self) -> None:

        # Reinicio limpio: si quedó un bucle anterior (por un fallo de red o un
        # rechazo del broker) se elimina antes de abrir uno nuevo. Así
        # "Conectar" funciona siempre, sin exigir pulsar "Desconectar" antes.
        if self._loop_iniciado:
            logger.info("Bucle MQTT previo detectado: reiniciando")
        self._detener_bucle()

        self._cerrando = False
        self._fallo_conexion = False

        try:

            # connect_async() no devuelve código (devuelve None); los fallos
            # de red se notifican de forma asíncrona en on_connect/on_disconnect.
            self._client.connect_async(
                self.host,
                self.port,
                keepalive=30
            )

            resultado = self._client.loop_start()

            if resultado is not None and resultado != mqtt.MQTT_ERR_SUCCESS:
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

    def cerrar_conexion(self) -> None:

        try:
            self._detener_bucle()
        finally:
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

            self._abortar_por_error()
            return

        logger.info("Conectado al broker MQTT")

        # Cada (re)conexión empieza en CONECTANDO: el estado real lo dicta el
        # mensaje retenido de /status que el broker entrega al suscribirnos.
        # Esto además provoca el reinicio del modo ECG en el ViewModel, igual
        # que hace el firmware en cada nueva conexión.
        self._emitir_estado(ConexionEstado.CONECTANDO)

        # Suscribirse a los tópicos del dispositivo (se repite en cada
        # reconexión porque la sesión es clean_start por defecto)
        resultado, mid = client.subscribe([
            (self.topic_telemetria, 0),
            (self.topic_status, 1)
        ])

        if resultado != mqtt.MQTT_ERR_SUCCESS:

            logger.error("Error al suscribirse a los tópicos MQTT")

            self._abortar_por_error()
            return

        logger.info(
            "Suscripciones MQTT solicitadas correctamente"
        )

        # IMPORTANTE:
        # Conectarse al broker no significa que el ESP32 / la pasarela estén
        # listos. Esperamos el mensaje de estado (CALIBRATING / READY / OFFLINE).

    def _abortar_por_error(self) -> None:
        """Error irrecuperable de conexión/suscripción (se llama desde el hilo de red).

        Notifica la UI y pide a paho que pare de reintentar. La limpieza del
        hilo (loop_stop) no puede hacerse aquí; la hará iniciar_conexion() en el
        siguiente intento del usuario, por eso ese método siempre reinicia.
        """
        self._fallo_conexion = True
        self._emitir_estado(ConexionEstado.ERROR_COMUNICACION)

        try:
            self._client.disconnect()
        except Exception:
            logger.exception("Error cancelando la conexión fallida")

    # --------------------------------------------------
    # CALLBACK: FALLO DE CONEXIÓN (broker apagado / red caída)
    # --------------------------------------------------

    def _on_connect_fail(self, client, userdata):

        # paho llama a este callback (y no a on_disconnect) cuando ni siquiera
        # se llega a establecer el socket. Seguirá reintentando solo.
        if self._cerrando:
            return

        logger.error(
            "No se pudo alcanzar el broker MQTT en %s:%s", self.host, self.port
        )

        self._emitir_estado(ConexionEstado.ERROR_COMUNICACION)

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

        if self._fallo_conexion:
            # Ya se notificó el error en on_connect
            return

        if reason_code.is_failure:

            # paho reintentará solo (reconnect_delay_set). Mientras tanto la UI
            # muestra error y sin datos; al reconectar, on_connect emite
            # CONECTANDO y el estado retenido de /status la devuelve a su sitio.
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

            # ------------------------------------------
            # MENSAJES DE ESTADO
            # ------------------------------------------

            if msg.topic == self.topic_status:

                self._procesar_estado(msg.payload)

            # ------------------------------------------
            # MENSAJES DE TELEMETRÍA
            # ------------------------------------------

            elif msg.topic == self.topic_telemetria:

                self._procesar_telemetria(msg.payload)

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

    def _procesar_estado(self, payload: bytes) -> None:

        estado = interpretar_estado_pasarela(payload)

        if estado is None:
            logger.warning("Estado de la pasarela no reconocido: %r", payload)
            return

        logger.info("Estado de la pasarela: %s", estado.value)

        self._emitir_estado(conexion_desde_estado(estado))

    def _procesar_telemetria(self, payload: bytes) -> None:

        datos = json.loads(payload.decode("utf-8"))

        if not isinstance(datos, dict):
            logger.warning("Mensaje MQTT no válido: no es un objeto JSON")
            return

        paquete = parsear_telemetria(datos)

        # Enviar datos al ViewModel mediante señal Qt
        self._vm.telemetria_recibida.emit(
            paquete.ecg,
            paquete.bpm,
            paquete.rpm,
            paquete.temp_c,
            paquete.cod_actividad,
            paquete.cod_aviso
        )

        # Media temporal de BPM (llega cada ~10 s) para el historial
        if paquete.media_bpm is not None:
            self._vm.media_bpm_recibida.emit(paquete.media_bpm)
