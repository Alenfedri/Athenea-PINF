from datetime import date

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QProgressBar,
    QSlider,
    QFrame,
    QMenu,
    QToolButton,
    QWidgetAction,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from domain.alertas_umbral import SupervisorAlertas
from domain.calidad_contacto import CalidadContacto
from domain.zonas_actividad import zona_de
from domain.ui_state import ConexionEstado, VitaBandUiState
from ui.coach_ia_widget import CoachIaWidget
from ui.modo_entrenador_widget import ModoEntrenadorWidget
from ui.modo_escritorio import ControladorModoEscritorio, PildoraVigilancia
from ui.susurrador_widget import TarjetaSusurro
from ui.panel_fisiologia_avanzada import PanelFisiologiaAvanzada
from ui.panel_planificacion import PanelEjecucion, PanelPlanificacion
from ui.confirmaciones import confirmar
from ui.dialogo_eliminar_cuenta import DialogoEliminarCuenta
from ui.dialogo_coherencia import DialogoCoherencia
from ui.dialogo_ortostatico import DialogoOrtostatico
from ui.dialogo_perfil import DialogoPerfil
from services import anonimizar as anonimizar_mod, ratio_pulso_resp as ratio_mod
from services.funciones_en_vivo import GeneradorPitidoCardiaco, OPCIONES_ZONA
from ui.grafica_acoplamiento import GraficaAcoplamiento
from ui import animations
from ui.animaciones_vitaband import AnimadorVitaBand, desplegar, suavizar_barra
from ui.indicador_piloto import IndicadorPiloto
from ui.mini_widget_pip import MiniWidgetPip
from ui.exportar_png import boton_png
from ui.modo_entrenamiento import DialogoEntrenamiento
from ui.vista_actividades import VistaActividades
from ui.vista_historial import VistaHistorialPeriodico
from viewmodel.vitaband_vm import VitaBandViewModel
from ui.tema_vitaband import (
    ALFA_REJILLA, BORDE_BOSQUE, CORAL_PULSO, ESMERALDA_ECG, ESMERALDA_BRILLO, TARJETA_PINO, TEXTO_MARFIL, TEXTO_SALVIA,
    configurar_pyqtgraph)

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

    def __init__(self, view_model: VitaBandViewModel, nombre_usuario: str = "", correo_usuario: str = ""):
        super().__init__()
        self.vm = view_model
        self._nombre_usuario = nombre_usuario
        view_model.nombre_usuario = nombre_usuario          # el Coach saluda por su nombre
        self._correo_usuario = correo_usuario
        self._modo_y_aplicado = None  # None = escala Y aún sin fijar
        self.alertas = SupervisorAlertas()
        self._alertas_activas: tuple = ()
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

        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        # Cabecera minimalista: identidad, indicador vivo de la banda y un único menú de cuenta y datos
        barra_top = QHBoxLayout()
        barra_top.setSpacing(12)
        self.lbl_titulo = QLabel("VitaBand · Banda Pectoral ECG")
        self.lbl_titulo.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {TEXTO_MARFIL};")
        self.lbl_punto_conexion = QLabel("●")
        self.lbl_punto_conexion.setStyleSheet(f"color: {TEXTO_SALVIA}; font-size: 16px;")
        self.lbl_conexion = QLabel()
        self.btn_conectar = QPushButton("Conectar")
        self.btn_desconectar = QPushButton("Desconectar")
        self.btn_sincronizar = QPushButton("Sincronizar ahora")
        self.btn_exportar_csv = QPushButton("Exportar historial (CSV)")
        self.btn_exportar_pdf = QPushButton("Exportar informe PDF")
        self.btn_backup = QPushButton("Exportar Backup (.zip)")
        self.btn_restaurar = QPushButton("Restaurar Backup (.zip)")
        self.btn_perfil = QPushButton("Perfil fisiológico")
        self.btn_eliminar_cuenta = QPushButton("Eliminar cuenta")
        self.lbl_usuario = QLabel(f"Usuario: {self._nombre_usuario}" if self._nombre_usuario else "")
        self.btn_cerrar_sesion = QPushButton("Cerrar sesión")
        self.chk_anonimizar = QCheckBox("Anonimizar datos personales")
        self.chk_anonimizar.setToolTip("Sustituye nombre y correo por un identificador SUJETO-xxxxxx en el PDF y el CSV")
        barra_top.addWidget(self.lbl_titulo)
        barra_top.addWidget(self.lbl_punto_conexion)
        barra_top.addWidget(self.lbl_conexion)
        self.pildora_estres = PildoraVigilancia()               # Modo Escritorio: visible solo si está activo
        barra_top.addWidget(self.pildora_estres)
        barra_top.addStretch()
        barra_top.addWidget(self.lbl_usuario)
        self.btn_menu_cuenta = QToolButton()
        self.btn_menu_cuenta.setText("Cuenta y datos ▾")
        self.btn_menu_cuenta.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu_cuenta = QMenu(self.btn_menu_cuenta)
        self.btn_menu_cuenta.setMenu(self.menu_cuenta)
        barra_top.addWidget(self.btn_menu_cuenta)
        layout.addLayout(barra_top)
        # Los botones existentes se conservan (mismos atributos y señales) pero viven dentro del menú
        self._acciones_ocultas = QWidget(central)
        self._acciones_ocultas.setVisible(False)
        for w in (self.btn_sincronizar, self.btn_exportar_csv, self.btn_exportar_pdf, self.btn_perfil, self.btn_backup,
                  self.btn_restaurar, self.btn_eliminar_cuenta, self.btn_cerrar_sesion, self.chk_anonimizar):
            w.setParent(self._acciones_ocultas)
        for boton, separador in ((self.btn_perfil, False), (self.btn_sincronizar, False), (self.btn_exportar_pdf, False),
                                 (self.btn_exportar_csv, False), (None, True), (self.btn_backup, False),
                                 (self.btn_restaurar, True), (self.btn_eliminar_cuenta, False),
                                 (self.btn_cerrar_sesion, False)):
            if boton is None:
                self.menu_cuenta.addSeparator()
                continue
            self.menu_cuenta.addAction(self._accion_de(boton, self.menu_cuenta))
            if separador:
                self.menu_cuenta.addSeparator()
        self.accion_anonimizar = QAction(self.chk_anonimizar.text(), self.menu_cuenta)
        self.accion_anonimizar.setCheckable(True)
        self.accion_anonimizar.toggled.connect(self.chk_anonimizar.setChecked)
        self.chk_anonimizar.toggled.connect(self.accion_anonimizar.setChecked)
        self.menu_cuenta.insertAction(self.menu_cuenta.actions()[4], self.accion_anonimizar)

        # Pestañas: monitorización en tiempo real e historial por fecha
        configurar_pyqtgraph()
        self.pestanas = QTabWidget()
        self.pestanas.addTab(self._construir_tiempo_real(), "Tiempo real")
        self.vista_historial = VistaHistorialPeriodico(self.vm)
        self.vista_actividades = VistaActividades(self.vm)
        me = self.vista_actividades.menu_exportar                  # PDF clínico, CSV y anonimización en el mismo menú
        me.addSeparator()
        for texto, boton in (("Informe PDF clínico", self.btn_exportar_pdf), ("Historial CSV", self.btn_exportar_csv)):
            a = QAction(texto, me)
            a.triggered.connect(lambda _=False, b=boton: b.click())
            me.addAction(a)
        a_pack = QAction("Exportar Coach Pack", me)
        a_pack.triggered.connect(self._exportar_coach_pack)
        me.addAction(a_pack)
        me.setStyleSheet(
            "QMenu { background:#0B1713; border:1px solid #264B3F; padding:4px; } "
            "QMenu::item { padding:8px 22px; color:#E7F5EF; } QMenu::item:selected { background:#264B3F; } "
            "QMenu::separator { height:1px; background:#264B3F; margin:4px 8px; } "
            "QMenu QPushButton { text-align:left; border:none; background:transparent; padding:4px 12px; color:#E7F5EF; } "
            "QMenu QPushButton:hover:enabled { background:#264B3F; } QMenu QPushButton:disabled { color:#6b8a7f; }")
        anon = QAction("Anonimizar datos personales (SHA-256)", me)
        anon.setCheckable(True)
        anon.toggled.connect(self.chk_anonimizar.setChecked)
        self.chk_anonimizar.toggled.connect(anon.setChecked)
        me.addAction(anon)
        self.pestanas.addTab(self.vista_historial, "Historial periódico")
        self.pestanas.addTab(self.vista_actividades, "Actividades")
        self.panel_fisiologia = PanelFisiologiaAvanzada(self.vm)
        self.panel_plan = PanelPlanificacion(self.vm)
        self.modo_entrenador = ModoEntrenadorWidget()
        self.pestanas.addTab(self.panel_fisiologia, "Análisis avanzado")
        self.pestanas.addTab(self.panel_plan, "Planificación")
        self.pestanas.addTab(self.modo_entrenador, "Modo Entrenador")
        self._vistas_balance = (self._fijar_balance_historial, self._fijar_balance_avanzado)
        self.panel_plan.entrenamiento_cargado.connect(self._cargar_entrenamiento)
        self.panel_plan.sesion_iniciada.connect(self._iniciar_sesion_planificada)
        self.cerrar_sesion_solicitada.connect(self.modo_entrenador.reiniciar)
        self.coach_ia = CoachIaWidget(self.vm)
        self.pestanas.addTab(self.coach_ia, "Coach IA")
        self.cerrar_sesion_solicitada.connect(self.coach_ia.reiniciar)
        self.coach_ia.accion_coherencia.connect(self._abrir_coherencia)
        self.coach_ia.plan_modificado.connect(self._refrescar_plan)
        self.tarjeta_susurro = TarjetaSusurro(self)
        self.vm.susurro.connect(self.tarjeta_susurro.mostrar)
        self.tarjeta_susurro.silenciado.connect(self.vm.susurrador.silenciar)
        self.vm.hrr_calculado.connect(self._hrr_medido)
        self.coach_ia.accion_plan_zona2.connect(self._agendar_zona2)
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
        self.btn_exportar_pdf.clicked.connect(self._exportar_pdf)
        self.btn_perfil.clicked.connect(self._editar_perfil)
        self.btn_backup.clicked.connect(self._exportar_backup)
        self.btn_restaurar.clicked.connect(self._restaurar_backup)
        self.btn_sincronizar.clicked.connect(self.vm.sincronizar)
        self.btn_eliminar_cuenta.clicked.connect(self._pedir_eliminar_cuenta)
        self.pestanas.currentChanged.connect(self._on_cambio_pestana)
        self.animador = AnimadorVitaBand(self)
        self.animador.instalar_pestanas()
        animations.decorate(self)
        self._sync_latidos()
        self.vm.latido.connect(self._on_latido_visual)

    @staticmethod
    def _accion_de(boton: QPushButton, padre) -> QAction:
        """Acción de menú que dispara el botón original (se conservan sus señales y sus tests)."""
        accion = QAction(boton.text(), padre)
        accion.triggered.connect(lambda _=False, b=boton: b.click())
        return accion

    @staticmethod
    def _tarjeta(*contenido, margen: int = 16) -> QFrame:
        """Tarjeta Verde Pino (card=\"true\") con estilo propio: el .qss global no define selectores por propiedad."""
        t = QFrame()
        t.setProperty("card", "true")
        t.setStyleSheet(f"QFrame[card=\"true\"] {{ background-color: {TARJETA_PINO}; border: 1px solid {BORDE_BOSQUE}; "
                        f"border-radius: 14px; }} QFrame[card=\"true\"] QLabel {{ background: transparent; border: none; }}")
        v = QVBoxLayout(t)
        v.setContentsMargins(margen, margen, margen, margen)
        v.setSpacing(4)
        for w in contenido:
            v.addWidget(w)
        return t

    @staticmethod
    def _accion_widget(padre, *widgets) -> QWidgetAction:
        """Acción de menú que aloja widgets existentes (combos, checks…) sin recrearlos."""
        cont = QWidget()
        f = QHBoxLayout(cont)
        f.setContentsMargins(10, 4, 10, 4)
        for w in widgets:
            f.addWidget(w)
        for w in widgets:
            for b in ([w] if isinstance(w, QPushButton) else []):
                b.clicked.connect(padre.close)
        a = QWidgetAction(padre)
        a.setDefaultWidget(cont)
        return a

    @Slot(object)
    def _iniciar_sesion_planificada(self, sesion) -> None:
        """«Iniciar ahora» desde Planificación: Tiempo Real con la sesión como objetivo del día (Susurrador en Vivo)."""
        self.vm.invalidar_zona_objetivo()
        if sesion.plan:
            from services.planificacion_entrenamiento import EntrenamientoEstructurado
            try:
                self._cargar_entrenamiento(EntrenamientoEstructurado.desde_dict(sesion.plan))
            except Exception:
                self.pestanas.setCurrentIndex(0)
        else:
            self.pestanas.setCurrentIndex(0)
        self.statusBar().showMessage(f"Objetivo de hoy: {sesion.nombre} · {sesion.minutos:g} min", 6000)

    def _cargar_entrenamiento(self, entrenamiento) -> None:
        self.panel_ejecucion.setVisible(True)
        self.panel_ejecucion.cargar(entrenamiento)
        self.pestanas.setCurrentIndex(0)

    def _construir_tiempo_real(self) -> QWidget:
        pagina = QWidget()
        layout = QVBoxLayout(pagina)

        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        # Nivel 1 — Cockpit limpio: 3 tarjetas KPI (BPM, RPM + ratio, Zona actual) y controles esenciales de sesión
        fila_metricas = QHBoxLayout()
        fila_metricas.setSpacing(14)
        self.lbl_bpm = QLabel()
        self.lbl_rpm = QLabel()
        self.lbl_temp = QLabel()
        self.lbl_actividad = QLabel()
        self.lbl_zona_actual = QLabel("Zona: —")
        for lbl in (self.lbl_bpm, self.lbl_rpm):
            lbl.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {TEXTO_MARFIL};")
        self.lbl_zona_actual.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {ESMERALDA_BRILLO};")
        for lbl in (self.lbl_temp, self.lbl_actividad):
            lbl.setStyleSheet(f"font-size: 13px; color: {TEXTO_SALVIA};")
        self.lbl_ratio = QLabel("Pulso/respiración: N/D")
        self.lbl_ratio.setStyleSheet(f"font-size: 13px; color: {TEXTO_SALVIA};")
        self.tarjeta_bpm = self._tarjeta(self.lbl_bpm)
        self.tarjeta_rpm = self._tarjeta(self.lbl_rpm, self.lbl_ratio)
        self.tarjeta_zona = self._tarjeta(self.lbl_zona_actual, self.lbl_actividad, self.lbl_temp)
        for t in (self.tarjeta_bpm, self.tarjeta_rpm, self.tarjeta_zona):
            fila_metricas.addWidget(t, 1)
        layout.addLayout(fila_metricas)

        # Alertas por umbral (Zona 5, temperatura, pérdida de contacto)
        self.lbl_alerta = QLabel()
        self.lbl_alerta.setStyleSheet(
            "background:#b00020; color:#ffffff; font-size: 18px; font-weight: bold; padding: 8px; "
            "border: 3px solid #ff5252; border-radius: 6px;")
        self.lbl_alerta.setVisible(False)
        layout.addWidget(self.lbl_alerta)

        # Banner de aviso experimental
        self.lbl_aviso = QLabel()
        self.lbl_aviso.setStyleSheet("font-size: 15px; padding: 6px;")
        layout.addWidget(self.lbl_aviso)

        # Selector ECG filtrada / cruda (RF-10)
        self.chk_ecg_crudo = QCheckBox("Mostrar señal ECG cruda (sin filtro Butterworth)")
        # Sesión en directo: vueltas, test ortostático, tiempo efectivo y auto-pausa
        fila_sesion = QHBoxLayout()
        self.btn_lap = QPushButton("Marcar vuelta (Lap)")
        self.btn_lap.setEnabled(False)
        self.btn_lap.clicked.connect(self._marcar_vuelta)
        self.btn_finalizar = QPushButton("Finalizar sesión")
        self.btn_finalizar.setToolTip("Termina el esfuerzo y mide cuánto baja tu pulso en 1 y 2 minutos (HRR)")
        self.btn_finalizar.setEnabled(False)
        self.btn_finalizar.clicked.connect(self._finalizar_sesion)
        self.btn_ortostatico = QPushButton("Test Ortostático (3 min)")
        self.btn_ortostatico.clicked.connect(self._abrir_ortostatico)
        self.lbl_vuelta = QLabel()
        self.lbl_vuelta.setStyleSheet("font-weight: bold; color: #1e8e3e;")
        self.lbl_sesion = QLabel("Sin sesión en directo")
        self.lbl_pausa = QLabel()
        self.lbl_pausa.setStyleSheet("font-weight: bold; color: #ffffff; background:#e67e22; padding: 2px 8px;")
        self.lbl_pausa.setVisible(False)
        self.btn_coherencia = QPushButton("Coherencia Cardíaca")
        self.btn_coherencia.clicked.connect(self._abrir_coherencia)
        self.btn_conectar.setStyleSheet(f"background-color: #1B4D3E; border: 1px solid #10B981; color: {TEXTO_MARFIL};")
        for w in (self.btn_conectar, self.btn_desconectar, self.btn_lap, self.btn_finalizar, self.lbl_vuelta, self.lbl_pausa):
            fila_sesion.addWidget(w)
        fila_sesion.addStretch()
        fila_sesion.addWidget(self.lbl_sesion)
        layout.addLayout(fila_sesion)

        self.panel_ejecucion = PanelEjecucion(self.vm)          # entrenamiento estructurado en vivo
        layout.addWidget(self.panel_ejecucion)
        self.panel_ejecucion.setVisible(False)                  # aparece al cargar un entrenamiento

        # Cociente pulso/respiración y Modo Escritorio (pausa activa por estrés)
        fila_extra = QHBoxLayout()
        self.lbl_alerta_ratio = QLabel()
        self.lbl_alerta_ratio.setStyleSheet("color: #7a4b00; background:#ffe8b0; padding: 2px 8px;")
        self.lbl_alerta_ratio.setWordWrap(True)
        self.lbl_alerta_ratio.setVisible(False)
        self.chk_escritorio = QCheckBox("Modo Escritorio")
        self.chk_escritorio.setToolTip("Avisa si en reposo baja tu RMSSD y sube tu respiración de forma sostenida")
        self.spin_escritorio = QSpinBox()
        self.spin_escritorio.setRange(10, 120)
        self.spin_escritorio.setValue(20)
        self.spin_escritorio.setSuffix(" min")
        self.controlador_escritorio = ControladorModoEscritorio(self, self.vm, self.pildora_estres,
                                                                balance=self.vm.balance_mental())
        self.chk_escritorio.toggled.connect(self._cambio_escritorio)
        self.spin_escritorio.valueChanged.connect(self._cambio_escritorio)
        self.lbl_estres = QLabel()
        self.lbl_estres.setWordWrap(True)
        self.lbl_estres.setStyleSheet("color: #14532d; background:#d7f0dd; padding: 2px 8px;")
        self.btn_estres_coherencia = QPushButton("Abrir Coherencia Cardíaca")
        self.btn_estres_coherencia.clicked.connect(self._abrir_coherencia)
        self.lbl_estres.setVisible(False)
        self.btn_estres_coherencia.setVisible(False)
        fila_extra.addWidget(self.lbl_alerta_ratio, 1)
        layout.addLayout(fila_extra)
        fila_estres = QHBoxLayout()
        fila_estres.addWidget(self.lbl_estres, 1)
        fila_estres.addWidget(self.btn_estres_coherencia)
        layout.addLayout(fila_estres)
        self.vm.aviso_estres.connect(self._mostrar_aviso_estres)

        # Monitor acústico de latido y Mini-Widget PiP
        fila_latido = QHBoxLayout()
        self.pitido = GeneradorPitidoCardiaco(0.7, silenciado=True)
        self.btn_latido = QPushButton("Sonido de latido: silenciado")
        self.btn_latido.setCheckable(True)
        self.btn_latido.setToolTip("Un pitido breve con cada latido (pico R) detectado por la banda pectoral")
        self.slider_volumen = QSlider(Qt.Orientation.Horizontal)
        self.slider_volumen.setRange(0, 100)
        self.slider_volumen.setValue(70)
        self.slider_volumen.setMaximumWidth(160)
        self.lbl_volumen = QLabel("Volumen 70 %")
        self.btn_latido.toggled.connect(self._alternar_latido)
        self.slider_volumen.valueChanged.connect(self._cambiar_volumen)
        self.vm.latido.connect(self.pitido.pitar)
        self.btn_pip = QPushButton("Mini-Widget PiP")
        self.btn_pip.setToolTip("Minimiza esta ventana y muestra un widget flotante con BPM, RPM y zona")
        self.btn_pip.clicked.connect(self._abrir_pip)
        layout.addLayout(fila_latido)                           # Nivel 2: se rellena al final del método

        # Sesión Fantasma: compite contra una sesión guardada, segundo a segundo
        fila_fantasma = QHBoxLayout()
        self.chk_fantasma = QCheckBox("Modo Fantasma (competir contra sesión previa)")
        self.chk_fantasma.toggled.connect(self._alternar_fantasma)
        fila_fantasma.addWidget(self.chk_fantasma)
        self.combo_fantasma = QComboBox()
        self.combo_fantasma.setMinimumWidth(200)
        self.combo_fantasma.currentIndexChanged.connect(self._elegir_fantasma)
        self.lbl_fantasma = QLabel("Elige una sesión guardada para competir contra ella.")
        self.barra_fantasma = QProgressBar()
        self.barra_fantasma.setRange(0, 100)
        self.barra_fantasma.setValue(50)
        self.barra_fantasma.setTextVisible(False)
        self.barra_fantasma.setMaximumWidth(180)
        self.barra_fantasma.setToolTip("Eficiencia cardíaca: a la derecha, menos pulso que tu sesión fantasma")
        fila_fantasma.addWidget(self.combo_fantasma)
        self._cont_fantasma = QWidget()
        self._cont_fantasma.setLayout(fila_fantasma)
        self.vm.historial_actualizado.connect(self._recargar_fantasmas)
        self._recargar_fantasmas()

        # Piloto automático de zona objetivo
        fila_piloto = QHBoxLayout()
        fila_piloto.addWidget(QLabel("Zona objetivo"))
        self.combo_zona = QComboBox()
        self.combo_zona.addItems(OPCIONES_ZONA)
        self.combo_zona.currentIndexChanged.connect(
            lambda i: self.vm.set_zona_objetivo(None if i == 0 else i - 1))
        self.vm.zona_objetivo_cambiada.connect(self._sincronizar_zona)
        self.indicador_piloto = IndicadorPiloto()
        fila_piloto.addWidget(self.combo_zona)
        self._cont_piloto = QWidget()
        self._cont_piloto.setLayout(fila_piloto)
        self._timer_vuelta = QTimer(self)
        self._timer_vuelta.setSingleShot(True)
        self._timer_vuelta.setInterval(2500)
        self._timer_vuelta.timeout.connect(lambda: self.lbl_vuelta.setText(""))

        self.lbl_calidad = QLabel()                    # insignia de calidad de contacto de la banda
        self._calidad_pintada = None
        fila_ecg = QHBoxLayout()
        fila_ecg.addWidget(self.chk_ecg_crudo)
        fila_ecg.addStretch()
        self.btn_entrenamiento = QPushButton("Modo Entrenamiento")
        self.btn_entrenamiento.setToolTip("BPM, RPM y zona cardíaca a pantalla completa (Esc para salir)")
        self.btn_entrenamiento.clicked.connect(self._abrir_modo_entrenamiento)
        self.btn_sonido = QPushButton("Silenciar sonido")
        self.btn_sonido.setToolTip("Silencia o activa el aviso sonoro de las alertas (el banner sigue apareciendo)")
        self.btn_sonido.clicked.connect(self._alternar_sonido)
        fila_ecg.addWidget(self.lbl_calidad)
        layout.addLayout(fila_ecg)

        # Gráfica PyQtGraph de alto rendimiento (100 Hz)
        self.plot_widget = pg.PlotWidget(title="Señal ECG (100 Hz)")
        self.plot_widget.setLabel("left", "Amplitud (ADC)")
        self.plot_widget.setLabel("bottom", "Tiempo", units="s")
        self.plot_widget.showGrid(x=True, y=True, alpha=ALFA_REJILLA)
        self.curva_ecg = self.plot_widget.plot(pen=pg.mkPen(ESMERALDA_ECG, width=2))
        layout.addWidget(self.plot_widget, 10)                 # protagonista: ECG en vivo (100 Hz)
        fila_ecg.addWidget(boton_png(self.plot_widget, "vitaband_ecg"))
        self.grafica_acoplamiento = GraficaAcoplamiento()
        # Nivel 3 — panel colapsable bajo demanda (oculto por defecto)
        self.btn_acoplamiento = QPushButton("Ver Acoplamiento Pulso-Respiración ▾")
        self.btn_acoplamiento.setCheckable(True)
        self.panel_acoplamiento = QFrame()
        v_acop = QVBoxLayout(self.panel_acoplamiento)
        v_acop.setContentsMargins(0, 0, 0, 0)
        v_acop.addWidget(self.grafica_acoplamiento)
        self.panel_acoplamiento.setVisible(False)
        self.btn_acoplamiento.toggled.connect(self._alternar_acoplamiento)
        layout.addWidget(self.btn_acoplamiento)
        layout.addWidget(self.panel_acoplamiento)

        # Nivel 2 — barra compacta de una fila: dos menús desplegables + audio de latido + feedback del piloto/fantasma
        self.btn_menu_entrenamiento = QToolButton()
        self.btn_menu_entrenamiento.setText("Entrenamiento ▾")
        self.btn_menu_pantalla = QToolButton()
        self.btn_menu_pantalla.setText("Modos de Pantalla ▾")
        self.menu_entrenamiento, self.menu_pantalla = QMenu(self.btn_menu_entrenamiento), QMenu(self.btn_menu_pantalla)
        for boton, menu in ((self.btn_menu_entrenamiento, self.menu_entrenamiento), (self.btn_menu_pantalla, self.menu_pantalla)):
            boton.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            boton.setMenu(menu)
        me = self.menu_entrenamiento
        me.addAction(self._accion_widget(me, self._cont_piloto))
        me.addAction(self._accion_widget(me, self._cont_fantasma))
        me.addSeparator()
        me.addAction(self._accion_widget(me, self.btn_coherencia))
        me.addAction(self._accion_widget(me, self.btn_ortostatico))
        mp = self.menu_pantalla
        mp.addAction(self._accion_widget(mp, self.btn_pip))
        mp.addAction(self._accion_widget(mp, self.btn_entrenamiento))
        mp.addAction(self._accion_widget(mp, self.chk_escritorio, self.spin_escritorio))
        self.btn_demo_pausa = QPushButton("Probar Pausa por Estrés (Demo)")
        self.btn_demo_pausa.clicked.connect(self.controlador_escritorio.simular_alerta)
        mp.addAction(self._accion_widget(mp, self.btn_demo_pausa))
        mp.addSeparator()
        mp.addAction(self._accion_widget(mp, self.btn_sonido))
        self.lbl_fantasma.setWordWrap(True)
        self.lbl_fantasma.setMinimumWidth(260)
        self.lbl_fantasma.setMaximumWidth(420)
        self.barra_fantasma.setMaximumWidth(110)
        self.slider_volumen.setMaximumWidth(110)
        self.chk_demo = QCheckBox("Modo Demo")
        self.chk_demo.setToolTip("Simula la banda pectoral (ECG a 100 Hz) para presentaciones; no guarda nada en el historial")
        self.combo_escenario_demo = QComboBox()
        self.combo_escenario_demo.addItems(["Reposo", "Esfuerzo Z3", "Estrés Escritorio"])
        self.btn_ejemplo = QPushButton("Datos de ejemplo")
        self.btn_ejemplo.setToolTip("Carga ~12 semanas de entrenamientos SIMULADOS para ver todas las gráficas y el Coach")
        self.btn_ejemplo.setAutoDefault(False)
        self.btn_ejemplo.clicked.connect(self._cargar_ejemplo)
        self.chk_demo.toggled.connect(self._alternar_demo)
        self.combo_escenario_demo.currentTextChanged.connect(self.vm.cambiar_escenario_demo)
        self.vm.state_changed.connect(self._sincronizar_demo)
        for w in (self.btn_menu_entrenamiento, self.btn_menu_pantalla, self.btn_latido, self.slider_volumen,
                  self.lbl_volumen, self.chk_demo, self.combo_escenario_demo, self.btn_ejemplo):
            fila_latido.addWidget(w)
        fila_latido.addStretch()
        for w in (self.indicador_piloto, self.lbl_fantasma, self.barra_fantasma):
            fila_latido.addWidget(w)
        fila_latido.setSpacing(12)
        return pagina

    @Slot(bool)
    def _alternar_acoplamiento(self, visible: bool) -> None:
        desplegar(self.panel_acoplamiento, visible)
        self.btn_acoplamiento.setText("Ocultar Acoplamiento Pulso-Respiración ▴" if visible
                                      else "Ver Acoplamiento Pulso-Respiración ▾")

    @Slot()
    def _abrir_modo_entrenamiento(self) -> None:
        self.modo_entrenamiento = DialogoEntrenamiento(self.vm, fc_max=self.vm.fc_max(), parent=self)
        self.modo_entrenamiento.btn_sonido.clicked.connect(self._alternar_sonido)
        self.modo_entrenamiento.vuelta_solicitada.connect(self._marcar_vuelta)
        self.modo_entrenamiento.mostrar_alertas(self._alertas_activas, self.alertas.silenciado)
        self.modo_entrenamiento.abrir()

    @Slot()
    def _alternar_sonido(self) -> None:
        self.alertas.silenciado = not self.alertas.silenciado
        self._pintar_alertas(self._alertas_activas)

    def _pintar_alertas(self, activas) -> None:
        self._alertas_activas = activas
        self.btn_sonido.setText("Activar sonido" if self.alertas.silenciado else "Silenciar sonido")
        self.lbl_alerta.setText("⚠ " + "  ·  ".join(a.texto for a in activas))
        self.lbl_alerta.setVisible(bool(activas))
        dialogo = getattr(self, "modo_entrenamiento", None)
        if dialogo is not None and dialogo.isVisible():
            dialogo.mostrar_alertas(activas, self.alertas.silenciado)

    def _sync_latidos(self) -> None:
        """Detecta R solo si alguien escucha: sonido activado o animación visible en Tiempo real conectado."""
        visual = self.pestanas.currentIndex() == 0 and self.vm.state.conexionEstado == ConexionEstado.CONECTADO
        self.vm.activar_latidos(visual or not self.pitido.silenciado)

    @Slot()
    def _on_latido_visual(self) -> None:
        if self.pestanas.currentIndex() == 0:
            animations.pulse_on_beat(self.lbl_bpm)

    @Slot(int)
    def _on_cambio_pestana(self, indice: int) -> None:
        self._sync_latidos()
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
    @Slot()
    def _exportar_coach_pack(self) -> None:
        from datetime import date
        from services import modo_entrenador as me_
        anonimo = self.chk_anonimizar.isChecked()
        sujeto = anonimizar_mod.seudonimo(self._correo_usuario, self._nombre_usuario) if anonimo else ""
        etiqueta = "".join(c for c in (sujeto or self._nombre_usuario or "Atleta") if c.isalnum() or c in "-_") or "Atleta"
        sugerido = f"VitaBand_CoachPack_{etiqueta}_{date.today().isoformat()}{me_.EXTENSION}"
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar Coach Pack", sugerido, "Coach Pack (*.vbcoach)")
        if not ruta:
            return
        try:
            me_.exportar_coach_pack_completo(self.vm.repositorio, ruta, self._nombre_usuario, sujeto)
        except Exception as exc:
            QMessageBox.warning(self, "No se pudo exportar", f"Error al exportar el Coach Pack:\n{exc}")
            return
        animations.show_toast(self, "Coach Pack listo para enviar al entrenador")

    def _exportar_csv(self) -> None:
        sugerido = f"vitaband_historial_{date.today():%Y-%m-%d}.csv"
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Exportar historial a CSV", sugerido, "Archivos CSV (*.csv)"
        )
        if not ruta:
            return

        try:
            sujeto = (anonimizar_mod.seudonimo(self._correo_usuario, self._nombre_usuario)
                      if self.chk_anonimizar.isChecked() else None)
            filas = self.vm.exportar_csv(ruta, sujeto=sujeto)
        except Exception as exc:
            QMessageBox.warning(self, "No se pudo exportar", f"Error al exportar el historial:\n{exc}")
            return

        animations.show_toast(self, f"CSV exportado · {filas} registros")

    def _texto_sesion(self) -> str:
        s = self.vm.sesion_directo
        if not s.activa:
            return "Sin sesión en directo"
        t = int(s.tiempo_efectivo_s)
        partes = [f"Sesión {t // 60}:{t % 60:02d} efectivos"]
        if s.bpm_medio:
            partes.append(f"FC media {s.bpm_medio:.0f}")
        if s.rpm_medio:
            partes.append(f"FR media {s.rpm_medio:.0f}")
        kcal = self.vm.kcal_sesion_directo()
        if kcal is not None:
            partes.append(f"≈ {kcal:.0f} kcal")
        return " · ".join(partes)

    def _pintar_sesion(self) -> None:
        s = self.vm.sesion_directo
        texto = self._texto_sesion()
        if texto != self.lbl_sesion.text():
            self.lbl_sesion.setText(texto)
        self.btn_lap.setEnabled(s.activa)
        self.btn_finalizar.setEnabled(s.activa)
        pausa = s.estado
        self.lbl_pausa.setText(pausa)
        self.lbl_pausa.setVisible(bool(pausa))
        dialogo = getattr(self, "modo_entrenamiento", None)
        if dialogo is not None and dialogo.isVisible():
            dialogo.mostrar_sesion(f"{texto}  ·  {pausa}" if pausa else texto)

    @Slot()
    def _marcar_vuelta(self) -> None:
        n = self.vm.marcar_vuelta()
        texto = f"Vuelta #{n} marcada" if n is not None else "Conecta la banda para marcar vueltas"
        self.lbl_vuelta.setText(texto)
        self._timer_vuelta.start()
        dialogo = getattr(self, "modo_entrenamiento", None)
        if dialogo is not None and dialogo.isVisible():
            dialogo.mostrar_vuelta(texto)

    @Slot(bool)
    def _alternar_latido(self, activo: bool) -> None:
        self.pitido.silenciado = not activo
        self._sync_latidos()
        self.btn_latido.setText("Sonido de latido: activado" if activo else "Sonido de latido: silenciado")

    @Slot(int)
    def _cambiar_volumen(self, valor: int) -> None:
        self.pitido.volumen = valor / 100.0
        self.lbl_volumen.setText(f"Volumen {valor} %")

    @Slot()
    def _abrir_pip(self) -> None:
        if getattr(self, "pip", None) is None:
            self.pip = MiniWidgetPip(self.vm)
            self.pip.restaurar_solicitado.connect(self._restaurar_desde_pip)
        self.pip.mostrar_sincronizado()
        self._sync_latidos()
        self.showMinimized()

    @Slot()
    def _restaurar_desde_pip(self) -> None:
        self.pip.ocultar()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    @Slot()
    def _recargar_fantasmas(self) -> None:
        actual = self.combo_fantasma.currentData()
        self.combo_fantasma.blockSignals(True)
        self.combo_fantasma.clear()
        self.combo_fantasma.addItem("Sin fantasma", None)
        for aid, texto in self.vm.fantasmas_disponibles():
            self.combo_fantasma.addItem(texto, aid)
        i = self.combo_fantasma.findData(actual)
        self.combo_fantasma.setCurrentIndex(max(i, 0))
        self.combo_fantasma.blockSignals(False)
        if actual is not None and i < 0:
            self.vm.seleccionar_fantasma(None)

    @Slot()
    def _cargar_ejemplo(self) -> None:
        r = QMessageBox.question(
            self, "Datos de ejemplo",
            "Se añadirán ~12 semanas de entrenamientos SIMULADOS al historial de esta cuenta.\n"
            "Úsalo en una cuenta de prueba: no son datos reales. ¿Continuar?")
        if r != QMessageBox.StandardButton.Yes:
            return
        resumen = self.vm.cargar_datos_ejemplo()
        self.statusBar().showMessage(
            f"Datos de ejemplo cargados: {resumen['actividades']} actividades nuevas" if resumen
            else "No se pudieron cargar los datos de ejemplo", 8000)

    @Slot(bool)
    def _alternar_demo(self, activo: bool) -> None:
        if activo and not self.vm.iniciar_demo(self.combo_escenario_demo.currentText()):
            self.chk_demo.blockSignals(True)
            self.chk_demo.setChecked(False)
            self.chk_demo.blockSignals(False)
            self.statusBar().showMessage("Hay una banda física conectada: pulsa Desconectar para usar el Modo Demo", 6000)
        elif not activo:
            self.vm.detener_demo()

    @Slot(object)
    def _sincronizar_demo(self, _estado) -> None:
        if self.chk_demo.isChecked() and not self.vm.modo_demo:
            self.chk_demo.blockSignals(True)
            self.chk_demo.setChecked(False)
            self.chk_demo.blockSignals(False)

    @Slot(bool)
    def _alternar_fantasma(self, activo: bool) -> None:
        """El interruptor nunca parece muerto: sin sesión elegida avisa y enfoca el selector."""
        if not activo:
            self.combo_fantasma.setCurrentIndex(0)
            return
        if self.combo_fantasma.currentData() is None:
            if self.combo_fantasma.count() <= 1:
                self.lbl_fantasma.setText("Aún no hay sesiones guardadas con pulso para competir contra ellas.")
                self.chk_fantasma.blockSignals(True)
                self.chk_fantasma.setChecked(False)
                self.chk_fantasma.blockSignals(False)
            else:
                self.lbl_fantasma.setText("Elige primero una sesión previa en el selector para competir contra ella.")
                self.combo_fantasma.setFocus()
            self.statusBar().showMessage(self.lbl_fantasma.text(), 5000)
        elif not self.vm.sesion_directo.activa:
            self.lbl_fantasma.setText("Listo: la comparación empezará cuando inicies una sesión en directo.")

    @Slot(int)
    def _elegir_fantasma(self, _i: int) -> None:
        aid = self.combo_fantasma.currentData()
        self.chk_fantasma.blockSignals(True)
        self.chk_fantasma.setChecked(aid is not None)
        self.chk_fantasma.blockSignals(False)
        if not self.vm.seleccionar_fantasma(aid):
            self.lbl_fantasma.setText("Esa sesión no tiene pulso suficiente para usarla como fantasma.")
            self.combo_fantasma.blockSignals(True)
            self.combo_fantasma.setCurrentIndex(0)
            self.combo_fantasma.blockSignals(False)
        elif aid is None:
            self.lbl_fantasma.setText("Elige una sesión guardada para competir contra ella.")
            self.barra_fantasma.setValue(50)

    @Slot(object)
    def _sincronizar_zona(self, zona) -> None:
        self.combo_zona.blockSignals(True)
        self.combo_zona.setCurrentIndex(0 if zona is None else zona + 1)
        self.combo_zona.blockSignals(False)
        self._pintar_en_vivo()

    def _pintar_en_vivo(self) -> None:
        from ui.modo_entrenamiento import numero
        st = self.vm.state
        conectado = st.conexionEstado == ConexionEstado.CONECTADO
        bpm = numero(st.bpmTexto) if conectado else None
        self.indicador_piloto.mostrar(self.vm.evaluar_piloto(bpm), bpm, self.vm.fc_max())
        if self.vm.fantasma.activo:
            c = self.vm.comparacion_fantasma()
            if c is not None:
                self.lbl_fantasma.setText(c.texto)
                suavizar_barra(self.barra_fantasma, int(max(0, min(100, 50 - c.delta * 50 / 15))))
                self.barra_fantasma.setStyleSheet(f"QProgressBar::chunk {{ background:{c.color}; }}")
            elif self.vm.fantasma.terminado(self.vm.tiempo_sesion_s()):
                self.lbl_fantasma.setText("Tu sesión fantasma ya terminó.")
            elif conectado:
                self.lbl_fantasma.setText("Comparando…")
            else:
                self.lbl_fantasma.setText("Conecta la banda para competir contra tu sesión fantasma.")
        self.grafica_acoplamiento.mostrar(self.vm.acoplamiento.ondas(), self.vm.acoplamiento.resultado())

    @Slot()
    def _abrir_coherencia(self) -> None:
        self.lbl_estres.setVisible(False)
        self.btn_estres_coherencia.setVisible(False)
        self.dialogo_coherencia = DialogoCoherencia(self.vm, parent=self)
        self.dialogo_coherencia.show()

    @Slot()
    def _finalizar_sesion(self) -> None:
        if self.vm.finalizar_sesion():
            self.statusBar().showMessage("Sesión finalizada · midiendo tu recuperación (2 min). Quédate quieto y respira.", 8000)
        else:
            self.statusBar().showMessage("Aún no hay suficientes datos de pulso para medir la recuperación.", 5000)

    @Slot(object)
    def _hrr_medido(self, h) -> None:
        self.statusBar().showMessage("Recuperación medida: " + h.texto(sencillo=False), 15000)

    @Slot()
    def _refrescar_plan(self) -> None:
        self.vm.invalidar_zona_objetivo()
        if getattr(self.panel_plan, "_construido", False):
            try:
                self.panel_plan.actualizar()
            except Exception:
                pass

    @Slot()
    def _agendar_zona2(self) -> None:
        """Acción del Coach IA: añade hoy una sesión de 40 min en Zona 2 al calendario de Planificación."""
        if self.vm.repositorio is None:
            return
        from services.planificacion_entrenamiento import GestorCalendarioPlanificado
        if GestorCalendarioPlanificado(self.vm.repositorio).agendar_unica(date.today(), "Zona 2 (Coach IA)", 40) is None:
            self.statusBar().showMessage("Esa sesión de Zona 2 ya estaba en el plan de hoy", 5000)
            return
        if getattr(self.panel_plan, "_construido", False):
            try:
                self.panel_plan.actualizar()
            except Exception:
                pass
        self.vm.invalidar_zona_objetivo()
        self.statusBar().showMessage("Sesión de 40 min en Zona 2 añadida a Planificación", 5000)
        animations.show_toast(self, "Añadido al plan de hoy")

    def _fijar_balance_historial(self, b) -> None:
        self.vista_historial.resumen_balance.fijar(b)

    def _fijar_balance_avanzado(self, b) -> None:
        if getattr(self.panel_fisiologia, "_construido", False):
            self.panel_fisiologia.resumen_balance.fijar(b)

    def _cambio_escritorio(self, *_args) -> None:
        self.controlador_escritorio.fijar_activo(self.chk_escritorio.isChecked())
        self.vm.configurar_modo_escritorio(self.chk_escritorio.isChecked(), self.spin_escritorio.value())
        if not self.chk_escritorio.isChecked():
            self.lbl_estres.setVisible(False)
            self.btn_estres_coherencia.setVisible(False)

    @Slot(str)
    def _mostrar_aviso_estres(self, texto: str) -> None:
        self.lbl_estres.setText(texto)
        self.lbl_estres.setVisible(True)
        self.btn_estres_coherencia.setVisible(True)

    def _pintar_ratio(self) -> None:
        r, alerta = self.vm.ratio_directo()
        estado = ratio_mod.estado(r)
        self.lbl_ratio.setText(f"Pulso/respiración: {ratio_mod.texto_ratio(r)}" + (f" ({estado}; óptimo ≈ 4:1)" if estado else ""))
        self.lbl_alerta_ratio.setText(ratio_mod.TEXTO_ALERTA)
        self.lbl_alerta_ratio.setVisible(alerta)

    @Slot()
    def _abrir_ortostatico(self) -> None:
        self.dialogo_ortostatico = DialogoOrtostatico(self.vm, parent=self)
        self.dialogo_ortostatico.show()

    @Slot()
    def _editar_perfil(self) -> None:
        dialogo = DialogoPerfil(self.vm.perfil(), self)
        if dialogo.exec():
            try:
                self.vm.guardar_perfil(dialogo.perfil())
            except Exception as exc:
                QMessageBox.warning(self, "No se pudo guardar", str(exc))

    @Slot()
    def _exportar_backup(self) -> None:
        sugerido = f"vitaband_backup_{date.today():%Y-%m-%d}.zip"
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar copia de seguridad", sugerido, "Archivos ZIP (*.zip)")
        if not ruta:
            return
        if not ruta.lower().endswith(".zip"):
            ruta += ".zip"
        try:
            self.vm.exportar_backup(ruta)
        except Exception as exc:
            QMessageBox.warning(self, "No se pudo exportar", f"Error al crear la copia:\n{exc}")
            return
        QMessageBox.information(
            self, "Copia creada",
            f"Copia de seguridad guardada en:\n{ruta}\n\nIncluye toda la base de datos local, también las "
            "cuentas (contraseñas con hash y claves de verificación en dos pasos): guárdala en un sitio seguro.")

    @Slot()
    def _restaurar_backup(self) -> None:
        ruta, _ = QFileDialog.getOpenFileName(self, "Restaurar copia de seguridad", "", "Archivos ZIP (*.zip)")
        if not ruta:
            return
        if not confirmar(
            self, "Restaurar copia de seguridad",
            "Se sustituirá TODA la base de datos actual por la de la copia (historial, actividades y cuentas).\n"
            "Antes se guarda una copia de seguridad de la actual (.bak) junto a la base de datos.\n"
            "Esta acción no se puede deshacer desde la aplicación.",
            "Restaurar",
        ):
            return
        try:
            bak = self.vm.restaurar_backup(ruta)
        except Exception as exc:
            QMessageBox.warning(self, "No se pudo restaurar", f"No se ha cambiado nada:\n{exc}")
            return
        self.vista_historial.actualizar()
        self.vista_actividades.actualizar()
        QMessageBox.information(
            self, "Copia restaurada",
            "Copia restaurada." + (f"\nLa base de datos anterior se guardó en:\n{bak}" if bak else ""))

    @Slot()
    def _exportar_pdf(self) -> None:
        """Informe PDF del rango elegido en la pestaña Historial periódico."""
        desde, hasta = self.vista_historial.selector.rango_ts()
        sugerido = f"vitaband_informe_{date.today():%Y-%m-%d}.pdf"
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Exportar informe PDF", sugerido, "Archivos PDF (*.pdf)")
        if not ruta:
            return
        if not ruta.lower().endswith(".pdf"):
            ruta += ".pdf"
        try:
            self.vm.exportar_pdf(ruta, desde, hasta, self._nombre_usuario, self._correo_usuario,
                                 self.chk_anonimizar.isChecked())
        except Exception as exc:
            QMessageBox.warning(self, "No se pudo exportar", f"Error al generar el informe:\n{exc}")
            return
        animations.show_toast(self, "Informe PDF generado")

    def _pintar_calidad(self, calidad: CalidadContacto, enlace: bool) -> None:
        """Verde: óptimo · ámbar: ruido · rojo: sin señal con enlace · gris: sin enlace."""
        if calidad == CalidadContacto.OPTIMO:
            fondo, texto = "#d7f0dd", "#14532d"
            ayuda = "El ECG es estable y está dentro del rango normal."
        elif calidad == CalidadContacto.RUIDO:
            fondo, texto = "#ffe8b0", "#7a4b00"
            ayuda = ("Mientras haya ruido, el pulso y los avisos pueden no ser fiables: "
                     "un artefacto de movimiento no es una taquicardia ni una arritmia.")
        elif enlace:
            fondo, texto = "#f8d4d4", "#7f1d1d"
            ayuda = "Hay enlace pero la señal ECG es plana o no llega: revisa que la banda toque la piel."
        else:
            fondo, texto = "#e3e3e3", "#444444"
            ayuda = "Sin enlace con la banda pectoral."
        clave = (calidad, fondo)
        if clave == self._calidad_pintada:
            return                                    # el estado se emite a ~33 Hz: no repintar sin cambios
        self._calidad_pintada = clave
        self.lbl_calidad.setText(calidad.value)
        self.lbl_calidad.setToolTip(ayuda)
        self.lbl_calidad.setStyleSheet(
            f"background:{fondo}; color:{texto}; border-radius:9px; padding:3px 10px; font-weight:bold;")

    @Slot(VitaBandUiState)
    def render(self, state: VitaBandUiState) -> None:
        # 1. Estado de conexión y habilitación de controles
        conectado = state.conexionEstado == ConexionEstado.CONECTADO
        calibrando = state.conexionEstado == ConexionEstado.CALIBRANDO
        en_curso = conectado or calibrando or state.conexionEstado == ConexionEstado.CONECTANDO

        self._sync_latidos()
        demo = self.vm.demo_active
        self.lbl_conexion.setText("Estado: DEMO (simulador)" if demo else f"Estado: {state.conexionEstado.value}")
        self.chk_demo.setText("● Demo activo" if demo else "Modo Demo")
        self.chk_demo.setStyleSheet(f"color: {ESMERALDA_ECG}; font-weight: 600;" if demo else "")
        if self.chk_demo.isChecked() != demo:
            self.chk_demo.blockSignals(True)
            self.chk_demo.setChecked(demo)
            self.chk_demo.blockSignals(False)
        self.lbl_punto_conexion.setStyleSheet(
            f"font-size: 16px; color: {ESMERALDA_ECG if conectado else CORAL_PULSO if state.conexionEstado == ConexionEstado.ERROR_COMUNICACION else TEXTO_SALVIA};")
        self.animador.pulso(self.lbl_punto_conexion, conectado, TEXTO_SALVIA, ESMERALDA_BRILLO,
                            lambda c: f"font-size: 16px; color: {c};")
        self.animador.pulso(self.tarjeta_bpm, conectado, BORDE_BOSQUE, ESMERALDA_ECG,
                            lambda c: f"QFrame[card=\"true\"] {{ background-color: {TARJETA_PINO}; border: 1px solid {c}; "
                                      f"border-radius: 14px; }} QFrame[card=\"true\"] QLabel {{ background: transparent; border: none; }}")
        self.btn_conectar.setEnabled(not en_curso)
        self.btn_desconectar.setEnabled(en_curso)
        self.chk_ecg_crudo.setEnabled(conectado)

        # Sincronizamos el checkbox sin disparar de nuevo el evento toggled
        self.chk_ecg_crudo.blockSignals(True)
        self.chk_ecg_crudo.setChecked(state.modoEcgCrudo)
        self.chk_ecg_crudo.blockSignals(False)

        self._pintar_calidad(state.calidadContacto, en_curso)

        self._pintar_sesion()
        self._pintar_ratio()
        self._pintar_en_vivo()
        resultado = self.alertas.evaluar(state)
        if resultado.activas != self._alertas_activas:
            self._pintar_alertas(resultado.activas)
        if resultado.sonar:
            QApplication.beep()

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
            self.animador.texto_kpi(self.lbl_bpm, f"FC: {state.bpmTexto}")
            self.animador.texto_kpi(self.lbl_rpm, f"FR: {state.rpmTexto}")

        try:
            self.lbl_zona_actual.setText("Zona: Z%d" % (zona_de(float(state.bpmTexto.split()[0]), self.vm.fc_max()) + 1))
        except (ValueError, IndexError, AttributeError):
            self.lbl_zona_actual.setText("Zona: —")
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

    def _en_modo_pip(self) -> bool:
        pip = getattr(self, "pip", None)
        return self.isMinimized() or (pip is not None and pip.isVisible())

    def hideEvent(self, event) -> None:
        if self._en_modo_pip():          # minimizar/ocultar por el PiP: la telemetría (Demo/BLE) sigue viva
            super().hideEvent(event)
            return
        self.vm.detener_demo()
        self.chk_demo.blockSignals(True)
        self.chk_demo.setChecked(False)
        self.chk_demo.blockSignals(False)
        self.animador.detener()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        self.controlador_escritorio.detener()
        self.vm.detener_demo()
        self.animador.detener()
        self.tarjeta_susurro.detener()
        self.ventana_cerrada.emit()
        super().closeEvent(event)
