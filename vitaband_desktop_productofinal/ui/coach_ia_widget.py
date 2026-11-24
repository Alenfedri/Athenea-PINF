"""Pestaña «Coach IA»: chat híbrido (Ollama local + análisis offline) sobre los datos reales de la cuenta."""
import html
import re
import os

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QProgressBar, QPushButton, QSizePolicy,
    QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget,
)

from services import coach_ia, contexto_coach as cc, inteligencia_biometrica as ib, ollama_provisioner as prov
from services.coach_ia import MOTOR_OFFLINE, MemoriaCorta, Motor

_HILOS_VIVOS: set = set()          # evita destruir un QThread mientras aún corre (p. ej. al cerrar la ventana)


def _lanzar(hilo: QThread) -> None:
    _HILOS_VIVOS.add(hilo)
    hilo.finished.connect(lambda h=hilo: _HILOS_VIVOS.discard(h))
    hilo.start()


CONSULTAS_RAPIDAS = (
    "¿Estoy recuperado para entrenar hoy?",
    "Analiza mi última sesión",
    "¿Cómo me están afectando mis hábitos?",
    "Resumen de mi estado semanal",
)

_ESTILO_RECONECTAR = "min-height: 32px; font-size: 13px; padding: 4px 12px;"
_ESTILO_RAPIDO = "font-size: 13px; min-height: 36px; padding: 6px 12px;"
_ESTILO_ENTRADA = "font-size: 14px; min-height: 40px; padding: 6px 12px;"
_ESTILO_ENVIAR = "font-size: 14px; font-weight: bold; min-height: 40px; padding: 6px 18px;"

_ESTILO_COMBO = ("QComboBox { background:#17221E; color:#F2F6F4; border:1px solid #D4AF37; border-radius:8px; "
                 "min-height:30px; font-size:13px; padding:2px 10px; } "
                 "QComboBox QAbstractItemView { background:#111916; color:#F2F6F4; selection-background-color:#1B4D3E; "
                 "selection-color:#D4AF37; }")
_ESTILO_ACCION = ("background:#D4AF37; color:#090E0C; font-weight:bold; border:none; border-radius:8px; "
                  "padding:6px 14px; min-height:30px; font-size:13px;")
_ESTILO_PILDORA = ("font-size: 13px; min-height: 32px; padding: 4px 14px; border-radius: 16px; "
                   "border: 1px solid #1B4D3E; background: #111916; color: #F2F6F4;")

_ESTILO = """
QFrame[card="true"] { background-color: #111916; border: 1px solid #21312B; border-radius: 14px; }
QFrame[card="true"] QLabel { background: transparent; border: none; color: #F2F6F4; }
QLabel[accent="emerald"] { color: #34D399; font-weight: bold; font-size: 14px; }
QLabel[accent="gold"] { color: #D4AF37; font-weight: bold; font-size: 14px; }
QFrame[burbuja="usuario"] { background-color: #1B4D3E; border: 1px solid #10B981; border-radius: 14px; }
QFrame[burbuja="usuario"] QLabel { background: transparent; border: none; color: #F2F6F4; }
QFrame[card="true"] QLabel, QFrame[burbuja="usuario"] QLabel { font-size: 14px; padding: 12px 16px; }
QPushButton[primary="true"] { background-color: #10B981; color: #090E0C; font-weight: bold;
    border: none; border-radius: 8px; padding: 6px 16px; }
QPushButton[primary="true"]:disabled { background-color: #21312B; color: #8BA096; }
"""

from ui.animaciones_vitaband import animaciones_activas, fundido

TEXTO_CARGANDO = "Cargando modelo Qwen en memoria y analizando tus datos..."


class _DeteccionWorker(QObject):
    listo = Signal(object)
    coach_creado = Signal()

    def __init__(self, version_guardada=None):
        super().__init__()
        self._version = version_guardada

    @Slot()
    def run(self):
        try:
            prov.arrancar_si_instalado()               # solo si Ollama ya está instalado; nunca instala ni descarga
            if not os.environ.get("PYTEST_CURRENT_TEST"):
                if prov.preparar_coach(version_guardada=self._version):   # crea/actualiza vitaband-coach (sin pesos)
                    self.coach_creado.emit()
            motor = coach_ia.detectar_motor()
        except Exception:
            motor = MOTOR_OFFLINE
        self.listo.emit(motor)


class _RespuestaWorker(QObject):
    listo = Signal(str, object)
    fragmento = Signal(str)
    fallo = Signal(str, str)                      # mensaje, texto parcial

    def __init__(self, motor, pregunta, ctx, turnos, sistema=None, extra="", sencillo=False):
        super().__init__()
        self._args = (motor, pregunta, ctx, turnos)
        self._kw = {"sistema": sistema, "extra": extra, "sencillo": sencillo}

    @Slot()
    def run(self):
        try:
            texto, usado = coach_ia.responder(*self._args, **self._kw, al_fragmento=self.fragmento.emit, estricto=True)
        except coach_ia.ErrorGeneracion as e:     # Ollama sigue activo: el motor NO cambia
            self.fallo.emit(str(e), e.parcial)
            return
        except Exception as e:  # nunca debe romper la UI
            texto, usado = f"No he podido responder: {e}", MOTOR_OFFLINE
        self.listo.emit(texto, usado)


class _InstalarWorker(QObject):
    progreso = Signal(int, str)
    terminado = Signal(bool, str)

    def __init__(self, model_id):
        super().__init__()
        self._model_id = model_id

    @Slot()
    def run(self):
        try:
            prov.instalar(self._model_id, lambda p, t: self.progreso.emit(p, t))
            self.terminado.emit(True, "")
        except Exception as e:  # nunca debe romper la UI
            self.terminado.emit(False, str(e))


class DialogoInformeClinico(QDialog):
    """Dossier clínico del último mes («Traductor Médico»): copiar o exportar a TXT/PDF."""

    def __init__(self, texto: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Resumen para mi médico")
        self.setMinimumSize(560, 460)
        self.setStyleSheet("QDialog { background:#090E0C; } QPlainTextEdit { background:#111916; color:#F2F6F4; "
                           "border:1px solid #21312B; border-radius:8px; font-size:13px; padding:8px; } "
                           "QPushButton { min-height:32px; padding:4px 14px; border-radius:8px; font-size:13px; "
                           "border:1px solid #D4AF37; color:#D4AF37; background:transparent; } "
                           "QPushButton[primary=\"true\"] { background:#10B981; color:#090E0C; border:none; font-weight:bold; }")
        self.txt = QPlainTextEdit(texto)
        self.txt.setReadOnly(True)
        self.btn_copiar = QPushButton("Copiar")
        self.btn_copiar.setProperty("primary", "true")
        self.btn_txt = QPushButton("Exportar TXT")
        self.btn_pdf = QPushButton("Exportar PDF")
        self.btn_cerrar = QPushButton("Cerrar")
        v = QVBoxLayout(self)
        v.addWidget(self.txt)
        fila = QHBoxLayout()
        for b in (self.btn_copiar, self.btn_txt, self.btn_pdf, self.btn_cerrar):
            fila.addWidget(b)
        v.addLayout(fila)
        self.btn_copiar.clicked.connect(self.copiar)
        self.btn_txt.clicked.connect(lambda: self._elegir("txt"))
        self.btn_pdf.clicked.connect(lambda: self._elegir("pdf"))
        self.btn_cerrar.clicked.connect(self.accept)

    def copiar(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.txt.toPlainText())

    def exportar_txt(self, ruta: str) -> None:
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(self.txt.toPlainText())

    def exportar_pdf(self, ruta: str) -> None:
        from PySide6.QtGui import QPdfWriter, QTextDocument
        escritor = QPdfWriter(ruta)
        doc = QTextDocument()
        doc.setPlainText(self.txt.toPlainText())
        doc.print_(escritor)

    def _elegir(self, tipo: str) -> None:
        from PySide6.QtWidgets import QFileDialog
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar informe", f"resumen_medico.{tipo}",
                                              "PDF (*.pdf)" if tipo == "pdf" else "Texto (*.txt)")
        if ruta:
            (self.exportar_pdf if tipo == "pdf" else self.exportar_txt)(ruta)
            from ui import animations
            animations.show_toast(self, "Resumen para tu médico exportado")


class DialogoPerfilMemoria(QDialog):
    """«Perfil y Memoria»: ficha biométrica que ve el Coach y notas/hechos guardados en la tabla coach_memoria."""

    def __init__(self, vm, parent=None):
        super().__init__(parent)
        self.vm = vm
        self.setWindowTitle("Perfil y Memoria")
        self.setMinimumWidth(480)
        self.setStyleSheet("QDialog { background:#090E0C; } QLabel { color:#F2F6F4; font-size:13px; } "
                           "QListWidget, QLineEdit { background:#111916; color:#F2F6F4; border:1px solid #21312B; "
                           "border-radius:8px; font-size:13px; padding:4px; } QPushButton { min-height:30px; }")
        v = QVBoxLayout(self)
        t = QLabel("Lo que el Coach sabe de ti")
        t.setStyleSheet("color:#D4AF37; font-weight:bold; font-size:14px;")
        self.lbl_ficha = QLabel(vm.contexto_total_coach() or "Aún no hay datos biométricos en la cuenta.")
        self.lbl_ficha.setWordWrap(True)
        self.campos_ficha = {}
        for campo, etiqueta in (("disciplina", "Disciplina"), ("objetivo", "Objetivo"), ("fc_reposo", "FC reposo (BPM)"),
                                ("fc_max", "FC máx (BPM)")):
            e = QLineEdit()
            e.setMaxLength(60)
            e.setPlaceholderText(etiqueta)
            self.campos_ficha[campo] = e
        self.btn_guardar_ficha = QPushButton("Guardar ficha")
        self.lista = QListWidget()
        self.txt_nota = QLineEdit()
        self.txt_nota.setMaxLength(cc.MAX_LONGITUD_NOTA)
        self.txt_nota.setPlaceholderText("Añade una nota (lesión, carrera objetivo, sueño…)")
        self.btn_anadir = QPushButton("Añadir nota")
        self.btn_eliminar = QPushButton("Eliminar seleccionada")
        self.btn_cerrar = QPushButton("Cerrar")
        fila = QHBoxLayout()
        for w in (self.btn_anadir, self.btn_eliminar, self.btn_cerrar):
            fila.addWidget(w)
        for w in (t, self.lbl_ficha, QLabel("Ficha editable (vacío = automático)"), *self.campos_ficha.values(),
                  self.btn_guardar_ficha, QLabel("Memoria"), self.lista, self.txt_nota):
            v.addWidget(w)
        v.addLayout(fila)
        self.btn_guardar_ficha.clicked.connect(self._guardar_ficha)
        m = vm.memoria_coach()
        for campo, valor in (m.ficha() if m is not None else {}).items():
            self.campos_ficha[campo].setText(valor)
        self.btn_anadir.clicked.connect(self._anadir)
        self.txt_nota.returnPressed.connect(self._anadir)
        self.btn_eliminar.clicked.connect(self._eliminar)
        self.btn_cerrar.clicked.connect(self.accept)
        self._recargar()

    def _memoria(self):
        return self.vm.memoria_coach()

    def _guardar_ficha(self):
        m = self._memoria()
        if m is None:
            return
        for campo, e in self.campos_ficha.items():
            m.fijar_ficha(campo, e.text())
        self.lbl_ficha.setText(self.vm.contexto_total_coach() or "Aún no hay datos biométricos en la cuenta.")

    def _recargar(self):
        self.lista.clear()
        m = self._memoria()
        for id_, ts, tipo, texto in ([] if m is None else m.listar()):
            self.lista.addItem(f"[{'nota' if tipo == 'nota' else 'chat'}] {texto}")
            self.lista.item(self.lista.count() - 1).setData(Qt.UserRole, id_)

    def _anadir(self):
        m = self._memoria()
        if m is not None and self.txt_nota.text().strip():
            m.agregar(self.txt_nota.text(), "nota")
            self.txt_nota.clear()
            self._recargar()

    def _eliminar(self):
        m, it = self._memoria(), self.lista.currentItem()
        if m is not None and it is not None:
            m.eliminar(it.data(Qt.UserRole))
            self._recargar()


class CoachIaWidget(QWidget):
    accion_coherencia = Signal()
    accion_plan_zona2 = Signal()
    plan_modificado = Signal()

    def __init__(self, vm, parent=None):
        super().__init__(parent)
        self.vm = vm
        self._burbujas_coach: list = []
        self.motor: Motor = MOTOR_OFFLINE
        self.memoria = MemoriaCorta()
        self._hilo = None
        self._worker = None
        self._hilo_det = None
        self._worker_det = None
        self._hilo_inst = None
        self._worker_inst = None
        self.estado = prov.CHECK_ONLY
        self._rechazado = False
        self._construido = False                       # la interfaz y la detección arrancan al mostrar la pestaña

    def showEvent(self, ev):
        self._reajustar_burbujas()
        self._construir()
        self.refrescar_senales()
        super().showEvent(ev)

    def _construir(self):
        if self._construido:
            return
        self._construido = True
        self.setStyleSheet(_ESTILO)

        raiz = QVBoxLayout(self)
        cab = QFrame()
        cab.setProperty("card", "true")
        fila = QHBoxLayout(cab)
        self.lbl_motor = QLabel()
        self.btn_reconectar = QPushButton("Reconectar")
        self.btn_reconectar.setStyleSheet(_ESTILO_RECONECTAR)
        self.btn_activar_qwen = QPushButton("Activar IA Qwen")
        self.btn_activar_qwen.setStyleSheet(_ESTILO_RECONECTAR)
        self.btn_activar_qwen.setVisible(False)
        self.btn_activar_qwen.clicked.connect(self._reabrir_consentimiento)
        fila.addWidget(self.lbl_motor, 1)
        fila.addWidget(self.btn_activar_qwen)
        fila.addWidget(self.btn_reconectar)
        raiz.addWidget(cab)
        self.cabecera = cab

        ajustes = QHBoxLayout()
        self.combo_nivel = QComboBox()
        for clave, texto in cc.NIVELES:
            self.combo_nivel.addItem(texto, clave)                    # «Sencillo (Explicado)» queda seleccionado por defecto
        self.combo_arquetipo = QComboBox()
        for clave, (nombre, _) in cc.ARQUETIPOS.items():
            self.combo_arquetipo.addItem(nombre, clave)
        self.combo_arquetipo.setCurrentIndex(self.combo_arquetipo.findData(cc.ARQUETIPO_DEFECTO))
        for c_ in (self.combo_nivel, self.combo_arquetipo):
            c_.setStyleSheet(_ESTILO_COMBO)
        self.btn_metricas = QPushButton("¿Qué significan estas métricas?")
        self.btn_memoria = QPushButton("Perfil y Memoria")
        self.btn_analizar_ultima = QPushButton("Analizar última sesión")
        self.chk_auto_analisis = QCheckBox("Resumir sesión al terminar")
        self.chk_auto_analisis.setStyleSheet("color: #E2E8F0; font-size: 13px;")
        self.chk_auto_analisis.setToolTip("Genera automáticamente un resumen del Coach cada vez que finalizas una sesión en Tiempo Real.")
        for b in (self.btn_metricas, self.btn_memoria, self.btn_analizar_ultima):
            b.setStyleSheet(_ESTILO_RECONECTAR)
        self.btn_informe = QPushButton("Preparar resumen para mi médico")      # botón normal de la barra superior
        self.btn_informe.setStyleSheet("font-size:13px; padding:4px 10px; border-radius:8px; "
                                       "background:#10B981; color:#090E0C; border:1px solid #D4AF37; font-weight:bold;")
        for w in (self.combo_nivel, self.combo_arquetipo, self.btn_metricas, self.btn_memoria, self.btn_analizar_ultima,
                  self.btn_informe, self.chk_auto_analisis):
            ajustes.addWidget(w)
        ajustes.addStretch(1)
        raiz.addLayout(ajustes)

        senales = QHBoxLayout()
        self.banner_alerta = QLabel()
        self.banner_alerta.setWordWrap(True)
        self.banner_alerta.setStyleSheet("background:#17221E; color:#F2F6F4; border:1px solid #D4AF37; border-radius:10px; "
                                         "padding:8px 12px; font-size:13px;")
        self.banner_alerta.setVisible(False)
        self.btn_reajustar = QPushButton("Reajustar semana sin culpa")
        self.btn_reajustar.setStyleSheet(_ESTILO_ACCION)
        self.btn_reajustar.setVisible(False)
        senales.addWidget(self.banner_alerta, 1)
        senales.addWidget(self.btn_reajustar)
        raiz.addLayout(senales)

        self._construir_tarjeta_consentimiento(raiz)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        cont = QWidget()
        self._chat = QVBoxLayout(cont)
        self._chat.setSpacing(12)
        self._chat.addStretch(1)
        self.scroll.setWidget(cont)
        raiz.addWidget(self.scroll, 1)

        # Zona inferior fija: hábitos, consultas rápidas y entrada de texto; solo el chat se estira
        self.barra_inferior = QWidget()
        self.barra_inferior.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        inf = QVBoxLayout(self.barra_inferior)
        inf.setContentsMargins(0, 0, 0, 0)
        raiz.addWidget(self.barra_inferior, 0)
        habitos = QHBoxLayout()
        self.botones_habito = []
        for texto in ib.HABITOS_RAPIDOS:
            b = QPushButton(texto)
            b.setStyleSheet(_ESTILO_PILDORA)
            b.clicked.connect(lambda _=False, t=texto: self._registrar_habito(t))
            habitos.addWidget(b)
            self.botones_habito.append(b)
        self.lbl_habito = QLabel()
        self.lbl_habito.setStyleSheet("color:#8BA096; font-size:12px;")
        habitos.addWidget(self.lbl_habito, 1)
        inf.addLayout(habitos)

        principiante = QHBoxLayout()
        self.botones_principiante = []
        for texto in cc.PREGUNTAS_PRINCIPIANTE:
            b = QPushButton(texto)
            b.setStyleSheet(_ESTILO_PILDORA)
            b.clicked.connect(lambda _=False, t=texto: self.enviar(t))
            principiante.addWidget(b)
            self.botones_principiante.append(b)
        principiante.addStretch(1)
        inf.addLayout(principiante)

        rapidos = QHBoxLayout()
        self.botones_rapidos = []
        for texto in CONSULTAS_RAPIDAS:
            b = QPushButton(texto)
            b.setStyleSheet(_ESTILO_RAPIDO)
            b.clicked.connect(lambda _=False, t=texto: self.enviar(t))
            rapidos.addWidget(b)
            self.botones_rapidos.append(b)
        inf.addLayout(rapidos)

        entrada = QHBoxLayout()
        self.txt_entrada = QLineEdit()
        self.txt_entrada.setPlaceholderText("Pregunta al Coach VitaBand…")
        self.btn_enviar = QPushButton("Enviar")
        self.btn_enviar.setProperty("primary", "true")
        self.btn_enviar.setStyleSheet(_ESTILO_ENVIAR)
        self.txt_entrada.setStyleSheet(_ESTILO_ENTRADA)
        entrada.addWidget(self.txt_entrada, 1)
        entrada.addWidget(self.btn_enviar)
        inf.addLayout(entrada)

        self.txt_entrada.returnPressed.connect(self._enviar_entrada)
        self.btn_enviar.clicked.connect(self._enviar_entrada)
        self.btn_reconectar.clicked.connect(self.reconectar)
        self.btn_metricas.clicked.connect(self._mostrar_chuleta)
        self.btn_memoria.clicked.connect(self._abrir_memoria)
        self.btn_analizar_ultima.clicked.connect(lambda: self.enviar("Analiza mi última sesión"))
        self.vm.sesion_importada.connect(self._auto_analisis)
        self.btn_reajustar.clicked.connect(self._reajustar)
        self.btn_informe.clicked.connect(self._abrir_informe)
        self.combo_nivel.currentIndexChanged.connect(lambda _=0: self.refrescar_senales())
        self.refrescar_senales()

        self._mostrar_motor(MOTOR_OFFLINE)
        self._burbuja("¡Hola! Soy tu Coach VitaBand. ¿Cómo te encuentras hoy?", usuario=False)
        self.reconectar()

    # --- Consentimiento para instalar Qwen (nunca se descarga nada sin pulsar «Sí») ---
    def _construir_tarjeta_consentimiento(self, raiz):
        t = QFrame()
        t.setStyleSheet("QFrame#consent { background-color: #090E0C; border: 1px solid #10B981; border-radius: 14px; } "
                        "QFrame#consent QLabel { background: transparent; border: none; color: #F2F6F4; font-size: 14px; }")
        t.setObjectName("consent")
        v = QVBoxLayout(t)
        v.setContentsMargins(16, 14, 16, 14)
        self.lbl_consent_titulo = QLabel("¿Quieres instalar el motor IA local Qwen para potenciar el Coach IA?")
        self.lbl_consent_titulo.setWordWrap(True)
        self.lbl_consent_titulo.setStyleSheet("color: #34D399; font-weight: bold; font-size: 14px;")
        self.lbl_consent_espacio = QLabel()
        self.lbl_consent_espacio.setWordWrap(True)
        self.combo_modelo = QComboBox()
        self.combo_modelo.setStyleSheet("min-height: 32px; font-size: 13px; padding: 4px 8px;")
        self.barra_instalacion = QProgressBar()
        self.barra_instalacion.setRange(0, 100)
        self.barra_instalacion.setVisible(False)
        self.lbl_instalacion = QLabel()
        self.lbl_instalacion.setWordWrap(True)
        self.btn_no_offline = QPushButton("No, continuar en Modo Offline")
        self.btn_si_instalar = QPushButton("Sí, instalar modelo elegido")
        self.btn_no_offline.setStyleSheet(_ESTILO_RAPIDO)
        self.btn_si_instalar.setProperty("primary", "true")
        self.btn_si_instalar.setStyleSheet(_ESTILO_ENVIAR)
        self.btn_no_offline.clicked.connect(self._rechazar_instalacion)
        self.btn_si_instalar.clicked.connect(self._aceptar_instalacion)
        fila = QHBoxLayout()
        fila.addWidget(self.btn_no_offline)
        fila.addWidget(self.btn_si_instalar)
        for w in (self.lbl_consent_titulo, self.lbl_consent_espacio, self.combo_modelo, self.barra_instalacion,
                  self.lbl_instalacion):
            v.addWidget(w)
        v.addLayout(fila)
        t.setVisible(False)
        self.tarjeta_consentimiento = t
        raiz.addWidget(t)

    def _mostrar_consentimiento(self):
        self.estado = prov.CONSENT_REQUIRED
        cap = prov.detectar_capacidad_equipo()
        self.capacidad = cap
        libre = "desconocido" if cap.disco_libre_gb is None else f"{cap.disco_libre_gb:.1f} GB".replace(".", ",")
        ram = "" if cap.ram_gb is None else f" · RAM: {cap.ram_gb:.0f} GB"
        self.lbl_consent_espacio.setText(f"Espacio libre detectado: {libre}{ram}. Se instala solo el modelo que elijas; "
                                         "sin tu permiso no se descarga nada.")
        self.combo_modelo.clear()
        for opcion, texto, rec in prov.opciones(cap):
            self.combo_modelo.addItem(texto, opcion.model_id)
            if rec:
                self.combo_modelo.setCurrentIndex(self.combo_modelo.count() - 1)
        self.barra_instalacion.setVisible(False)
        self.lbl_instalacion.clear()
        self.btn_activar_qwen.setVisible(False)
        self.tarjeta_consentimiento.setVisible(True)

    def _rechazar_instalacion(self):
        self._rechazado = True
        self.estado = prov.OFFLINE
        self.tarjeta_consentimiento.setVisible(False)
        self.btn_activar_qwen.setVisible(True)

    def _reabrir_consentimiento(self):
        self._rechazado = False
        self._mostrar_consentimiento()

    def _aceptar_instalacion(self):
        if self._hilo_inst is not None and self._hilo_inst.isRunning():
            return
        model_id = self.combo_modelo.currentData()
        self.estado = prov.INSTALLING
        for w in (self.btn_si_instalar, self.btn_no_offline, self.combo_modelo):
            w.setEnabled(False)
        self.barra_instalacion.setValue(0)
        self.barra_instalacion.setVisible(True)
        self.lbl_instalacion.setText("Preparando la instalación…")
        self._hilo_inst = QThread()
        self._worker_inst = _InstalarWorker(model_id)
        self._worker_inst.moveToThread(self._hilo_inst)
        self._hilo_inst.started.connect(self._worker_inst.run)
        self._worker_inst.progreso.connect(self._progreso_instalacion)
        self._worker_inst.terminado.connect(self._instalacion_terminada)
        self._worker_inst.terminado.connect(self._hilo_inst.quit)
        _lanzar(self._hilo_inst)

    @Slot(int, str)
    def _progreso_instalacion(self, pct: int, texto: str):
        self.barra_instalacion.setValue(pct)
        self.lbl_instalacion.setText(texto)

    @Slot(bool, str)
    def _instalacion_terminada(self, ok: bool, error: str):
        for w in (self.btn_si_instalar, self.btn_no_offline, self.combo_modelo):
            w.setEnabled(True)
        if ok:
            self.tarjeta_consentimiento.setVisible(False)
            self.estado = prov.READY
            self._guardar_version_coach()
            self.reconectar()
        else:
            self.estado = prov.ERROR
            self.lbl_instalacion.setText(f"No se pudo instalar: {error}. El Coach sigue en Modo Offline.")

    # --- Maxx: chuleta, memoria, auto-análisis y acciones ---
    @property
    def nivel(self) -> str:
        return self.combo_nivel.currentData()

    @property
    def arquetipo(self) -> str:
        return self.combo_arquetipo.currentData()

    def _mostrar_chuleta(self):
        self._burbuja(cc.CHULETA, usuario=False)                   # instantánea: sin inferencia ni memoria

    def _abrir_memoria(self):
        self.dialogo_memoria = DialogoPerfilMemoria(self.vm, self)
        self.dialogo_memoria.show()

    @Slot()
    def _auto_analisis(self):
        if self._construido and self.chk_auto_analisis.isChecked():
            self.enviar("Analiza mi última sesión")

    def _pulsar_accion(self, accion: str, boton):
        """Confirmación visual inmediata y bloqueo: un solo clic por botón de acción."""
        boton.setEnabled(False)
        boton.setText({"PLAN_ZONA2": "✓ Añadido al plan de hoy", "REAJUSTAR_SEMANA": "✓ Semana reajustada",
                       "COHERENCIA_60S": "✓ Coherencia iniciada"}.get(accion, "✓ Hecho"))
        boton.setStyleSheet("background:#10B981; color:#090E0C; font-weight:bold; border:none; border-radius:8px; "
                            "padding:6px 12px;")
        self._lanzar_accion(accion)

    def _lanzar_accion(self, accion: str):
        if accion == "REAJUSTAR_SEMANA":
            self._reajustar()
            return
        (self.accion_coherencia if accion == "COHERENCIA_60S" else self.accion_plan_zona2).emit()

    # --- Coach de salud: escudo preventivo, hábitos, Modo Vida Real e informe ---
    def refrescar_senales(self):
        """Banner del escudo preventivo y botón de reajuste (lectura rápida de SQLite en el hilo principal)."""
        if not self._construido:
            return
        alerta = self.vm.alerta_preventiva()
        self.banner_alerta.setVisible(alerta is not None)
        if alerta is not None:
            self.banner_alerta.setText("Alerta preventiva · " + alerta.texto(self.nivel == cc.NIVEL_SENCILLO))
        self.btn_reajustar.setVisible(self.vm.motivo_reajuste() is not None)

    def _registrar_habito(self, etiqueta: str):
        nuevo = self.vm.registrar_habito_diario(etiqueta)
        self.lbl_habito.setText(f"Registrado hoy: {etiqueta}" if nuevo else f"«{etiqueta}» ya estaba registrado hoy")

    def _reajustar(self):
        msg = self.vm.reajustar_semana()
        if msg:
            self._burbuja(msg, usuario=False)
        self.btn_reajustar.setVisible(False)
        self.plan_modificado.emit()

    def _abrir_informe(self):
        self.dialogo_informe = DialogoInformeClinico(self.vm.informe_clinico(), self)
        self.dialogo_informe.show()

    # --- Motor ---
    def _mostrar_motor(self, motor: Motor):
        self.motor = motor
        self.lbl_motor.setText(motor.etiqueta)
        self.lbl_motor.setProperty("accent", motor.acento)
        self.lbl_motor.style().unpolish(self.lbl_motor)
        self.lbl_motor.style().polish(self.lbl_motor)

    def reconectar(self):
        """Re-detecta el motor en segundo plano (no congela la UI)."""
        self._construir()
        if self._hilo_det is not None and self._hilo_det.isRunning():
            return
        self.btn_reconectar.setEnabled(False)
        self._hilo_det = QThread()
        meta = self.vm.app_meta()                      # SQLite solo en el hilo principal
        self._worker_det = _DeteccionWorker(None if meta is None else meta.obtener(prov.CLAVE_VERSION_META))
        self._worker_det.coach_creado.connect(self._guardar_version_coach)
        self._worker_det.moveToThread(self._hilo_det)
        self._hilo_det.started.connect(self._worker_det.run)
        self._worker_det.listo.connect(self._motor_detectado)
        self._worker_det.listo.connect(self._hilo_det.quit)
        _lanzar(self._hilo_det)

    @Slot()
    def _guardar_version_coach(self):
        meta = self.vm.app_meta()
        if meta is not None:
            meta.guardar(prov.CLAVE_VERSION_META, prov.COACH_PROMPT_VERSION)

    @Slot(object)
    def _motor_detectado(self, motor):
        self._mostrar_motor(motor)
        self.btn_reconectar.setEnabled(True)
        if motor.tipo == "ollama":
            self.estado = prov.READY
            self.tarjeta_consentimiento.setVisible(False)
            self.btn_activar_qwen.setVisible(False)
        elif self._rechazado:
            self.btn_activar_qwen.setVisible(True)
        elif self.estado != prov.INSTALLING:
            self._mostrar_consentimiento()                 # CONSENT_REQUIRED: solo se pregunta, no se descarga nada

    # --- Chat ---
    def _burbuja(self, texto: str, usuario: bool, acciones=()):
        marco = QFrame()
        if usuario:
            marco.setProperty("burbuja", "usuario")
            marco.setStyleSheet("background-color: #1B4D3E; border: 1px solid #10B981; border-radius: 14px;")
        else:
            marco.setProperty("card", "true")
        lay = QVBoxLayout(marco)
        lbl = QLabel("<div style='line-height:150%'>" + html.escape(texto).replace("\n", "<br>") + "</div>")
        lbl.setTextFormat(Qt.RichText)
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(lbl)
        self.botones_accion = []
        for a in acciones:
            b = QPushButton({"COHERENCIA_60S": "Iniciar coherencia cardíaca (60 s)", "REAJUSTAR_SEMANA": "Reajustar semana sin culpa"}.get(a, "Añadir Zona 2 de 40 min al plan"))
            b.setStyleSheet(_ESTILO_ACCION)
            b.clicked.connect(lambda _=False, x=a, bb=b: self._pulsar_accion(x, bb))
            lay.addWidget(b)
            self.botones_accion.append(b)
        marco.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        if usuario:
            marco.setStyleSheet(marco.styleSheet() + " padding: 12px 16px;")
        self._burbujas_coach.append((marco, usuario))
        self._ajustar_burbuja(marco, usuario)
        fila = QHBoxLayout()
        if usuario:
            fila.addStretch(1)
            fila.addWidget(marco)
        else:
            fila.addWidget(marco)
            fila.addStretch(1)
        cont = QWidget()
        cont.setLayout(fila)
        fila.setContentsMargins(0, 0, 0, 0)
        self._chat.insertWidget(self._chat.count() - 1, cont)
        if animaciones_activas():
            fundido(cont)                                           # entrada animada de la burbuja
        barra = self.scroll.verticalScrollBar()
        barra.setValue(barra.maximum())
        return marco

    def _bloquear(self, ocupado: bool):
        for w in (self.btn_enviar, self.txt_entrada, *self.botones_rapidos, *self.botones_principiante):
            w.setEnabled(not ocupado)

    def _enviar_entrada(self):
        texto = self.txt_entrada.text().strip()
        if texto:
            self.txt_entrada.clear()
            self.enviar(texto)

    def enviar(self, pregunta: str, repetir: bool = False):
        self._construir()
        if self._hilo is not None and self._hilo.isRunning():
            return
        if not repetir:
            self._burbuja(pregunta, usuario=True)
        ctx = self.vm.contexto_coach()  # SQLite siempre en el hilo principal
        mem = self.vm.memoria_coach()
        if mem is not None:
            mem.registrar_hechos_de(pregunta)                      # lesiones, carreras o falta de sueño mencionados
        sistema = cc.prompt_sistema(self.nivel, self.arquetipo, "" if mem is None else mem.a_texto())
        extra = self.vm.contexto_total_coach()
        nombre = getattr(self.vm, "nombre_usuario", "") or ""
        if nombre:
            extra = f"NOMBRE DEL USUARIO: {nombre}\n{extra}"
        sencillo = self.nivel == cc.NIVEL_SENCILLO
        if self.motor.tipo == "offline":
            texto, usado = coach_ia.responder(self.motor, pregunta, ctx, self.memoria.turnos, sencillo=sencillo)
            self._terminar(pregunta, texto, usado)
            return
        self._bloquear(True)
        self._vivo = self._burbuja(TEXTO_CARGANDO, usuario=False)
        self._acumulado = ""
        self._hilo = QThread()
        self._worker = _RespuestaWorker(self.motor, pregunta, ctx, self.memoria.turnos, sistema, extra, sencillo)
        self._worker.moveToThread(self._hilo)
        self._hilo.started.connect(self._worker.run)
        self._worker.fragmento.connect(self._fragmento)
        self._pregunta_actual = pregunta
        self._worker.listo.connect(self._al_terminar)                 # métodos enlazados: se ejecutan en el hilo de la UI
        self._worker.fallo.connect(self._al_fallar)
        self._worker.listo.connect(self._hilo.quit)
        self._worker.fallo.connect(self._hilo.quit)
        _lanzar(self._hilo)

    @Slot(str, object)
    def _al_terminar(self, texto, usado):
        self._terminar(self._pregunta_actual, texto, usado)

    @Slot(str, str)
    def _al_fallar(self, mensaje, parcial):
        self._fallo(self._pregunta_actual, mensaje, parcial)

    def _ancho_chat(self) -> int:
        vw = self.scroll.viewport().width() if getattr(self, "scroll", None) is not None else 0
        return max((vw if vw > 0 else self.width()) - 64, 600)

    def _ajustar_burbuja(self, marco, usuario: bool):
        ancho = self._ancho_chat()
        if usuario:
            marco.setMinimumWidth(0)
            marco.setMaximumWidth(int(ancho * 0.50))
        else:
            marco.setMinimumWidth(int(ancho * 0.55))
            marco.setMaximumWidth(int(ancho * 0.72))

    def _reajustar_burbujas(self):
        vivas = []
        for marco, usuario in self._burbujas_coach:
            try:
                self._ajustar_burbuja(marco, usuario)
                vivas.append((marco, usuario))
            except RuntimeError:                                    # widget ya destruido
                pass
        self._burbujas_coach = vivas

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._reajustar_burbujas()

    def _quitar_vivo(self):
        v = getattr(self, "_vivo", None)
        self._vivo = None
        if v is not None:
            self._burbujas_coach = [(m, u) for m, u in self._burbujas_coach if m is not v]
            c = v.parentWidget()
            c.setParent(None)
            c.deleteLater()

    @Slot(str)
    def _fragmento(self, trozo: str):
        v = getattr(self, "_vivo", None)
        if v is None:
            return
        self._acumulado += trozo
        visible = re.split(r"<ACTION>|\[ACCION:", self._acumulado)[0]          # el bloque de acción no se pinta
        v.findChild(QLabel).setText("<div style='line-height:150%'>" + html.escape(visible).replace("\n", "<br>") + "</div>")
        barra = self.scroll.verticalScrollBar()
        barra.setValue(barra.maximum())

    def _fallo(self, pregunta: str, mensaje: str, parcial: str):
        """Fallo puntual con Ollama activo: se mantiene el motor y se ofrece reintentar."""
        self._quitar_vivo()
        if parcial.strip():
            self._burbuja(parcial.strip(), usuario=False)
        cont = self._burbuja("Ollama sigue activo, pero esta respuesta no ha llegado a tiempo o se interrumpió "
                             f"({mensaje}). Si es la primera pregunta, el modelo puede estar cargándose en memoria.",
                             usuario=False)
        self.btn_reintentar = QPushButton("Reintentar")
        self.btn_reintentar.setStyleSheet(_ESTILO_ACCION)
        self.btn_reintentar.clicked.connect(lambda _=False, c=cont.parentWidget(), p=pregunta: (c.setParent(None), c.deleteLater(),
                                                                                              self.enviar(p, repetir=True)))
        cont.layout().addWidget(self.btn_reintentar)
        self._bloquear(False)

    def _terminar(self, pregunta: str, texto: str, usado):
        self._quitar_vivo()
        if usado.tipo != self.motor.tipo:  # Ollama falló: pasamos a offline
            self._mostrar_motor(usado)
        texto, acciones = cc.extraer_acciones(texto)
        self.memoria.agregar(pregunta, texto)
        self._burbuja(texto, usuario=False, acciones=acciones)
        self._bloquear(False)

    def reiniciar(self):
        """Limpia memoria e historial (cambio de cuenta / cierre de sesión)."""
        self.memoria.limpiar()
        self._burbujas_coach = []
        if not self._construido:
            return
        while self._chat.count() > 1:
            item = self._chat.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def closeEvent(self, ev):
        for h in (self._hilo_det, self._hilo, self._hilo_inst):
            if h is not None and h.isRunning():
                h.wait(2000)
        super().closeEvent(ev)
