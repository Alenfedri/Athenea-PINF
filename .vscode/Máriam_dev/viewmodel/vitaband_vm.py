from collections import deque
from PySide6.QtCore import QObject, Signal, Slot, Qt
from domain.ui_state import ConexionEstado, VitaBandUiState
import math

class VitaBandViewModel(QObject):

    state_changed = Signal(VitaBandUiState)
    
    # Señales de entrada desde otros hilos
    telemetria_recibida = Signal(
        float, float, float, float, int, int
    )

    enlace_actualizado = Signal(ConexionEstado)

    sync_actualizado = Signal(int, bool)
    _MAPA_ACTIVIDAD = {
        0: "Baja / Reposo",
        1: "Media",
        2: "Intensa",
        255: "En transición / Sin clasificar",
    }

    _MAPA_AVISOS = {
        0: "Aviso experimental: niveles bajos en reposo",
        1: "Aviso experimental: FC elevada en reposo",
        2: "Aviso experimental: FC y FR elevadas en reposo",
        255: "Sin avisos",
    }

    def __init__(self, mqtt_service, ventana_segundos=6):
        super().__init__()
        self._contador_muestras = 0
        self._frecuencia_actualizacion = 3
        self._mqtt = mqtt_service
        self._state = VitaBandUiState.inicial()
        if ventana_segundos <= 0:
            raise ValueError("La ventana debe ser positiva")
        self._ecg_buffer = deque(
            maxlen=100 * ventana_segundos
        )
        
        # Forzar ejecución en el hilo del ViewModel
        self.telemetria_recibida.connect(
            self.on_paquete_telemetria,
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
        datos = {
            "conexionEstado": self._state.conexionEstado,
            "ecgMuestras": self._state.ecgMuestras,
            "modoEcgCrudo": self._state.modoEcgCrudo,
            "bpmTexto": self._state.bpmTexto,
            "rpmTexto": self._state.rpmTexto,
            "tempTexto": self._state.tempTexto,
            "nivelActividad": self._state.nivelActividad,
            "avisoExperimental": self._state.avisoExperimental,
            "pendientesSync": self._state.pendientesSync,
            "sincronizando": self._state.sincronizando,
        }
        datos.update(cambios)
        self._state = VitaBandUiState(**datos)
        self.state_changed.emit(self._state)

    # --- Acciones disparadas por el usuario desde la UI ---

    @Slot()
    def conectar(self) -> None:
        self._ecg_buffer.clear()
        self._emitir_nuevo_estado(
            conexionEstado=ConexionEstado.CONECTANDO,
            ecgMuestras=(),
            bpmTexto="--",
            rpmTexto="--",
        )
        self._mqtt.iniciar_conexion()

    @Slot()
    def desconectar(self) -> None:
        self._mqtt.cerrar_conexion()
        self._ecg_buffer.clear()
        self._emitir_nuevo_estado(
            conexionEstado=ConexionEstado.DESCONECTADO,
            ecgMuestras=(),
            bpmTexto="--",
            rpmTexto="--",
            tempTexto="-- °C",
            nivelActividad="Sin datos",
            avisoExperimental="Sin avisos",
        )

    @Slot(bool)
    def cambiarModoEcg(self, activo_crudo: bool) -> None:
        # "1" = crudo (A0), "0" = filtrado Butterworth + offset 1600
        comando = "1" if activo_crudo else "0"
        self._mqtt.publicar_control_ecg(comando)
        self._ecg_buffer.clear()
        self._emitir_nuevo_estado(modoEcgCrudo=activo_crudo, ecgMuestras=())

    # --- Callbacks llamados por la capa MQTT/Sync en segundo plano ---

    def on_estado_enlace_actualizado(self, nuevo_estado: ConexionEstado) -> None:
        self._emitir_nuevo_estado(conexionEstado=nuevo_estado)

    def _formatear_metrica(
        self,
        valor: float,
        unidad: str,
        decimales: int = 1
    ) -> str:

        if not math.isfinite(valor) or valor <= 0:
            return "Calculando..."

        return f"{valor:.{decimales}f} {unidad}"


    def _formatear_temperatura(self, temp_c: float) -> str:

        if not math.isfinite(temp_c):
            return "-- °C"

        return f"{temp_c:.2f} °C"

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

        # 1. Validar ECG y añadirlo al buffer
        if math.isfinite(ecg):
            self._ecg_buffer.append(ecg)

        # 2. Contabilizar muestras recibidas
        self._contador_muestras += 1

        # 3. Actualizar la interfaz cada 3 muestras
        if self._contador_muestras < self._frecuencia_actualizacion:
            return

        self._contador_muestras = 0

        # 4. Formatear métricas
        bpm_str = self._formatear_metrica(bpm, "BPM")
        rpm_str = self._formatear_metrica(rpm, "RPM")
        temp_str = self._formatear_temperatura(temp_c)

        # 5. Emitir el nuevo estado
        self._emitir_nuevo_estado(
            conexionEstado=ConexionEstado.CONECTADO,
            ecgMuestras=tuple(self._ecg_buffer),
            bpmTexto=bpm_str,
            rpmTexto=rpm_str,
            tempTexto=temp_str,
            nivelActividad=self._MAPA_ACTIVIDAD.get(
                cod_actividad,
                "En transición / Sin clasificar"
            ),
            avisoExperimental=self._MAPA_AVISOS.get(
                cod_aviso,
                "Sin avisos"
            ),
        )

    def on_estado_sync_actualizado(self, pendientes: int, sincronizando: bool) -> None:
        self._emitir_nuevo_estado(
            pendientesSync=pendientes,
            sincronizando=sincronizando,
        )
