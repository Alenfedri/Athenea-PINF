import logging
import math
import sqlite3
import time
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable, Optional

from PySide6.QtCore import QObject, QTimer, Qt, Signal, Slot

from domain import comparador_sesiones, ecg_historico, hrv, marcadores_contexto, zonas_actividad
from domain.calidad_contacto import CalidadContacto, evaluar_calidad
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
from services import datos_ejemplo
from services import backup_db, constancia, exportar_tcx as _tcx, metricas_avanzadas as metricas
from services import calculos_fisiologicos as calc
from services import funciones_en_vivo as fv, tarjeta_resumen
from services import anonimizar as anonimizar_mod, coherencia, disciplinas as disc, ia_local_sesion, poincare, vo2max
from services import inteligencia_biometrica as ib
from services.estres_escritorio import DetectorEstres
from services.ratio_pulso_resp import MonitorRatio
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
_CADA_N_EMISIONES_CALIDAD = 10          # reevaluar la calidad de contacto cada 10 emisiones (~0,3 s)


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
    vuelta_marcada = Signal(int)
    latido = Signal()                           # un pico R detectado en el ECG en directo
    zona_objetivo_cambiada = Signal(object)     # índice 0..4 o None (piloto automático)
    susurro = Signal(str)                       # consejo del Susurrador en vivo (fuera de la zona objetivo > 4 min)
    hrr_calculado = Signal(object)              # Hrr medido tras «Finalizar sesión»
    sesion_importada = Signal()                 # una sincronización ha traído sesiones nuevas (auto-análisis del Coach)
    rmssd_calculado = Signal(float)             # RMSSD (ms) de cada ventana HRV completada
    aviso_estres = Signal(str)                  # Modo Escritorio: texto de la pausa activa sugerida

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
        self._evaluaciones_calidad = 0
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
        self.susurrador = ib.Susurrador()
        self._bpm_hist: deque = deque(maxlen=1500)   # (ts, bpm) recientes para medir la recuperación (HRR)
        self._hrr_pend: Optional[dict] = None
        self._zona_obj: tuple = (None, None, 0.0)    # (fecha, zona objetivo de hoy, ts consulta) en caché
        self.sesion_directo = calc.SesionDirecto()   # tiempo efectivo y auto-pausa por retirada de banda
        self._captura_ecg: Optional[list] = None      # test ortostático: (t, valor)
        self._acum_hrv = hrv.AcumuladorHrv()         # RMSSD en reposo, calculado en directo
        self._acum_rr = poincare.AcumuladorRr()      # R-R de cada minuto (cualquier nivel) para Poincaré
        self.monitor_ratio = MonitorRatio()
        self.modo_escritorio = False
        self.detector_estres = DetectorEstres()
        self._nivel_reposo = False
        self._captura_coh: Optional[dict] = None
        self.detector_latido = fv.DetectorLatido()
        self.detectar_latidos = False                # solo se ejecuta si hay alguien escuchando (sonido / PiP)
        self.piloto = fv.PilotoZonaObjetivo()
        self._fc_max_cache: Optional[float] = None
        self.fantasma = fv.ControladorFantasma()
        self.acoplamiento = fv.CalculadorAcoplamientoRSA()

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
        self._demo = None                                  # Modo Demo (GeneradorDemo) y su temporizador
        self._timer_demo = None
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
        self._alimentar_sesion(self._state)
        self.state_changed.emit(self._state)

    def _alimentar_sesion(self, st: VitaBandUiState) -> None:
        def num(t):
            try:
                v = float(t.split()[0].replace(",", "."))
                return v if v > 0 else None
            except (ValueError, IndexError, AttributeError):
                return None
        ahora, bpm, rpm = self._reloj(), num(st.bpmTexto), num(st.rpmTexto)
        conectado = st.conexionEstado == ConexionEstado.CONECTADO
        self.sesion_directo.actualizar(conectado, st.calidadContacto != CalidadContacto.SIN_SENAL, bpm, rpm, ahora)
        self._inteligencia_en_vivo(ahora, bpm if conectado else None)
        self.monitor_ratio.actualizar(ahora, bpm if conectado else None, rpm if conectado else None)
        self.acoplamiento.agregar(ahora, bpm if conectado else None, rpm if conectado else None)
        if self.modo_escritorio and self.detector_estres.actualizar(
                ahora, conectado and self._nivel_reposo, None, rpm):
            self.aviso_estres.emit(self._texto_estres())
        c = self._captura_coh
        if c is not None and conectado:
            c["bpm"].append((ahora - c["t0"], bpm or 0.0))
            if rpm:
                c["rpm"].append(rpm)

    def _limpiar_datos(self) -> dict:
        """Vacía buffers y devuelve los campos de estado "sin datos".

        Incluye ``modoEcgCrudo=False``: el firmware reinicia el modo ECG a
        filtrado (0) en cada nueva conexión, así que la UI debe hacer lo mismo.
        """
        self._ecg_buffer.clear()
        self.detector_latido.reiniciar()
        self._contador_muestras = 0
        self._evaluaciones_calidad = 0
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
            "calidadContacto": CalidadContacto.SIN_SENAL,
        }

    # --- Acciones disparadas por el usuario desde la UI ---

    @Slot()
    def conectar(self) -> None:
        self.detener_demo()
        self._watchdog.stop()
        self._error_por_silencio = False
        self._emitir_nuevo_estado(
            conexionEstado=ConexionEstado.CONECTANDO,
            **self._limpiar_datos(),
        )
        self._mqtt.iniciar_conexion()

    # --- Modo Demo: telemetría sintética a 100 Hz para presentaciones (sin banda ni persistencia) ---
    @property
    def modo_demo(self) -> bool:
        return getattr(self, "_demo", None) is not None

    @property
    def demo_active(self) -> bool:
        return self.modo_demo

    @property
    def ble_connected(self) -> bool:
        """Banda física realmente enlazada: telemetría real en curso (nunca el simulador ni un intento pendiente)."""
        return (not self.modo_demo
                and self._state.conexionEstado in (ConexionEstado.CONECTADO, ConexionEstado.CALIBRANDO))

    def is_real_device_connected(self) -> bool:
        return self.ble_connected

    def reset_stream_state(self) -> None:
        """Detiene timer y generador del simulador y limpia banderas residuales (no emite estado)."""
        t = getattr(self, "_timer_demo", None)
        if t is not None:
            t.stop()
            t.deleteLater()
        self._timer_demo = None
        self._demo = None
        self._watchdog.stop()
        self._error_por_silencio = False

    def iniciar_demo(self, escenario: str = "Reposo") -> bool:
        """Solo se bloquea con una banda física conectada. Si el Demo ya estaba activo, se reinicia limpio;
        un intento de conexión pendiente o fallido (CONECTANDO/ERROR) se cancela en lugar de bloquear."""
        from PySide6.QtCore import QTimer
        from services.simulador_demo import GeneradorDemo
        if self.ble_connected:
            return False
        if not self.modo_demo and self._state.conexionEstado != ConexionEstado.DESCONECTADO:
            self._mqtt.cerrar_conexion()
        self.reset_stream_state()
        self._demo = GeneradorDemo(escenario)
        self._timer_demo = QTimer(self)
        self._timer_demo.setInterval(30)                         # 3 muestras de 10 ms por tic = 100 Hz
        self._timer_demo.timeout.connect(self._tic_demo)
        self._emitir_nuevo_estado(conexionEstado=ConexionEstado.CONECTADO, **self._limpiar_datos())
        self._timer_demo.start()
        return True

    def cambiar_escenario_demo(self, escenario: str) -> None:
        if self.modo_demo:
            from services.simulador_demo import GeneradorDemo
            self._demo = GeneradorDemo(escenario)

    @Slot()
    def _tic_demo(self) -> None:
        if not self.modo_demo:
            return
        for _ in range(3):
            self.on_paquete_telemetria(*self._demo.siguiente())

    def detener_demo(self) -> None:
        estaba = self.modo_demo
        self.reset_stream_state()
        if estaba:
            self._emitir_nuevo_estado(conexionEstado=ConexionEstado.DESCONECTADO, **self._limpiar_datos())

    @Slot()
    def desconectar(self) -> None:
        self.detener_demo()
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
        self.detector_latido.reiniciar()
        self._volcar_ecg(cerrar_segundo=True)   # el ECG crudo no se guarda en el histórico
        self._evaluaciones_calidad = 0
        self._emitir_nuevo_estado(
            modoEcgCrudo=activo_crudo, ecgMuestras=(), calidadContacto=CalidadContacto.SIN_SENAL)

    # --- Callbacks llamados por la capa MQTT en segundo plano ---

    @Slot(ConexionEstado)
    def on_estado_enlace_actualizado(self, nuevo_estado: ConexionEstado) -> None:
        if self.modo_demo:                       # el simulador manda: eventos rezagados de red no lo pisan
            return
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
            if self._captura_ecg is not None:
                self._captura_ecg.append((self._reloj(), ecg))
            if self.detectar_latidos and self.detector_latido.agregar(ecg):
                self.latido.emit()
            self._acumular_ecg(ecg)
            if not self.modo_demo:                       # la demo nunca ensucia el historial
                self._acumular_hrv(ecg, cod_actividad)
                self._acumular_rr(ecg)

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
            calidadContacto=self._calidad_contacto(),
        )

    def _calidad_contacto(self) -> CalidadContacto:
        """Calidad de contacto sobre el ECG reciente; se reevalúa cada ~0,3 s, no en cada emisión."""
        self._evaluaciones_calidad += 1
        if self._evaluaciones_calidad % _CADA_N_EMISIONES_CALIDAD != 1:
            return self._state.calidadContacto
        return evaluar_calidad(self._ecg_buffer, enlace_activo=True)

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

        if self._repositorio is None or self.modo_demo or self._state.conexionEstado != ConexionEstado.CONECTADO:
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
        if self._repositorio is None or self._state.modoEcgCrudo or self.modo_demo:
            return
        self._ecg_pendiente.extend(self._acum_ecg.agregar(int(self._reloj()), valor))
        if len(self._ecg_pendiente) >= _MAX_ECG_PENDIENTE:
            self._volcar_ecg()

    def _acumular_rr(self, valor: float) -> None:
        """R-R de cada minuto de ECG filtrado y conectado, a cualquier nivel de actividad."""
        if (self._repositorio is None or self._state.modoEcgCrudo
                or self._state.conexionEstado != ConexionEstado.CONECTADO):
            self._acum_rr.reiniciar()
            return
        try:
            ventana = self._acum_rr.agregar(self._reloj(), valor)
            if ventana is not None:
                self._repositorio.guardar_rr(*ventana)
        except Exception:
            logger.exception("No se pudieron guardar los intervalos R-R")

    def _acumular_hrv(self, valor: float, nivel: int) -> None:
        """Alimenta el cálculo de HRV solo con ECG filtrado, conectado y en reposo."""
        self._nivel_reposo = nivel == NIVEL_REPOSO
        if (self._repositorio is None or self._state.modoEcgCrudo
                or self._state.conexionEstado != ConexionEstado.CONECTADO or nivel != NIVEL_REPOSO):
            self._acum_hrv.reiniciar()
            return
        try:
            resultado = self._acum_hrv.agregar(self._reloj(), valor)
            if resultado is not None:
                self._repositorio.guardar_hrv(resultado)
                self.rmssd_calculado.emit(float(resultado.rmssd_ms))
                if self.modo_escritorio and self.detector_estres.actualizar(
                        self._reloj(), True, resultado.rmssd_ms, None):
                    self.aviso_estres.emit(self._texto_estres())
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

    def cargar_datos_ejemplo(self) -> Optional[dict]:
        """Importa el conjunto de datos SINTÉTICOS de ejemplo (idempotente) y refresca las vistas."""
        if self._repositorio is None:
            return None
        try:
            resumen = datos_ejemplo.cargar(self._repositorio)
        except Exception:
            logger.exception("No se pudieron cargar los datos de ejemplo")
            return None
        try:
            ia_local_sesion.IaLocalSesion(self._repositorio).procesar_pendientes()
        except Exception:
            logger.exception("IA local tras cargar datos de ejemplo")
        self._actualizar_observaciones()
        self.historial_actualizado.emit()
        self.sesion_importada.emit()
        return resumen

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
            if self._repositorio is not None:                                  # IA local: disciplina + veredicto
                try:
                    ia_local_sesion.IaLocalSesion(self._repositorio).procesar_pendientes()
                except Exception:
                    logger.exception("IA local tras sincronizar")
            if actualizar_observaciones:
                self._actualizar_observaciones()
            self.historial_actualizado.emit()
            self.sesion_importada.emit()
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

    def comparar_actividades(self, id_a: int, id_b: int) -> Optional[comparador_sesiones.Comparativa]:
        """«Antes vs. Ahora» de dos actividades distintas; None si falta alguna."""
        if id_a == id_b:
            return None
        da, db = self.detalle_actividad(id_a), self.detalle_actividad(id_b)
        if da is None or db is None:
            return None
        return comparador_sesiones.comparar((da.actividad, da.mediciones), (db.actividad, db.mediciones))

    def analisis_actividad(self, detalle) -> zonas_actividad.AnalisisActividad:
        """Zonas cardíacas y umbral de fatiga de una actividad, calculados al vuelo (no se guardan)."""
        try:
            return zonas_actividad.analizar_actividad(detalle.mediciones, detalle.actividad.inicio_ts)
        except Exception:
            logger.exception("No se pudo analizar la actividad")
            return zonas_actividad.AnalisisActividad(
                None, zonas_actividad.ResultadoUmbral(None, "No se pudo analizar la actividad."))

    def ecg_historico(self, desde_ts: int, hasta_ts: int, n_bins: int = 600):
        return self._consultar(lambda c: c.ecg(desde_ts, hasta_ts, n_bins), None)

    def observaciones(self, desde_ts: int, hasta_ts: int, tipo: Optional[str] = None) -> list:
        return self._consultar(lambda c: c.observaciones(desde_ts, hasta_ts, tipo), [])

    # --- Marcadores de contexto en la línea temporal ---

    def marcadores(self, desde_ts: int, hasta_ts: int) -> list[tuple[int, str]]:
        if self._repositorio is None:
            return []
        try:
            return self._repositorio.marcadores_rango(desde_ts, hasta_ts)
        except sqlite3.Error:
            logger.exception("No se pudieron leer los marcadores")
            return []

    def observaciones_periodo(self, desde_ts: int, hasta_ts: int) -> list:
        """Observaciones diarias y cruces con marcadores (los cruces primero)."""
        return (self.observaciones(desde_ts, hasta_ts, "CONTEXTO")
                + self.observaciones(desde_ts, hasta_ts, "DIARIA"))

    def poner_marcador(self, ts: int, etiqueta: str) -> None:
        self._repositorio_requerido().guardar_marcador(ts, etiqueta)
        self._tras_borrado(True)                    # regenera observaciones y avisa a la vista

    def poner_habito(self, texto: str) -> str:
        """Hábito libre (p. ej. «Siesta 30 min») como marcador de contexto de ahora; devuelve la etiqueta guardada."""
        etiqueta = marcadores_contexto.normalizar_etiqueta(texto)
        ts = int(self._reloj())
        usados = {t for t, _ in self._repositorio_requerido().marcadores_rango(ts - 5, ts + 60)}
        while ts in usados:                                              # un marcador por segundo y cuenta
            ts += 1
        self.poner_marcador(ts, etiqueta)
        return etiqueta

    def habitos_recientes(self, horas: int = 24) -> list[str]:
        """Etiquetas (predefinidas y personalizadas) de las últimas ``horas``, más recientes primero."""
        if self._repositorio is None:
            return []
        ahora = int(self._reloj())
        vistos: list[str] = []
        for _, e in sorted(self._repositorio.marcadores_rango(ahora - horas * 3600, ahora + 61), reverse=True):
            if e not in vistos:
                vistos.append(e)
        return vistos

    def quitar_marcador(self, ts: int) -> bool:
        quitado = self._repositorio_requerido().quitar_marcador(ts)
        self._tras_borrado(quitado)
        return quitado

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
        sujeto: Optional[str] = None,
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
        return exportar_historial_csv(mediciones, ruta, sujeto)

    # --- Vueltas, ortostático, perfil, kcal, RPE y constancia ---

    def tiempo(self) -> float:
        return self._reloj()

    @property
    def repositorio(self):
        """Repositorio de la cuenta activa (None si no hay); los paneles lo usan para leer/editar sus datos."""
        return self._repositorio

    def contexto_coach(self):
        """Contexto de solo lectura para el Coach IA (llamar siempre desde el hilo principal)."""
        from services import coach_ia
        return coach_ia.recopilar_contexto(self._repositorio, self.perfil(), int(self._reloj()))

    # --- Inteligencia biométrica (Coach de salud) ---
    def _fc_max_zonas(self) -> float:
        try:
            m = self.memoria_coach()
            ficha = m.ficha() if m is not None else {}
            if ficha.get("fc_max"):
                return float(ficha["fc_max"])
            p = self.perfil()
            return float(vo2max.fc_max_tanaka(p.edad)) if p and p.edad else float(fv.FC_MAX_REFERENCIA)
        except Exception:
            return float(fv.FC_MAX_REFERENCIA)

    def _inteligencia_en_vivo(self, ahora: float, bpm: Optional[float]) -> None:
        try:
            if bpm:
                self._bpm_hist.append((ahora, bpm))
            if self._hrr_pend is not None and ahora >= self._hrr_pend["t0"] + 125:
                t0 = self._hrr_pend["t0"]
                self._hrr_pend = None
                h = ib.calcular_hrr(list(self._bpm_hist), t0)
                if h is not None and self._repositorio is not None:
                    ib.RecuperacionSesiones(self._repositorio).guardar(int(t0), h)
                    self.hrr_calculado.emit(h)
            if self._repositorio is None or not self.sesion_directo.activa or self.sesion_directo.pausada:
                self.susurrador.actualizar(ahora, None, 190)
                return
            hoy = datetime.fromtimestamp(ahora).date()
            if self._zona_obj[0] != hoy or (self._zona_obj[1] is None and ahora - self._zona_obj[2] > 60):
                self._zona_obj = (hoy, ib.zona_objetivo_hoy(self._repositorio, hoy), ahora)
            self.susurrador.zona_objetivo = self._zona_obj[1]
            consejo = self.susurrador.actualizar(ahora, bpm, self._fc_max_zonas())
            if consejo:
                self.susurro.emit(consejo)
        except Exception:
            logger.exception("Inteligencia en vivo")

    def invalidar_zona_objetivo(self) -> None:
        self._zona_obj = (None, None, 0.0)

    def finalizar_sesion(self) -> bool:
        """Cierra el esfuerzo: arranca la medición de HRR 1'/2' (se calcula y guarda a los ~2 min)."""
        ahora = self._reloj()
        recientes = [b for t, b in self._bpm_hist if ahora - 30 <= t <= ahora]
        if len(recientes) < 3:
            return False
        self._hrr_pend = {"t0": ahora}
        self.susurrador.reiniciar()
        self.sesion_directo.reiniciar()
        return True

    def evaluar_hrr_actividad(self, actividad):
        return None if self._repositorio is None else ib.evaluar_sesion_cerrada(self._repositorio, actividad)

    def registrar_habito_diario(self, etiqueta: str) -> bool:
        if self._repositorio is None:
            return False
        return ib.RegistroHabitos(self._repositorio).registrar(etiqueta, datetime.fromtimestamp(self._reloj()).date())

    def habitos_de_hoy(self) -> list:
        return [] if self._repositorio is None else ib.RegistroHabitos(self._repositorio).del_dia(
            datetime.fromtimestamp(self._reloj()).date())

    def alerta_preventiva(self):
        return None if self._repositorio is None else ib.escudo_preventivo(self._repositorio, int(self._reloj()))

    def motivo_reajuste(self):
        return None if self._repositorio is None else ib.detectar_reajuste(self._repositorio, datetime.fromtimestamp(self._reloj()).date())

    def reajustar_semana(self) -> str:
        """Modo Vida Real: acorta y suaviza lo que queda de semana y devuelve la explicación empática."""
        if self._repositorio is None:
            return ""
        hoy = datetime.fromtimestamp(self._reloj()).date()
        motivo = ib.detectar_reajuste(self._repositorio, hoy)
        return ib.mensaje_reajuste(motivo, ib.reajustar_semana(self._repositorio, hoy))

    def informe_clinico(self) -> str:
        return "" if self._repositorio is None else ib.informe_clinico(self._repositorio, int(self._reloj()))

    def memoria_coach(self):
        """Memoria persistente del Coach (tabla coach_memoria); None sin historial."""
        if self._repositorio is None:
            return None
        from services.contexto_coach import MemoriaCoach
        return MemoriaCoach(self._repositorio)

    def app_meta(self):
        if self._repositorio is None:
            return None
        from services.app_meta import AppMeta
        return AppMeta(self._repositorio)

    def contexto_total_coach(self) -> str:
        from services import contexto_coach
        try:
            return contexto_coach.contexto_total(self)
        except Exception:
            logger.exception("Contexto total del Coach")
            return ""

    def marcar_vuelta(self) -> Optional[int]:
        """Marca una vuelta de la sesión en directo. None si no hay sesión (banda no conectada) o BD."""
        if self._repositorio is None or not self.sesion_directo.activa:
            return None
        self.sesion_directo.vueltas += 1
        n = self.sesion_directo.vueltas
        self._repositorio.guardar_vuelta(int(self._reloj()), n)
        self.vuelta_marcada.emit(n)
        return n

    def desglose_vueltas(self, detalle) -> list:
        if self._repositorio is None:
            return []
        a = detalle.actividad
        return calc.desglose_vueltas(a.inicio_ts, a.fin_ts, self._repositorio.vueltas_rango(a.inicio_ts, a.fin_ts),
                                     detalle.mediciones)

    def iniciar_captura_ecg(self) -> None:
        self._captura_ecg = []

    def detener_captura_ecg(self) -> list:
        captura, self._captura_ecg = self._captura_ecg or [], None
        return captura

    def guardar_test_ortostatico(self, r: calc.ResultadoOrtostatico, ts: int) -> None:
        if self._repositorio is not None:
            self._repositorio.guardar_test_ortostatico(
                ts, r.fc_basal, r.rmssd_basal, r.fc_pico, r.fc_estable, r.rmssd_pie, r.delta_fc, r.valoracion)

    def perfil(self) -> calc.PerfilFisiologico:
        f = None if self._repositorio is None else self._repositorio.perfil()
        if f is None:
            return calc.PerfilFisiologico()
        return calc.PerfilFisiologico(f["edad"], f["sexo"], f["peso_kg"], f["objetivo_semanal_min"])

    def guardar_perfil(self, perfil: calc.PerfilFisiologico) -> None:
        self._repositorio_requerido().guardar_perfil(perfil.edad, perfil.sexo, perfil.peso_kg,
                                                     perfil.objetivo_semanal_min)
        self._fc_max_cache = None
        self.historial_actualizado.emit()

    # --- Funciones en vivo: latido, fantasma, piloto de zona, acoplamiento y tarjeta ---

    def fc_max(self) -> float:
        """FCmáx personalizada (Tanaka con la edad del perfil; sin edad, la de referencia)."""
        if self._fc_max_cache is None:
            self._fc_max_cache = fv.fc_max_usuario(self.perfil().edad)
        return self._fc_max_cache

    def activar_latidos(self, activo: bool) -> None:
        self.detectar_latidos = bool(activo)
        self.detector_latido.reiniciar()

    @property
    def zona_objetivo(self) -> Optional[int]:
        return self.piloto.zona

    def set_zona_objetivo(self, zona: Optional[int]) -> None:
        if zona is not None and not 0 <= zona <= 4:
            raise ValueError("Zona objetivo fuera de rango")
        if zona != self.piloto.zona:
            self.piloto.zona = zona
            self.zona_objetivo_cambiada.emit(zona)

    def evaluar_piloto(self, bpm: Optional[float]) -> fv.ResultadoPiloto:
        self.piloto.fc_max = self.fc_max()
        return self.piloto.evaluar(bpm)

    def fantasmas_disponibles(self) -> list[tuple[int, str]]:
        """Sesiones guardadas del usuario activo (la más reciente primero) con pulso suficiente."""
        if self._repositorio is None:
            return []
        salida = []
        for r in sorted(self.actividades(0, _TS_MAXIMO), key=lambda r: -r.actividad.inicio_ts):
            a = r.actividad
            if r.mediciones >= 10:
                salida.append((a.id, f"{datetime.fromtimestamp(a.inicio_ts):%d/%m/%Y %H:%M} · {a.duracion_s / 60:.0f} min"))
        return salida

    def seleccionar_fantasma(self, actividad_id: Optional[int]) -> bool:
        if actividad_id is None:
            self.fantasma.cargar(None)
            return True
        d = self.detalle_actividad(actividad_id)
        puntos = [] if d is None else fv.puntos_de_mediciones(d.actividad.inicio_ts, d.mediciones)
        if len(puntos) < 10:
            self.fantasma.cargar(None)
            return False
        self.fantasma.cargar(fv.SesionFantasma(d.actividad.inicio_ts, puntos))
        return True

    def tiempo_sesion_s(self) -> float:
        return self.sesion_directo.tiempo_efectivo_s

    def comparacion_fantasma(self) -> Optional[fv.ComparacionFantasma]:
        """ΔBPM frente a la sesión fantasma en el mismo segundo de la sesión en directo."""
        if not self.fantasma.activo or self._state.conexionEstado != ConexionEstado.CONECTADO:
            return None
        try:
            bpm = float(self._state.bpmTexto.split()[0].replace(",", "."))
        except (ValueError, IndexError, AttributeError):
            return None
        return self.fantasma.actualizar(self.tiempo_sesion_s(), bpm)

    def datos_tarjeta(self, detalle) -> tarjeta_resumen.DatosTarjeta:
        a = detalle.actividad
        zonas = self.analisis_actividad(detalle).zonas
        m = self.metricas_actividad(detalle)
        return tarjeta_resumen.DatosTarjeta(
            a.inicio_ts, a.duracion_s, fv.puntos_de_mediciones(a.inicio_ts, detalle.mediciones),
            None if zonas is None or zonas.total_s <= 0 else zonas.porcentajes,
            self.kcal_actividad(detalle), m["trimp"], tuple(self.records_personales().get(a.id, ())),
            self.disciplinas().get(a.id))

    def exportar_tarjeta(self, actividad_id: int, ruta: str) -> bool:
        detalle = self.detalle_actividad(actividad_id)
        if detalle is None:
            raise RuntimeError("La actividad ya no existe")
        return tarjeta_resumen.guardar_tarjeta(self.datos_tarjeta(detalle), ruta)

    # --- Coherencia, Poincaré, VO2máx, disciplinas, ratio y Modo Escritorio ---

    def iniciar_coherencia(self) -> None:
        self._captura_coh = {"t0": self._reloj(), "bpm": [], "rpm": []}

    def detener_coherencia(self, rpm_guia: float = coherencia.RPM_GUIA) -> coherencia.ResultadoCoherencia:
        c, self._captura_coh = self._captura_coh, None
        if c is None:
            return coherencia.resultado([], [], 0.0, rpm_guia)
        return coherencia.resultado(c["bpm"], c["rpm"], self._reloj() - c["t0"], rpm_guia)

    def _texto_estres(self) -> str:
        from services.estres_escritorio import TEXTO_AVISO
        return TEXTO_AVISO

    def balance_mental(self):
        """Balance diario de carga mental (SQLite); None sin historial."""
        if self._repositorio is None:
            return None
        from services.balance_mental import BalanceCargaMental
        return BalanceCargaMental(self._repositorio)

    def configurar_modo_escritorio(self, activo: bool, ventana_min: float = 20) -> None:
        self.modo_escritorio = bool(activo)
        self.detector_estres.ventana_min = max(1.0, float(ventana_min))
        self.detector_estres.reiniciar()

    def ratio_directo(self) -> tuple[Optional[float], bool]:
        return self.monitor_ratio.ratio, self.monitor_ratio.alerta

    def poincare(self, desde_ts: int, hasta_ts: int) -> poincare.Poincare:
        ventanas = [] if self._repositorio is None else self._repositorio.rr_rango(desde_ts - 60, hasta_ts)
        return poincare.calcular_poincare(ventanas)

    def _hoy(self):
        return datetime.fromtimestamp(self._reloj()).date()

    def estimacion_vo2(self):
        if self._repositorio is None:
            return None
        ahora = int(self._reloj())
        reposo = vo2max.fc_reposo(self._repositorio.mediciones_rango(ahora - 30 * 86400, ahora + 1))
        obs = vo2max.fc_max_observada(
            self._repositorio.mediciones_rango(ahora - vo2max.VENTANA_FCMAX_DIAS * 86400, ahora + 1))
        return vo2max.estimar(reposo, obs, self.perfil())

    def evolucion_vo2(self, meses: int = 6):
        if self._repositorio is None:
            return []
        return vo2max.evolucion_mensual(self._repositorio, self.perfil(), self._hoy(), meses)

    def guardar_disciplina(self, actividad_id: int, disciplina: Optional[str]) -> None:
        if disciplina not in (None, ""):
            disciplina = disc.normalizar_disciplina(disciplina)            # predefinida o personalizada
        self._repositorio_requerido().guardar_disciplina(actividad_id, disciplina)
        self.historial_actualizado.emit()

    def disciplinas(self) -> dict[int, str]:
        return {} if self._repositorio is None else self._repositorio.disciplinas()

    def records_personales(self, desde_ts: int = 0, hasta_ts: int = _TS_MAXIMO) -> dict[int, list[str]]:
        if self._repositorio is None:
            return {}
        return disc.records_personales(disc.resumenes(self._repositorio, desde_ts, hasta_ts))

    def kcal_actividad(self, detalle) -> Optional[float]:
        return calc.kcal_actividad(detalle.mediciones, self.perfil())

    def kcal_sesion_directo(self) -> Optional[float]:
        s = self.sesion_directo
        return calc.kcal_keytel(s.bpm_medio, s.tiempo_efectivo_s / 60.0, self.perfil())

    def nota_sesion(self, actividad_id: int):
        return None if self._repositorio is None else self._repositorio.nota_sesion(actividad_id)

    def veredicto_actividad(self, actividad_id: int) -> Optional[str]:
        """IA local: veredicto de 3 líneas (cacheado). La primera vez también auto-etiqueta la disciplina."""
        if self._repositorio is None:
            return None
        try:
            return ia_local_sesion.IaLocalSesion(self._repositorio).procesar(actividad_id)
        except Exception:
            logger.exception("No se pudo generar el veredicto")
            return None

    def guardar_nota_sesion(self, actividad_id: int, rpe: Optional[int], nota: str) -> None:
        self._repositorio_requerido().guardar_nota_sesion(actividad_id, rpe, nota)
        if self.veredicto_actividad(actividad_id) is not None:                  # el RPE cambia el veredicto
            ia_local_sesion.IaLocalSesion(self._repositorio).procesar(actividad_id, regenerar=True)
        self._actualizar_observaciones()
        self.observaciones_actualizadas.emit()

    def constancia(self, hoy=None) -> dict:
        """Mapa de calor: días, objetivo, minutos de la semana, rachas y kcal semanal."""
        from datetime import date as _date, timedelta as _td
        hoy = hoy or _date.today()
        perfil = self.perfil()
        if self._repositorio is None:
            dias = {}
        else:
            dias = constancia.resumen_dias(self._repositorio, hoy - _td(weeks=52), hoy, perfil)
        obj = perfil.objetivo_semanal_min
        return {"dias": dias, "hoy": hoy, "objetivo": obj, "perfil": perfil,
                "minutos_semana": constancia.minutos_semana(dias, constancia.lunes(hoy)),
                "racha_semanas": constancia.racha_semanas(dias, hoy, obj),
                "racha_dias": constancia.racha_dias(dias, hoy),
                "kcal_semana": constancia.kcal_semana(dias, hoy)}

    def guardar_objetivo_semanal(self, minutos: int) -> None:
        p = self.perfil()
        self._repositorio_requerido().guardar_perfil(p.edad, p.sexo, p.peso_kg, int(minutos))

    # --- Métricas avanzadas, TCX y copia de seguridad ---

    def carga_entrenamiento(self) -> metricas.EstadoCarga:
        if self._repositorio is None:
            return metricas.estado_carga([], int(time.time()))
        return metricas.carga_entrenamiento(self._repositorio, int(time.time()))

    def tarjetas_semanales(self) -> list:
        if self._repositorio is None:
            return []
        return metricas.tarjetas_semanales(self._repositorio, int(time.time()))

    def metricas_actividad(self, detalle) -> dict:
        """TRIMP, HRR-60 y deriva cardíaca de una actividad (al vuelo, sin guardar)."""
        a, ms = detalle.actividad, detalle.mediciones
        return {"trimp": metricas.trimp(ms), "hrr60": metricas.hrr60(ms),
                "deriva": metricas.deriva_cardiaca(ms, a.inicio_ts, a.fin_ts)}

    def exportar_tcx(self, actividad_id: int, ruta: str) -> int:
        detalle = self.detalle_actividad(actividad_id)
        if detalle is None:
            raise RuntimeError("La actividad ya no existe")
        return _tcx.exportar_tcx(detalle.actividad, detalle.mediciones, ruta)

    def exportar_backup(self, ruta: str) -> str:
        return backup_db.exportar_backup(self._repositorio_requerido().conexion, ruta)

    def restaurar_backup(self, ruta: str) -> str:
        """Restaura una copia (.zip) sobre la BD abierta y refresca las vistas. Devuelve la ruta del .bak."""
        repo = self._repositorio_requerido()
        bak = backup_db.restaurar_backup(repo.conexion, ruta, repo._usuario_id)
        repo.asegurar_esquema()
        self._actualizar_observaciones()
        self.historial_actualizado.emit()
        self.observaciones_actualizadas.emit()
        return bak

    def exportar_pdf(self, ruta: str, desde_ts: int, hasta_ts: int, nombre: str = "", correo: str = "",
                     anonimizar: bool = False) -> str:
        """Informe biométrico en PDF del rango [desde_ts, hasta_ts). Devuelve la ruta escrita."""
        from services.exportar_pdf import PerfilInforme, generar_informe_pdf
        anonimizar_id = anonimizar_mod.seudonimo(correo, nombre)
        correo_pdf = "oculto (datos anonimizados)"
        return generar_informe_pdf(
            ruta, self._repositorio_requerido(), desde_ts, hasta_ts,
            PerfilInforme(nombre=anonimizar_id, correo=correo_pdf) if anonimizar else
            PerfilInforme(nombre=nombre, correo=correo or None))

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
