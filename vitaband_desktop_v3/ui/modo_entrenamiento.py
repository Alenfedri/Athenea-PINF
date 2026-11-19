"""Modo Entrenamiento: BPM, RPM y zona cardíaca a tamaño gigante y alto contraste.

Pensado para leer a 2–3 m mientras se entrena con la banda pectoral. Se alimenta del mismo
``state_changed`` del ViewModel que la vista normal; solo dibuja, no calcula nada salvo
la zona (función de dominio ya existente).
"""

from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import QTimer, Qt, Signal, Slot
from PySide6.QtGui import QFont, QKeyEvent
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from domain.calidad_contacto import CalidadContacto
from domain.ui_state import ConexionEstado, VitaBandUiState
from domain.zonas_actividad import FC_MAX_REFERENCIA, zona_de

FONDO = "#0A0A0A"
PT_BPM = 120
PT_RPM = 72
PT_ZONA = 56
SIN_DATO = "--"

# (nombre, fondo, texto): Z1 gris azulado, Z2 verde, Z3 ámbar, Z4 naranja, Z5 rojo
ZONAS = (
    ("Z1 · Recuperación", "#8FA3B8", "#0A0A0A"),
    ("Z2 · Base", "#2ECC40", "#0A0A0A"),
    ("Z3 · Aeróbico", "#FFC20E", "#0A0A0A"),
    ("Z4 · Umbral", "#FF851B", "#0A0A0A"),
    ("Z5 · Máximo", "#E8231A", "#FFFFFF"),
)
_SIN_ZONA = ("Sin zona", "#2A2A2A", "#BBBBBB")


def numero(texto: str) -> Optional[float]:
    """BPM/RPM del estado («72.0 BPM», «--»…) como número; None si no hay valor válido."""
    try:
        v = float(texto.split()[0].replace(",", "."))
    except (ValueError, AttributeError, IndexError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def _fuente(pt: int) -> QFont:
    f = QFont()
    f.setPointSize(pt)
    f.setBold(True)
    return f


class DialogoEntrenamiento(QDialog):

    vuelta_solicitada = Signal()          # tecla Espacio

    def __init__(self, view_model, fc_max: float = FC_MAX_REFERENCIA, parent=None):
        super().__init__(parent)
        self.vm = view_model
        self.fc_max = float(fc_max)
        self.setWindowTitle("VitaBand — Modo Entrenamiento")
        self.setStyleSheet(f"QDialog {{ background:{FONDO}; }} QLabel {{ color:#FFFFFF; }}")
        self._suscrito = False

        capa = QVBoxLayout(self)
        capa.setContentsMargins(24, 12, 24, 16)

        # Estado de la banda (discreto, arriba)
        arriba = QHBoxLayout()
        self.lbl_conexion = QLabel()
        self.lbl_calidad = QLabel()
        for lbl in (self.lbl_conexion, self.lbl_calidad):
            lbl.setStyleSheet("font-size: 18px; color:#9A9A9A;")
        arriba.addWidget(self.lbl_conexion)
        arriba.addStretch()
        arriba.addWidget(self.lbl_calidad)
        capa.addLayout(arriba)

        # Alerta por umbral (borde y fondo rojos) + silenciar sonido
        self.lbl_alerta = QLabel()
        self.lbl_alerta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_alerta.setStyleSheet(
            "background:#b00020; color:#FFFFFF; font-size: 32px; font-weight: bold; padding: 10px; "
            "border: 6px solid #FF5252; border-radius: 10px;")
        self.lbl_alerta.setVisible(False)
        capa.addWidget(self.lbl_alerta)
        self.btn_sonido = QPushButton("Silenciar sonido")
        self.btn_sonido.setStyleSheet(
            "font-size: 16px; padding: 6px 14px; color:#FFFFFF; background:#333333; border:1px solid #888888;")
        arriba.addWidget(self.btn_sonido)

        # Sesión en directo (tiempo efectivo, pausa automática) y feedback de vuelta
        self.lbl_sesion = QLabel()
        self.lbl_sesion.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_sesion.setStyleSheet("font-size: 22px; color:#BBBBBB;")
        capa.addWidget(self.lbl_sesion)
        self.lbl_vuelta = QLabel()
        self.lbl_vuelta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_vuelta.setStyleSheet("font-size: 40px; font-weight: bold; color:#2ECC40;")
        self.lbl_vuelta.setVisible(False)
        capa.addWidget(self.lbl_vuelta)
        self._timer_vuelta = QTimer(self)
        self._timer_vuelta.setSingleShot(True)
        self._timer_vuelta.setInterval(2000)
        self._timer_vuelta.timeout.connect(lambda: self.lbl_vuelta.setVisible(False))

        # BPM protagonista
        self.lbl_bpm = QLabel(SIN_DATO)
        self.lbl_bpm.setFont(_fuente(PT_BPM))
        self.lbl_bpm.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_bpm.setStyleSheet("color:#FFFFFF;")
        capa.addWidget(self.lbl_bpm, stretch=3)
        capa.addWidget(self._rotulo("BPM"))

        # RPM
        self.lbl_rpm = QLabel(SIN_DATO)
        self.lbl_rpm.setFont(_fuente(PT_RPM))
        self.lbl_rpm.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_rpm.setStyleSheet("color:#7FDBFF;")
        capa.addWidget(self.lbl_rpm, stretch=2)
        capa.addWidget(self._rotulo("RPM"))

        # Zona cardíaca
        self.lbl_zona = QLabel()
        self.lbl_zona.setFont(_fuente(PT_ZONA))
        self.lbl_zona.setAlignment(Qt.AlignmentFlag.AlignCenter)
        capa.addWidget(self.lbl_zona, stretch=2)

        self.btn_salir = QPushButton("Salir del modo entrenamiento")
        self.btn_salir.setStyleSheet(
            "font-size: 20px; font-weight: bold; padding: 12px 24px; color:#FFFFFF; "
            "background:#333333; border:2px solid #FFFFFF; border-radius:8px;")
        self.btn_salir.setToolTip("Esc")
        # Sin foco en los botones: Espacio solo marca vuelta y nunca «pulsa» el botón enfocado (doble disparo)
        self.btn_salir.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_sonido.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.btn_salir.clicked.connect(self.close)
        capa.addWidget(self.btn_salir, alignment=Qt.AlignmentFlag.AlignCenter)

        self.actualizar(self.vm.state)

    @staticmethod
    def _rotulo(texto: str) -> QLabel:
        lbl = QLabel(texto)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("font-size: 22px; font-weight: bold; color:#9A9A9A;")
        return lbl

    # ------------------------------------------------------------------

    def mostrar_alertas(self, activas, silenciado: bool = False) -> None:
        """Banner y borde de aviso mientras haya alertas activas."""
        self.lbl_alerta.setText("⚠ " + "  ·  ".join(a.texto for a in activas))
        self.lbl_alerta.setVisible(bool(activas))
        self.btn_sonido.setText("Activar sonido" if silenciado else "Silenciar sonido")
        self.setStyleSheet(
            f"QDialog {{ background:{FONDO}; {'border: 8px solid #FF5252;' if activas else ''} }} "
            "QLabel { color:#FFFFFF; }")

    @property
    def zona_actual(self) -> Optional[int]:
        """Índice 0..4 de la zona mostrada, o None sin señal."""
        for i, (nombre, _, _) in enumerate(ZONAS):
            if nombre == self.lbl_zona.text():
                return i
        return None

    @Slot(VitaBandUiState)
    def actualizar(self, state: VitaBandUiState) -> None:
        calibrando = state.conexionEstado == ConexionEstado.CALIBRANDO
        bpm = None if calibrando else numero(state.bpmTexto)
        rpm = None if calibrando else numero(state.rpmTexto)

        self.lbl_bpm.setText(SIN_DATO if bpm is None else f"{bpm:.0f}")
        self.lbl_rpm.setText(SIN_DATO if rpm is None else f"{rpm:.0f}")

        nombre, fondo, texto = _SIN_ZONA if bpm is None else ZONAS[zona_de(bpm, self.fc_max)]
        self.lbl_zona.setText(nombre)
        self.lbl_zona.setStyleSheet(
            f"background:{fondo}; color:{texto}; border-radius:14px; padding:6px;")

        self.lbl_conexion.setText(f"Banda: {state.conexionEstado.value}")
        calidad = state.calidadContacto
        self.lbl_calidad.setText(f"Contacto: {calidad.value}")
        self.lbl_calidad.setStyleSheet(
            "font-size: 18px; color:%s;" % ("#2ECC40" if calidad == CalidadContacto.OPTIMO
                                              else "#FFC20E" if calidad == CalidadContacto.RUIDO else "#9A9A9A"))

    # ------------------------------------------------------------------

    def abrir(self) -> None:
        if not self._suscrito:
            self.vm.state_changed.connect(self.actualizar)
            self._suscrito = True
        self.actualizar(self.vm.state)
        self.showFullScreen()
        self.setFocus()

    def _desconectar(self) -> None:
        if self._suscrito:
            self._suscrito = False
            self.vm.state_changed.disconnect(self.actualizar)

    def mostrar_vuelta(self, texto: str) -> None:
        self.lbl_vuelta.setText(texto)
        self.lbl_vuelta.setVisible(True)
        self._timer_vuelta.start()

    def mostrar_sesion(self, texto: str) -> None:
        self.lbl_sesion.setText(texto)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        if event.key() == Qt.Key.Key_Space:
            if not event.isAutoRepeat():                  # mantener pulsada no repite vueltas
                self.vuelta_solicitada.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def done(self, resultado: int) -> None:
        self._desconectar()
        super().done(resultado)

    def closeEvent(self, event) -> None:
        self._desconectar()
        super().closeEvent(event)
