import logging
import math
from collections import deque
from dataclasses import replace

from PySide6.QtCore import QObject, Qt, Signal, Slot

from domain.interprete_biometrico import (
    AVISO_NINGUNO,
    TEXTO_TEMP_SIN_DATOS,
    describir_actividad,
    describir_aviso,
    formatear_metrica,
    formatear_temperatura,
    validar_media_bpm,
)
from domain.ui_state import ConexionEstado, VitaBandUiState

logger = logging.getLogger(__name__)

# Estados en los que no hay enlace útil con la pulsera: cualquier telemetría
# que aún esté en cola de Qt es "rezagada" y debe descartarse.
_ESTADOS_SIN_ENLACE = (
    ConexionEstado.DESCONECTADO,
    ConexionEstado.ERROR_COMUNICACION,
)


class VitaBandViewModel(QObject):
    """Estado de presentación de VitaBand.

    Las reglas de negocio (mapeo de códigos, formateo, validación) viven en
    ``domain.interprete_biometrico``; aquí solo se orquesta el estado de la UI.
    """

    state_changed = Signal(VitaBandUiState)

    # Señales de entrada desde otros hilos
    telemetria_recibida = Signal(
        float, float, float, float, int, int
    )

    media_bpm_recibida = Signal(float)

    enlace_actualizado = Signal(ConexionEstado)

    sync_actualizado = Signal(int, bool)

    def __init__(self, mqtt_service, ventana_segundos=6, repositorio=None):
        super().__init__()

        if ventana_segundos <= 0:
            raise ValueError("La ventana debe ser positiva")

        self._contador_muestras = 0
        self._frecuencia_actualizacion = 3
        self._mqtt = mqtt_service
        self._repositorio = repositorio
        self._ecg_buffer = deque(
            maxlen=100 * ventana_segundos
        )

        self._state = VitaBandUiState.inicial()
        if self._repositorio is not None:
            self._state = replace(
                self._state,
                pendientesSync=self._contar_pendientes_seguro(),
            )

        # Forzar ejecución en el hilo del ViewModel
        self.telemetria_recibida.connect(
            self.on_paquete_telemetria,
            Qt.ConnectionType.QueuedConnection
        )

        self.media_bpm_recibida.connect(
            self.on_media_bpm,
            Qt.ConnectionType.QueuedConnection
        )

        self.enlace_actualizado.connect(
            self.on_estado_enlace_actualizado,
            Qt.ConnectionType.QueuedConnection
        )

        self.sync_actualizado.connect(
            self.on_estado_sync_actualizado,
            Qt.ConnectionType.QueuedConnection
        )

    @property
    def state(self) -> VitaBandUiState:
        return self._state

    def _emitir_nuevo_estado(self, **cambios) -> None:
        self._state = replace(self._state, **cambios)
        self.state_changed.emit(self._state)

    def _limpiar_datos(self) -> dict:
        """Vacía buffers y devuelve los campos de estado "sin datos".

        Incluye ``modoEcgCrudo=False``: el firmware reinicia el modo ECG a
        filtrado (0) en cada nueva conexión, así que la UI debe hacer lo mismo.
        """
        self._ecg_buffer.clear()
        self._contador_muestras = 0
        return {
            "ecgMuestras": (),
            "modoEcgCrudo": False,
            "bpmTexto": "--",
            "rpmTexto": "--",
            "tempTexto": TEXTO_TEMP_SIN_DATOS,
            "nivelActividad": "Sin datos",
            "avisoExperimental": AVISO_NINGUNO,
        }

    # --- Acciones disparadas por el usuario desde la UI ---

    @Slot()
    def conectar(self) -> None:
        self._emitir_nuevo_estado(
            conexionEstado=ConexionEstado.CONECTANDO,
            **self._limpiar_datos(),
        )
        self._mqtt.iniciar_conexion()

    @Slot()
    def desconectar(self) -> None:
        self._mqtt.cerrar_conexion()
        self._emitir_nuevo_estado(
            conexionEstado=ConexionEstado.DESCONECTADO,
            **self._limpiar_datos(),
        )

    @Slot(bool)
    def cambiarModoEcg(self, activo_crudo: bool) -> None:
        # "1" = crudo (A0), "0" = filtrado Butterworth + offset 1600
        comando = "1" if activo_crudo else "0"

        if not self._mqtt.publicar_control_ecg(comando):
            # El dispositivo no recibió el comando: no cambiamos el modo y
            # re-emitimos el estado para que el checkbox vuelva a su valor real.
            logger.warning("Modo ECG no cambiado: el comando no se pudo publicar")
            self._emitir_nuevo_estado()
            return

        self._ecg_buffer.clear()
        self._emitir_nuevo_estado(modoEcgCrudo=activo_crudo, ecgMuestras=())

    # --- Callbacks llamados por la capa MQTT/Sync en segundo plano ---

    @Slot(ConexionEstado)
    def on_estado_enlace_actualizado(self, nuevo_estado: ConexionEstado) -> None:
        actual = self._state.conexionEstado

        # Tras un "Desconectar" del usuario ignoramos eventos rezagados del
        # hilo de red; si no, la UI "resucitaría" sola.
        if actual == ConexionEstado.DESCONECTADO:
            return

        if nuevo_estado == actual:
            return

        if nuevo_estado in (
            ConexionEstado.CONECTANDO,
            ConexionEstado.ERROR_COMUNICACION,
            ConexionEstado.DESCONECTADO,
        ):
            # Reconexión o caída (p. ej. "OFFLINE" de la pasarela): se vacía el
            # ECG y las métricas para no mostrar datos congelados como vivos.
            self._emitir_nuevo_estado(
                conexionEstado=nuevo_estado,
                **self._limpiar_datos(),
            )
            return

        if nuevo_estado == ConexionEstado.CALIBRANDO:
            self._emitir_nuevo_estado(
                conexionEstado=nuevo_estado,
                bpmTexto="--",
                rpmTexto="--",
            )
            return

        self._emitir_nuevo_estado(conexionEstado=nuevo_estado)

    @Slot(float, float, float, float, int, int)
    def on_paquete_telemetria(
        self,
        ecg: float,
        bpm: float,
        rpm: float,
        temp_c: float,
        cod_actividad: int,
        cod_aviso: int,
    ) -> None:

        estado_actual = self._state.conexionEstado

        # 0. Descartar paquetes rezagados sin enlace activo
        if estado_actual in _ESTADOS_SIN_ENLACE:
            return

        # 1. Validar ECG y añadirlo al buffer
        if math.isfinite(ecg):
            self._ecg_buffer.append(ecg)

        # 2. Contabilizar muestras recibidas
        self._contador_muestras += 1

        # 3. Actualizar la interfaz cada 3 muestras
        if self._contador_muestras < self._frecuencia_actualizacion:
            return

        self._contador_muestras = 0

        # 4. Durante la calibración se mantiene el estado CALIBRANDO; solo el
        #    mensaje READY del firmware (o, sin él, la primera telemetría tras
        #    CONECTANDO) lleva a CONECTADO.
        if estado_actual == ConexionEstado.CALIBRANDO:
            nuevo_estado = ConexionEstado.CALIBRANDO
        else:
            nuevo_estado = ConexionEstado.CONECTADO

        # 5. Emitir el nuevo estado
        self._emitir_nuevo_estado(
            conexionEstado=nuevo_estado,
            ecgMuestras=tuple(self._ecg_buffer),
            bpmTexto=formatear_metrica(bpm, "BPM"),
            rpmTexto=formatear_metrica(rpm, "RPM"),
            tempTexto=formatear_temperatura(temp_c),
            nivelActividad=describir_actividad(cod_actividad),
            avisoExperimental=describir_aviso(cod_aviso),
        )

    @Slot(float)
    def on_media_bpm(self, media_bpm: float) -> None:
        """Media temporal de BPM (cada 10 s): se guarda en el historial local."""
        if self._repositorio is None:
            return

        if self._state.conexionEstado in _ESTADOS_SIN_ENLACE:
            return

        if not validar_media_bpm(media_bpm):
            logger.debug("Media de BPM descartada por inválida: %s", media_bpm)
            return

        try:
            self._repositorio.guardar_media_bpm(media_bpm)
        except Exception:
            logger.exception("No se pudo guardar la media de BPM")
            return

        self._emitir_nuevo_estado(
            pendientesSync=self._contar_pendientes_seguro()
        )

    @Slot(int, bool)
    def on_estado_sync_actualizado(self, pendientes: int, sincronizando: bool) -> None:
        self._emitir_nuevo_estado(
            pendientesSync=pendientes,
            sincronizando=sincronizando,
        )

    # --- Utilidades ---

    def _contar_pendientes_seguro(self) -> int:
        try:
            return self._repositorio.contar_pendientes()
        except Exception:
            logger.exception("No se pudo leer el número de registros pendientes")
            return self._state.pendientesSync

    @Slot()
    def cerrar(self) -> None:
        """Libera recursos (base de datos) al salir de la aplicación."""
        if self._repositorio is not None:
            self._repositorio.cerrar()
