from datetime import date

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from domain.ui_state import ConexionEstado, VitaBandUiState
from ui.confirmaciones import confirmar
from ui.dialogo_eliminar_cuenta import DialogoEliminarCuenta
from ui.vista_actividades import VistaActividades
from ui.vista_historial import VistaHistorialPeriodico
from viewmodel.vitaband_vm import VitaBandViewModel

# Escala vertical del ECG. En la señal filtrada el reposo queda centrado en
# OFFSET_ECG = 1600; el margen amplio evita recortar los artefactos de movimiento
# y sudor que aparecen al correr.
RANGO_Y_FILTRADA = (900, 2300)
RANGO_Y_CRUDA = (0, 4095)


class MainWindow(QMainWindow):
    # La ventana no decide qué pasa al cerrar sesión o salir: avisa al controlador.
    cerrar_sesion_solicitada = Signal()
    ventana_cerrada = Signal()
    # RF-39: se emite solo tras la doble confirmación; lleva la contraseña para revalidarla
    eliminar_cuenta_solicitada = Signal(str)

    def __init__(self, view_model: VitaBandViewModel, nombre_usuario: str = ""):
        super().__init__()
        self.vm = view_model
        self._nombre_usuario = nombre_usuario
        self._modo_y_aplicado = None  # None = escala Y aún sin fijar
        self.setWindowTitle("VitaBand Desktop — Monitorización")
        self.resize(1100, 700)

        self._construir_ui()

        # Suscripción única al contrato de estado
        self.vm.state_changed.connect(self.render)
        # Pintado inicial
        self.render(self.vm.state)

    def _construir_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Barra superior: estado de enlace, exportación y sesión (RF-11)
        barra_top = QHBoxLayout()
        self.lbl_conexion = QLabel()
        self.btn_conectar = QPushButton("Conectar")
        self.btn_desconectar = QPushButton("Desconectar")

        barra_top.addWidget(self.lbl_conexion)
        barra_top.addWidget(self.btn_conectar)
        barra_top.addWidget(self.btn_desconectar)
        barra_top.addStretch()
        self.btn_sincronizar = QPushButton("Sincronizar ahora")
        self.btn_exportar_csv = QPushButton("Exportar historial (CSV)")
        self.btn_eliminar_cuenta = QPushButton("Eliminar cuenta")
        self.lbl_usuario = QLabel(f"Usuario: {self._nombre_usuario}" if self._nombre_usuario else "")
        self.btn_cerrar_sesion = QPushButton("Cerrar sesión")
        barra_top.addWidget(self.btn_sincronizar)
        barra_top.addWidget(self.btn_exportar_csv)
        barra_top.addWidget(self.lbl_usuario)
        barra_top.addWidget(self.btn_eliminar_cuenta)
        barra_top.addWidget(self.btn_cerrar_sesion)
        layout.addLayout(barra_top)

        # Pestañas: monitorización en tiempo real e historial por fecha
        pg.setConfigOption("background", "w")
        pg.setConfigOption("foreground", "k")
        self.pestanas = QTabWidget()
        self.pestanas.addTab(self._construir_tiempo_real(), "Tiempo real")
        self.vista_historial = VistaHistorialPeriodico(self.vm)
        self.vista_actividades = VistaActividades(self.vm)
        self.pestanas.addTab(self.vista_historial, "Historial periódico")
        self.pestanas.addTab(self.vista_actividades, "Actividades")
        layout.addWidget(self.pestanas)

        # Barra de estado: estado de la sincronización con el móvil (RF-21)
        self.setStatusBar(QStatusBar())
        self.lbl_sync = QLabel()
        self.statusBar().addWidget(self.lbl_sync, 1)

        # Eventos de usuario -> llamadas directas al ViewModel
        self.btn_conectar.clicked.connect(self.vm.conectar)
        self.btn_desconectar.clicked.connect(self.vm.desconectar)
        self.chk_ecg_crudo.toggled.connect(self.vm.cambiarModoEcg)
        self.btn_cerrar_sesion.clicked.connect(self.cerrar_sesion_solicitada)
        self.btn_exportar_csv.clicked.connect(self._exportar_csv)
        self.btn_sincronizar.clicked.connect(self.vm.sincronizar)
        self.btn_eliminar_cuenta.clicked.connect(self._pedir_eliminar_cuenta)
        self.pestanas.currentChanged.connect(self._on_cambio_pestana)

    def _construir_tiempo_real(self) -> QWidget:
        pagina = QWidget()
        layout = QVBoxLayout(pagina)

        # Tarjetas de constantes vitales (RF-08)
        fila_metricas = QHBoxLayout()
        self.lbl_bpm = QLabel()
        self.lbl_rpm = QLabel()
        self.lbl_temp = QLabel()
        self.lbl_actividad = QLabel()
        for lbl in (self.lbl_bpm, self.lbl_rpm, self.lbl_temp, self.lbl_actividad):
            lbl.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px;")
            fila_metricas.addWidget(lbl)
        layout.addLayout(fila_metricas)

        # Banner de aviso experimental
        self.lbl_aviso = QLabel()
        self.lbl_aviso.setStyleSheet("font-size: 15px; padding: 6px;")
        layout.addWidget(self.lbl_aviso)

        # Selector ECG filtrada / cruda (RF-10)
        self.chk_ecg_crudo = QCheckBox("Mostrar señal ECG cruda (sin filtro Butterworth)")
        layout.addWidget(self.chk_ecg_crudo)

        # Gráfica PyQtGraph de alto rendimiento (100 Hz)
        self.plot_widget = pg.PlotWidget(title="Señal ECG (100 Hz)")
        self.plot_widget.setLabel("left", "Amplitud (ADC)")
        self.plot_widget.setLabel("bottom", "Tiempo", units="s")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.curva_ecg = self.plot_widget.plot(pen=pg.mkPen("#1f77b4", width=2))
        layout.addWidget(self.plot_widget)
        return pagina

    @Slot(int)
    def _on_cambio_pestana(self, indice: int) -> None:
        pagina = self.pestanas.widget(indice)
        if pagina in (self.vista_historial, self.vista_actividades):
            pagina.actualizar()

    @Slot()
    def _pedir_eliminar_cuenta(self) -> None:
        """Doble confirmación: aviso con el alcance y diálogo con palabra clave + contraseña."""
        if not confirmar(
            self, "Eliminar cuenta",
            "Vas a eliminar tu cuenta y TODOS tus datos de este equipo: mediciones, actividades, "
            "ECG, observaciones y estado de sincronización.\n\n"
            "No se podrá deshacer. Las copias que hayas exportado (CSV) o los archivos de "
            "intercambio no se borran.",
            "Continuar",
        ):
            return
        dialogo = DialogoEliminarCuenta(self._nombre_usuario, self)
        if dialogo.exec() != DialogoEliminarCuenta.DialogCode.Accepted:
            return
        self.eliminar_cuenta_solicitada.emit(dialogo.password())

    @Slot()
    def _exportar_csv(self) -> None:
        sugerido = f"vitaband_historial_{date.today():%Y-%m-%d}.csv"
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Exportar historial a CSV", sugerido, "Archivos CSV (*.csv)"
        )
        if not ruta:
            return

        try:
            filas = self.vm.exportar_csv(ruta)
        except Exception as exc:
            QMessageBox.warning(self, "No se pudo exportar", f"Error al exportar el historial:\n{exc}")
            return

        QMessageBox.information(
            self, "Exportación completada", f"Se exportaron {filas} registros a:\n{ruta}"
        )

    @Slot(VitaBandUiState)
    def render(self, state: VitaBandUiState) -> None:
        # 1. Estado de conexión y habilitación de controles
        conectado = state.conexionEstado == ConexionEstado.CONECTADO
        calibrando = state.conexionEstado == ConexionEstado.CALIBRANDO
        en_curso = conectado or calibrando or state.conexionEstado == ConexionEstado.CONECTANDO

        self.lbl_conexion.setText(f"Estado: {state.conexionEstado.value}")
        self.btn_conectar.setEnabled(not en_curso)
        self.btn_desconectar.setEnabled(en_curso)
        self.chk_ecg_crudo.setEnabled(conectado)

        # Sincronizamos el checkbox sin disparar de nuevo el evento toggled
        self.chk_ecg_crudo.blockSignals(True)
        self.chk_ecg_crudo.setChecked(state.modoEcgCrudo)
        self.chk_ecg_crudo.blockSignals(False)

        # Sincronización con el móvil
        self.lbl_sync.setText(f"Sincronización: {state.syncTexto}")
        self.lbl_sync.setToolTip(
            f"Sincronizados: {state.syncSincronizados} · Pendientes: {state.syncPendientes} · "
            f"Con error: {state.syncErrores}")

        # 2. Constantes vitales y contexto
        if calibrando:
            self.lbl_bpm.setText("FC: Calibrando respiración (6 s)...")
            self.lbl_rpm.setText("FR: Esperando calibración...")
        else:
            self.lbl_bpm.setText(f"FC: {state.bpmTexto}")
            self.lbl_rpm.setText(f"FR: {state.rpmTexto}")

        self.lbl_temp.setText(f"Temp: {state.tempTexto}")
        self.lbl_actividad.setText(f"Actividad: {state.nivelActividad}")
        self.lbl_aviso.setText(state.avisoExperimental)

        # 3. Renderizado ECG
        if state.ecgMuestras:
            y = np.asarray(state.ecgMuestras, dtype=np.float32)
            x = np.arange(len(y), dtype=np.float32) * 0.01  # dt = 10 ms (100 Hz)
            self.curva_ecg.setData(x, y)
            # Escala Y según el modo; solo se reaplica cuando cambia (no en cada
            # render a ~33 Hz).
            if self._modo_y_aplicado != state.modoEcgCrudo:
                rango = RANGO_Y_CRUDA if state.modoEcgCrudo else RANGO_Y_FILTRADA
                self.plot_widget.setYRange(*rango, padding=0.05)
                self._modo_y_aplicado = state.modoEcgCrudo
        else:
            self.curva_ecg.setData([], [])

    def closeEvent(self, event) -> None:
        self.ventana_cerrada.emit()
        super().closeEvent(event)
