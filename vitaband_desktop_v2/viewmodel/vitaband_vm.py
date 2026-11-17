import logging
import math
import sqlite3
import time
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable, Optional

from PySide6.QtCore import QObject, QTimer, Qt, Signal, Slot

from domain import ecg_historico, hrv
from domain.interprete_biometrico import (
    AVISO_NINGUNO,
    TEXTO_TEMP_SIN_DATOS,
    describir_actividad,
    describir_aviso,
    formatear_metrica,
    formatear_temperatura,
    validar_media_bpm,
)
from domain.modelos import ETIQUETA_PERIODICO, NIVEL_REPOSO, NIVELES_VALIDOS
from domain.ui_state import ConexionEstado, VitaBandUiState
from services.ajustes import (
    DIAS_ACTIVIDADES,
    DIAS_PERIODICO,
    INTERVALO_OBSERVACIONES_MIN,
    INTERVALO_REGISTRO_S,
    INTERVALO_SYNC_S,
)
from services.consultas_historial import ConsultasHistorial
from services.exportacion_csv import exportar_historial_csv
from services.repositorio_historial import ResultadoPurga
from services.servicio_observaciones import ResultadoObservaciones, ServicioObservaciones
from services.servicio_sync import EstadoSync, ResultadoSync

logger = logging.getLogger(__name__)

# Si pasa este tiempo sin ningún paquete de telemetría con el enlace "vivo",
# se considera que la banda pectoral se ha apagado o ha perdido el BLE.
TIMEOUT_TELEMETRIA_MS = 2500

# Estados en los que no hay enlace útil con la banda pectoral: cualquier telemetría
# que aún esté en cola de Qt es "rezagada" y debe descartarse.
_ESTADOS_SIN_ENLACE = (
    ConexionEstado.DESCONECTADO,
    ConexionEstado.ERROR_COMUNICACION,
)

_ESTADOS_CON_ENLACE = (
    ConexionEstado.CONECTADO,
    ConexionEstado.CALIBRANDO,
)

# Valores por defecto: se definen en services.ajustes y se sobrescriben desde settings.json
INTERVALO_REGISTRO_MS = INTERVALO_REGISTRO_S * 1000
INTERVALO_SYNC_MS = INTERVALO_SYNC_S * 1000
INTERVALO_OBSERVACIONES_MS = INTERVALO_OBSERVACIONES_MIN * 60_000

_MAX_ECG_PENDIENTE = 3600               # segundos de ECG en memoria antes de forzar el volcado
_TS_MAXIMO = 4_102_444_800              # 2100-01-01: "sin límite superior" en las consultas
_TEXTO_SYNC_INICIAL = "Sin sincronizar"


@dataclass(frozen=True)
class _Muestra:
    """Últimos valores numéricos recibidos (los textos de la UI no sirven para guardar)."""
    bpm: float
    rpm: float
    temp_c: float
    nivel: int


@dataclass(frozen=True)
class ResultadoArranque:
    purga: Optional[ResultadoPurga] = None
    sync: Optional[ResultadoSync] = None
    observaciones: Optional[ResultadoObservaciones] = None
    errores: tuple[str, ...] = ()


def _en_rango(v: float, minimo: float, maximo: float) -> bool:
    return math.isfinite(v) and minimo <= v <= maximo


def texto_sync(estado: EstadoSync, resultado: Optional[ResultadoSync] = None) -> str:
    """Resumen legible del estado de sincronización (RF-21)."""
    if not estado.carpeta_disponible:
        return "Carpeta de intercambio no encontrada"

    partes = []
    if resultado is not None:
        if resultado.hubo_datos_nuevos:
            partes.append(f"Nuevos: {resultado.mediciones_nuevas} mediciones, "
                          f"{resultado.actividades_nuevas} actividades")
        elif resultado.rechazados == 0:
            partes.append("Todo al día")
    if estado.errores:
        partes.append(f"{estado.errores} con error")
    if estado.pendientes:
        partes.append(f"{estado.pendientes} pendientes")
    if not partes:
        partes.append("Sin pendientes" if estado.sincronizados else "Sin archivos de intercambio")
    if estado.ultima_sync_ts:
        partes.append("última: " + datetime.fromtimestamp(estado.ultima_sync_ts).strftime("%d/%m %H:%M"))
    return " · ".join(partes)


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

    # Se emite cuando se guardan mediciones nuevas (registro periódico o importación)
    historial_actualizado = Signal()

    # Se emite cuando se crean o cambian observaciones guardadas
    observaciones_actualizadas = Signal()

    def __init__(
        self,
        mqtt_service,
        ventana_segundos=6,
        repositorio=None,
        timeout_telemetria_ms: int = TIMEOUT_TELEMETRIA_MS,
        *,
        servicio_sync=None,
        servicio_observaciones: Optional[ServicioObservaciones] = None,
        consultas: Optional[ConsultasHistorial] = None,
        intervalo_registro_ms: int = INTERVALO_REGISTRO_MS,
        intervalo_sync_ms: int = INTERVALO_SYNC_MS,
        intervalo_observaciones_ms: int = INTERVALO_OBSERVACIONES_MS,
        dias_periodico: int = DIAS_PERIODICO,
        dias_actividades: int = DIAS_ACTIVIDADES,
        reloj: Callable[[], float] = time.time,
    ):
        super().__init__()

        if ventana_segundos <= 0:
            raise ValueError("La ventana debe ser positiva")
        if intervalo_registro_ms <= 0:
            raise ValueError("El intervalo de registro debe ser positivo")
        if dias_actividades < dias_periodico:
            raise ValueError("Las actividades deben conservarse al menos tanto como el historial periódico")

        self._contador_muestras = 0
        self._frecuencia_actualizacion = 3
        self._mqtt = mqtt_service
        self._repositorio = repositorio
        self._reloj = reloj
        self._dias_periodico = dias_periodico
        self._dias_actividades = dias_actividades

        intervalo_s = intervalo_registro_ms / 1000
        self._sync = servicio_sync
        self._observaciones = servicio_observaciones or (
            ServicioObservaciones(repositorio, intervalo_s, reloj=reloj) if repositorio else None)
        self._consultas = consultas or (
            ConsultasHistorial(repositorio, intervalo_s, reloj) if repositorio else None)

        # Registro periódico (RF-12) y ECG histórico (RF-33)
        self._ultimo: Optional[_Muestra] = None
        self._media_bpm: Optional[float] = None
        self._media_edad = 0
        self._acum_ecg = ecg_historico.AcumuladorEcg()
        self._ecg_pendiente: list[ecg_historico.SegundoEcg] = []
        self._acum_hrv = hrv.AcumuladorHrv()         # RMSSD en reposo, calculado en directo

        self._timer_registro = QTimer(self)
        self._timer_registro.setInterval(intervalo_registro_ms)
        self._timer_registro.timeout.connect(self.registrar_medicion)
        self._timer_sync = QTimer(self)
        self._timer_sync.setInterval(max(1, intervalo_sync_ms))
        self._timer_sync.timeout.connect(self.sincronizar)
        self._timer_obs = QTimer(self)
        self._timer_obs.setInterval(max(1, intervalo_observaciones_ms))
        self._timer_obs.timeout.connect(self._actualizar_observaciones)
        self._usa_timer_sync = intervalo_sync_ms > 0
        self._usa_timer_obs = intervalo_observaciones_ms > 0
        self._ecg_buffer = deque(
            maxlen=100 * ventana_segundos
        )

        self._state = VitaBandUiState.inicial()

        # Watchdog de silencio de telemetría: se reinicia con cada paquete.
        self._error_por_silencio = False
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.setInterval(timeout_telemetria_ms)
        self._watchdog.timeout.connect(self._on_silencio_telemetria)

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
        self._volcar_ecg(cerrar_segundo=True)
        self._acum_hrv.reiniciar()
        self._ultimo = None
        self._media_bpm = None
        self._media_edad = 0
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
        self._watchdog.stop()
        self._error_por_silencio = False
        self._emitir_nuevo_estado(
            conexionEstado=ConexionEstado.CONECTANDO,
            **self._limpiar_datos(),
        )
        self._mqtt.iniciar_conexion()

    @Slot()
    def desconectar(self) -> None:
        self._watchdog.stop()
        self._error_por_silencio = False
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
        self._volcar_ecg(cerrar_segundo=True)   # el ECG crudo no se guarda en el histórico
        self._emitir_nuevo_estado(modoEcgCrudo=activo_crudo, ecgMuestras=())

    # --- Callbacks llamados por la capa MQTT en segundo plano ---

    @Slot(ConexionEstado)
    def on_estado_enlace_actualizado(self, nuevo_estado: ConexionEstado) -> None:
        actual = self._state.conexionEstado

        # Tras un "Desconectar" del usuario ignoramos eventos rezagados del
        # hilo de red; si no, la UI "resucitaría" sola.
        if actual == ConexionEstado.DESCONECTADO:
            return

        # Un aviso explícito de la capa MQTT/pasarela sustituye al diagnóstico
        # por silencio: ya no se recupera sola con la próxima telemetría.
        self._error_por_silencio = False

        if nuevo_estado == actual:
            return

        if nuevo_estado in (
            ConexionEstado.CONECTANDO,
            ConexionEstado.ERROR_COMUNICACION,
            ConexionEstado.DESCONECTADO,
        ):
            # Reconexión o caída (p. ej. "OFFLINE" de la pasarela): se vacía el
            # ECG y las métricas para no mostrar datos congelados como vivos.
            self._watchdog.stop()
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

        # 0. Descartar paquetes rezagados sin enlace activo. Única excepción:
        #    si el error lo provocó el watchdog por silencio y la banda pectoral
        #    vuelve a emitir, se recupera sola.
        if estado_actual in _ESTADOS_SIN_ENLACE:
            if (
                estado_actual == ConexionEstado.ERROR_COMUNICACION
                and self._error_por_silencio
            ):
                logger.info("La telemetría se ha reanudado tras un silencio")
                self._error_por_silencio = False
                # El estado debe cambiar de verdad: si solo se cambiara la variable
                # local, los paquetes siguientes volverían a descartarse.
                estado_actual = ConexionEstado.CONECTANDO
                self._emitir_nuevo_estado(conexionEstado=estado_actual)
            else:
                return

        # 0b. Hay vida: se reinicia la cuenta atrás del watchdog
        self._watchdog.start()

        # 1. Validar ECG y añadirlo al buffer (y al histórico si es señal filtrada)
        if math.isfinite(ecg):
            self._ecg_buffer.append(ecg)
            self._acumular_ecg(ecg)
            self._acumular_hrv(ecg, cod_actividad)

        self._ultimo = _Muestra(bpm, rpm, temp_c, cod_actividad)

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

    @Slot()
    def _on_silencio_telemetria(self) -> None:
        """Vence el watchdog: la banda pectoral dejó de emitir sin avisar (apagada o sin BLE)."""
        if self._state.conexionEstado not in _ESTADOS_CON_ENLACE:
            return

        logger.warning(
            "Sin telemetría durante %d ms: se marca el enlace como perdido",
            self._watchdog.interval(),
        )
        self._error_por_silencio = True
        self._emitir_nuevo_estado(
            conexionEstado=ConexionEstado.ERROR_COMUNICACION,
            **self._limpiar_datos(),
        )

    @Slot(float)
    def on_media_bpm(self, media_bpm: float) -> None:
        """Media temporal de BPM (cada ~10 s): se recuerda para el próximo registro periódico."""
        if self._state.conexionEstado in _ESTADOS_SIN_ENLACE:
            return

        if not validar_media_bpm(media_bpm):
            logger.debug("Media de BPM descartada por inválida: %s", media_bpm)
            return

        self._media_bpm = media_bpm
        self._media_edad = 0

    # --- Registro periódico (RF-12, 13) y ECG histórico (RF-33) ---

    def _bpm_a_registrar(self) -> Optional[float]:
        """La media reciente si la hay (se usa una sola vez); si no, el BPM instantáneo."""
        if self._media_bpm is not None:
            self._media_edad += 1
            if self._media_edad <= 1:
                return self._media_bpm
            self._media_bpm = None          # caducada: el firmware dejó de enviarla

        if self._ultimo is not None and validar_media_bpm(self._ultimo.bpm):
            return self._ultimo.bpm
        return None

    @Slot()
    def registrar_medicion(self) -> bool:
        """Guarda una medición periódica con los últimos valores. True si se guardó."""
        self._volcar_ecg()

        if self._repositorio is None or self._state.conexionEstado != ConexionEstado.CONECTADO:
            return False

        bpm = self._bpm_a_registrar()
        if bpm is None:
            return False

        u = self._ultimo
        try:
            self._repositorio.guardar_medicion(
                bpm,
                datetime.fromtimestamp(int(self._reloj())),
                etiqueta=ETIQUETA_PERIODICO,
                rpm=u.rpm if _en_rango(u.rpm, 0.001, 100) else None,
                temp_c=u.temp_c if _en_rango(u.temp_c, 20, 45) else None,
                nivel_actividad=u.nivel if u.nivel in NIVELES_VALIDOS else None,
            )
        except Exception:
            logger.exception("No se pudo guardar la medición periódica")
            return False

        self.historial_actualizado.emit()
        return True

    def _acumular_ecg(self, valor: float) -> None:
        if self._repositorio is None or self._state.modoEcgCrudo:
            return
        self._ecg_pendiente.extend(self._acum_ecg.agregar(int(self._reloj()), valor))
        if len(self._ecg_pendiente) >= _MAX_ECG_PENDIENTE:
            self._volcar_ecg()

    def _acumular_hrv(self, valor: float, nivel: int) -> None:
        """Alimenta el cálculo de HRV solo con ECG filtrado, conectado y en reposo."""
        if (self._repositorio is None or self._state.modoEcgCrudo
                or self._state.conexionEstado != ConexionEstado.CONECTADO or nivel != NIVEL_REPOSO):
            self._acum_hrv.reiniciar()
            return
        try:
            resultado = self._acum_hrv.agregar(self._reloj(), valor)
            if resultado is not None:
                self._repositorio.guardar_hrv(resultado)
        except Exception:
            logger.exception("No se pudo calcular o guardar la HRV")

    def _volcar_ecg(self, cerrar_segundo: bool = False) -> None:
        if cerrar_segundo:
            self._ecg_pendiente.extend(self._acum_ecg.vaciar())
        if not self._ecg_pendiente:
            return
        pendiente, self._ecg_pendiente = self._ecg_pendiente, []
        if self._repositorio is None:
            return
        try:
            self._repositorio.guardar_ecg_segundos(pendiente)
        except Exception:
            logger.exception("No se pudo guardar el ECG histórico")

    # --- Arranque, sincronización y observaciones (RF-18, 21, 29, 36, 40) ---

    @Slot()
    def arrancar(self) -> ResultadoArranque:
        """Al abrir la sesión: purga lo vencido, sincroniza, genera observaciones y
        pone en marcha los temporizadores. Cada paso falla de forma independiente."""
        errores: list[str] = []

        purga = None
        if self._repositorio is not None:
            try:
                purga = self._repositorio.purgar(
                    int(self._reloj()), self._dias_periodico, self._dias_actividades)
            except Exception as e:
                logger.exception("Error al purgar el historial")
                errores.append(f"purga: {e}")

        sync = self._sincronizar(actualizar_observaciones=False)
        if self._sync is not None and sync is None:
            errores.append("sincronización")

        observaciones = self._actualizar_observaciones()
        if self._observaciones is not None and observaciones is None:
            errores.append("observaciones")

        self._timer_registro.start()
        if self._usa_timer_sync and self._sync is not None:
            self._timer_sync.start()
        if self._usa_timer_obs and self._observaciones is not None:
            self._timer_obs.start()

        return ResultadoArranque(purga, sync, observaciones, tuple(errores))

    @Slot()
    def refrescar_estado_sync(self) -> None:
        """Actualiza los contadores de sincronización sin importar nada."""
        if self._sync is None:
            return
        try:
            self._aplicar_estado_sync(self._sync.estado())
        except Exception:
            logger.exception("No se pudo leer el estado de sincronización")

    @Slot()
    def sincronizar(self) -> Optional[ResultadoSync]:
        """Botón "Sincronizar ahora" (RF-21): importa los paquetes pendientes."""
        return self._sincronizar(actualizar_observaciones=True)

    def _sincronizar(self, actualizar_observaciones: bool) -> Optional[ResultadoSync]:
        if self._sync is None:
            return None
        try:
            resultado = self._sync.sincronizar()
            estado = self._sync.estado()
        except Exception:
            logger.exception("Error al sincronizar")
            self._emitir_nuevo_estado(syncTexto="Error al sincronizar")
            return None

        self._aplicar_estado_sync(estado, resultado)
        if resultado.hubo_datos_nuevos:
            if actualizar_observaciones:
                self._actualizar_observaciones()
            self.historial_actualizado.emit()
        return resultado

    def _aplicar_estado_sync(self, estado: EstadoSync, resultado: Optional[ResultadoSync] = None) -> None:
        campos = {
            "syncPendientes": estado.pendientes,
            "syncSincronizados": estado.sincronizados,
            "syncErrores": estado.errores,
            "syncTexto": texto_sync(estado, resultado),
        }
        if any(getattr(self._state, k) != v for k, v in campos.items()):
            self._emitir_nuevo_estado(**campos)

    @Slot()
    def _actualizar_observaciones(self) -> Optional[ResultadoObservaciones]:
        if self._observaciones is None:
            return None
        try:
            resultado = self._observaciones.actualizar_todo()
        except Exception:
            logger.exception("No se pudieron generar las observaciones")
            return None
        if resultado.total:
            self.observaciones_actualizadas.emit()
        return resultado

    # --- Consultas de historial (RF-13..16, 22, 27, 34, 45) ---

    @property
    def consultas(self) -> Optional[ConsultasHistorial]:
        return self._consultas

    def _consultar(self, funcion, defecto):
        """Ejecuta una consulta; sin historial o ante un error de BD devuelve ``defecto``.

        Los ``ValueError`` (argumentos inválidos) no se capturan: son un fallo del llamador.
        """
        if self._consultas is None:
            return defecto
        try:
            return funcion(self._consultas)
        except sqlite3.Error:
            logger.exception("No se pudo consultar el historial")
            return defecto

    def rango_disponible(self):
        return self._consultar(lambda c: c.rango_disponible(), None)

    def serie_historica(self, variable: str, desde_ts: int, hasta_ts: int, resolucion: str = "auto"):
        return self._consultar(lambda c: c.serie(variable, desde_ts, hasta_ts, resolucion), None)

    def actividades(self, desde_ts: int, hasta_ts: int) -> list:
        return self._consultar(lambda c: c.actividades(desde_ts, hasta_ts), [])

    def detalle_actividad(self, actividad_id: int):
        return self._consultar(lambda c: c.detalle_actividad(actividad_id), None)

    def ecg_historico(self, desde_ts: int, hasta_ts: int, n_bins: int = 600):
        return self._consultar(lambda c: c.ecg(desde_ts, hasta_ts, n_bins), None)

    def observaciones(self, desde_ts: int, hasta_ts: int, tipo: Optional[str] = None) -> list:
        return self._consultar(lambda c: c.observaciones(desde_ts, hasta_ts, tipo), [])

    # --- Eliminación de registros (RF-38) ---
    # La confirmación del usuario la pide la interfaz antes de llamar a estos métodos.

    def _repositorio_requerido(self):
        if self._repositorio is None:
            raise RuntimeError("No hay historial disponible")
        return self._repositorio

    def _tras_borrado(self, cambios) -> None:
        if cambios:
            self._actualizar_observaciones()        # las estadísticas de los días afectados cambian
            self.historial_actualizado.emit()

    def borrar_mediciones_periodicas(self, ids) -> int:
        """Quita mediciones del historial periódico (las de actividad se conservan)."""
        n = self._repositorio_requerido().quitar_del_periodico(ids)
        self._tras_borrado(n)
        return n

    def borrar_periodo(self, desde_ts: int, hasta_ts: int) -> int:
        """Quita todo el historial periódico de [desde_ts, hasta_ts)."""
        repo = self._repositorio_requerido()
        ids = [m.id for m in repo.mediciones_rango(desde_ts, hasta_ts, "periodico")]
        n = repo.quitar_del_periodico(ids)
        self._tras_borrado(n)
        return n

    def borrar_actividad(self, actividad_id: int) -> bool:
        """Elimina una actividad con sus datos exclusivos; lo periódico se conserva."""
        borrada = self._repositorio_requerido().borrar_actividad(actividad_id)
        self._tras_borrado(borrada)
        return borrada

    def exportar_csv(
        self,
        ruta: str,
        desde_ts: Optional[int] = None,
        hasta_ts: Optional[int] = None,
        ambito: Optional[str] = None,
    ) -> int:
        """Exporta mediciones del usuario a CSV (RF-19). Sin filtros, exporta todas.

        Devuelve cuántas filas se escribieron.
        """
        if self._repositorio is None:
            raise RuntimeError("No hay historial disponible")
        if desde_ts is None and hasta_ts is None and ambito is None:
            mediciones = self._repositorio.todas_las_mediciones()
        else:
            mediciones = self._repositorio.mediciones_rango(
                0 if desde_ts is None else desde_ts,
                _TS_MAXIMO if hasta_ts is None else hasta_ts,
                ambito,
            )
        return exportar_historial_csv(mediciones, ruta)

    # --- Utilidades ---

    @Slot()
    def cerrar(self, volcar_ecg: bool = True) -> None:
        """Libera recursos (temporizadores y base de datos) al salir o cerrar sesión.

        ``volcar_ecg=False`` descarta el ECG pendiente: se usa al eliminar la cuenta,
        para no volver a escribir datos de un usuario que ya no existe (RF-39).
        """
        self._watchdog.stop()
        for t in (self._timer_registro, self._timer_sync, self._timer_obs):
            t.stop()
        if volcar_ecg:
            self._volcar_ecg(cerrar_segundo=True)
        else:
            self._ecg_pendiente.clear()
            self._acum_ecg.vaciar()
        self._acum_hrv.reiniciar()
        if self._repositorio is not None:
            self._repositorio.cerrar()
            self._repositorio = None            # ya nada puede escribir tras el cierre
