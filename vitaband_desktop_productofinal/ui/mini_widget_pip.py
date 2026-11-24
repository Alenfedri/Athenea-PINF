"""Mini-widget flotante (Picture-in-Picture): BPM, RPM y zona actual, siempre visible y arrastrable."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ui.modo_entrenamiento import SIN_DATO, ZONAS, _SIN_ZONA, numero
from domain.zonas_actividad import zona_de
from ui.tema_vitaband import ESMERALDA_BRILLO, FONDO_OBSIDIANA, TEXTO_MARFIL, VERDE_PINO


class MiniWidgetPip(QWidget):

    restaurar_solicitado = Signal()

    def __init__(self, view_model, parent=None):
        super().__init__(parent)
        self.vm = view_model
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setWindowOpacity(0.85)
        self.setStyleSheet(f"MiniWidgetPip {{ background:{FONDO_OBSIDIANA}; border:2px solid {VERDE_PINO}; border-radius:10px; }}"
                           f" QLabel {{ color:{TEXTO_MARFIL}; background:transparent; }}")
        capa = QVBoxLayout(self)
        capa.setContentsMargins(12, 8, 12, 8)
        fila = QHBoxLayout()
        self.lbl_bpm = QLabel(SIN_DATO)
        self.lbl_bpm.setStyleSheet("font-size: 34px; font-weight: bold;")
        self.lbl_rpm = QLabel(SIN_DATO)
        self.lbl_rpm.setStyleSheet(f"font-size: 22px; color:{ESMERALDA_BRILLO};")
        fila.addWidget(self.lbl_bpm)
        fila.addWidget(QLabel("BPM"))
        fila.addSpacing(10)
        fila.addWidget(self.lbl_rpm)
        fila.addWidget(QLabel("RPM"))
        capa.addLayout(fila)
        self.lbl_zona = QLabel()
        capa.addWidget(self.lbl_zona)
        self.btn_restaurar = QPushButton("Restaurar")
        self.btn_restaurar.clicked.connect(self.restaurar_solicitado)
        capa.addWidget(self.btn_restaurar)
        self._arrastre: Optional[QPoint] = None
        self._suscrito = False
        self.actualizar(self.vm.state)

    # --- telemetría en directo ---
    def actualizar(self, st) -> None:
        bpm, rpm = numero(st.bpmTexto), numero(st.rpmTexto)
        self.lbl_bpm.setText(SIN_DATO if bpm is None else f"{bpm:.0f}")
        self.lbl_rpm.setText(SIN_DATO if rpm is None else f"{rpm:.0f}")
        nombre, fondo, texto = _SIN_ZONA if bpm is None else ZONAS[zona_de(bpm, self.vm.fc_max())]
        self.lbl_zona.setText(nombre)
        self.lbl_zona.setStyleSheet(f"background:{fondo}; color:{texto}; border-radius:6px; padding:3px;")

    @property
    def zona_texto(self) -> str:
        return self.lbl_zona.text()

    def mostrar_sincronizado(self) -> None:
        if not self._suscrito:
            self.vm.state_changed.connect(self.actualizar)
            self._suscrito = True
        self.actualizar(self.vm.state)
        self.show()
        self.raise_()

    def ocultar(self) -> None:
        if self._suscrito:
            try:
                self.vm.state_changed.disconnect(self.actualizar)
            except (RuntimeError, TypeError):
                pass
            self._suscrito = False
        self.hide()

    # --- arrastre con el ratón ---
    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._arrastre = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e) -> None:
        if self._arrastre is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._arrastre)
            e.accept()

    def mouseReleaseEvent(self, e) -> None:
        self._arrastre = None

    def closeEvent(self, e) -> None:
        self.ocultar()
        super().closeEvent(e)
