import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from domain.ui_state import ConexionEstado, VitaBandUiState
from viewmodel.vitaband_vm import VitaBandViewModel


class MainWindow(QMainWindow):
    def __init__(self, view_model: VitaBandViewModel):
        super().__init__()
        self.vm = view_model
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

        # Barra superior: estado de enlace y sincronización (RF-11, RF-21)
        barra_top = QHBoxLayout()
        self.lbl_conexion = QLabel()
        self.btn_conectar = QPushButton("Conectar")
        self.btn_desconectar = QPushButton("Desconectar")
        self.lbl_sync = QLabel()

        barra_top.addWidget(self.lbl_conexion)
        barra_top.addWidget(self.btn_conectar)
        barra_top.addWidget(self.btn_desconectar)
        barra_top.addStretch()
        barra_top.addWidget(self.lbl_sync)
        layout.addLayout(barra_top)

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
        pg.setConfigOption("background", "w")
        pg.setConfigOption("foreground", "k")
        self.plot_widget = pg.PlotWidget(title="Señal ECG (100 Hz)")
        self.plot_widget.setLabel("left", "Amplitud (ADC)")
        self.plot_widget.setLabel("bottom", "Tiempo", units="s")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.curva_ecg = self.plot_widget.plot(pen=pg.mkPen("#1f77b4", width=2))
        layout.addWidget(self.plot_widget)

        # Eventos de usuario -> llamadas directas al ViewModel
        self.btn_conectar.clicked.connect(self.vm.conectar)
        self.btn_desconectar.clicked.connect(self.vm.desconectar)
        self.chk_ecg_crudo.toggled.connect(self.vm.cambiarModoEcg)

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

        # 3. Estado de sincronización
        if state.sincronizando:
            self.lbl_sync.setText("Sync: Sincronizando registros...")
        elif state.pendientesSync > 0:
            self.lbl_sync.setText(f"Sync: {state.pendientesSync} registros pendientes")
        else:
            self.lbl_sync.setText("Sync: Al día")

        # 4. Renderizado ECG
        if state.ecgMuestras:
            y = np.asarray(state.ecgMuestras, dtype=np.float32)
            x = np.arange(len(y), dtype=np.float32) * 0.01  # dt = 10 ms (100 Hz)
            self.curva_ecg.setData(x, y)
            # Escala Y adaptada: [0..4095] en crudo, centrada en 1600 en filtrada
            if state.modoEcgCrudo:
                self.plot_widget.setYRange(0, 4095, padding=0.05)
            else:
                self.plot_widget.setYRange(1100, 2100, padding=0.05)
        else:
            self.curva_ecg.setData([], [])