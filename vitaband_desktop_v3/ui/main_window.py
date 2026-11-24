from datetime import date

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
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
from domain.ui_state import ConexionEstado, VitaBandUiState
from ui.confirmaciones import confirmar
from ui.dialogo_eliminar_cuenta import DialogoEliminarCuenta
from ui.dialogo_coherencia import DialogoCoherencia
from ui.dialogo_ortostatico import DialogoOrtostatico
from ui.dialogo_perfil import DialogoPerfil
from services import anonimizar as anonimizar_mod, ratio_pulso_resp as ratio_mod
from ui.exportar_png import boton_png
from ui.modo_entrenamiento import DialogoEntrenamiento
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

    def __init__(self, view_model: VitaBandViewModel, nombre_usuario: str = "", correo_usuario: str = ""):
        super().__init__()
        self.vm = view_model
        self._nombre_usuario = nombre_usuario
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
        self.btn_exportar_pdf = QPushButton("Exportar informe PDF")
        self.btn_backup = QPushButton("Exportar Backup (.zip)")
        self.btn_restaurar = QPushButton("Restaurar Backup (.zip)")
        self.btn_perfil = QPushButton("Perfil fisiológico")
        self.btn_eliminar_cuenta = QPushButton("Eliminar cuenta")
        self.lbl_usuario = QLabel(f"Usuario: {self._nombre_usuario}" if self._nombre_usuario else "")
        self.btn_cerrar_sesion = QPushButton("Cerrar sesión")
        barra_top.addWidget(self.btn_sincronizar)
        barra_top.addWidget(self.btn_exportar_csv)
        barra_top.addWidget(self.btn_exportar_pdf)
        self.chk_anonimizar = QCheckBox("Anonimizar datos personales")
        self.chk_anonimizar.setToolTip("Sustituye nombre y correo por un identificador SUJETO-xxxxxx en el PDF y el CSV")
        barra_top.addWidget(self.chk_anonimizar)
        barra_top.addWidget(self.lbl_usuario)
        barra_top.addWidget(self.btn_perfil)
        barra_top.addWidget(self.btn_backup)
        barra_top.addWidget(self.btn_restaurar)
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
        self.btn_exportar_pdf.clicked.connect(self._exportar_pdf)
        self.btn_perfil.clicked.connect(self._editar_perfil)
        self.btn_backup.clicked.connect(self._exportar_backup)
        self.btn_restaurar.clicked.connect(self._restaurar_backup)
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
        for w in (self.btn_lap, self.btn_ortostatico, self.btn_coherencia, self.lbl_vuelta, self.lbl_pausa):
            fila_sesion.addWidget(w)
        fila_sesion.addStretch()
        fila_sesion.addWidget(self.lbl_sesion)
        layout.addLayout(fila_sesion)

        # Cociente pulso/respiración y Modo Escritorio (pausa activa por estrés)
        fila_extra = QHBoxLayout()
        self.lbl_ratio = QLabel("Pulso/respiración: N/D")
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
        self.chk_escritorio.toggled.connect(self._cambio_escritorio)
        self.spin_escritorio.valueChanged.connect(self._cambio_escritorio)
        self.lbl_estres = QLabel()
        self.lbl_estres.setWordWrap(True)
        self.lbl_estres.setStyleSheet("color: #14532d; background:#d7f0dd; padding: 2px 8px;")
        self.btn_estres_coherencia = QPushButton("Abrir Coherencia Cardíaca")
        self.btn_estres_coherencia.clicked.connect(self._abrir_coherencia)
        self.lbl_estres.setVisible(False)
        self.btn_estres_coherencia.setVisible(False)
        for w in (self.lbl_ratio, self.lbl_alerta_ratio):
            fila_extra.addWidget(w)
        fila_extra.addStretch()
        for w in (self.chk_escritorio, self.spin_escritorio):
            fila_extra.addWidget(w)
        layout.addLayout(fila_extra)
        fila_estres = QHBoxLayout()
        fila_estres.addWidget(self.lbl_estres, 1)
        fila_estres.addWidget(self.btn_estres_coherencia)
        layout.addLayout(fila_estres)
        self.vm.aviso_estres.connect(self._mostrar_aviso_estres)
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
        fila_ecg.addWidget(self.btn_sonido)
        fila_ecg.addWidget(self.btn_entrenamiento)
        fila_ecg.addWidget(self.lbl_calidad)
        layout.addLayout(fila_ecg)

        # Gráfica PyQtGraph de alto rendimiento (100 Hz)
        self.plot_widget = pg.PlotWidget(title="Señal ECG (100 Hz)")
        self.plot_widget.setLabel("left", "Amplitud (ADC)")
        self.plot_widget.setLabel("bottom", "Tiempo", units="s")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.curva_ecg = self.plot_widget.plot(pen=pg.mkPen("#1f77b4", width=2))
        layout.addWidget(self.plot_widget)
        fila_ecg.addWidget(boton_png(self.plot_widget, "vitaband_ecg"))
        return pagina

    @Slot()
    def _abrir_modo_entrenamiento(self) -> None:
        self.modo_entrenamiento = DialogoEntrenamiento(self.vm, parent=self)
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
            sujeto = (anonimizar_mod.seudonimo(self._correo_usuario, self._nombre_usuario)
                      if self.chk_anonimizar.isChecked() else None)
            filas = self.vm.exportar_csv(ruta, sujeto=sujeto)
        except Exception as exc:
            QMessageBox.warning(self, "No se pudo exportar", f"Error al exportar el historial:\n{exc}")
            return

        QMessageBox.information(
            self, "Exportación completada", f"Se exportaron {filas} registros a:\n{ruta}"
        )

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

    @Slot()
    def _abrir_coherencia(self) -> None:
        self.lbl_estres.setVisible(False)
        self.btn_estres_coherencia.setVisible(False)
        self.dialogo_coherencia = DialogoCoherencia(self.vm, parent=self)
        self.dialogo_coherencia.show()

    def _cambio_escritorio(self, *_args) -> None:
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
        QMessageBox.information(self, "Informe generado", f"Informe PDF guardado en:\n{ruta}")

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

        self.lbl_conexion.setText(f"Estado: {state.conexionEstado.value}")
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
