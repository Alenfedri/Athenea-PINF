"""Tarjeta flotante discreta del Susurrador en vivo (Tiempo Real): consejo en lenguaje sencillo, con botón silenciar."""
from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

AUTO_OCULTAR_MS = 30_000


class TarjetaSusurro(QFrame):
    silenciado = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("susurro")
        self.setStyleSheet("QFrame#susurro { background-color: #090E0C; border: 1px solid #D4AF37; border-radius: 14px; } "
                           "QLabel { color: #F2F6F4; font-size: 14px; background: transparent; border: none; }")
        self.setFixedWidth(380)
        self.lbl_texto = QLabel()
        self.lbl_texto.setWordWrap(True)
        self.btn_silenciar = QPushButton("Silenciar")
        self.btn_silenciar.setStyleSheet("color:#D4AF37; border:1px solid #D4AF37; border-radius:8px; padding:3px 12px; "
                                         "background:transparent; min-height:24px;")
        titulo = QLabel("Tu coach susurra…")
        titulo.setStyleSheet("color:#D4AF37; font-weight:bold; font-size:13px;")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 10)
        fila = QHBoxLayout()
        fila.addWidget(titulo, 1)
        fila.addWidget(self.btn_silenciar)
        v.addLayout(fila)
        v.addWidget(self.lbl_texto)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(AUTO_OCULTAR_MS)
        self._timer.timeout.connect(self.hide)
        self.btn_silenciar.clicked.connect(self._silenciar)
        self.setVisible(False)

    def mostrar(self, texto: str) -> None:
        self.lbl_texto.setText(texto)
        self.adjustSize()
        p = self.parentWidget()
        if p is not None:
            self.move(max(8, p.width() - self.width() - 16), max(8, p.height() - self.height() - 48))
        self.show()
        self.raise_()
        self._timer.start()

    def _silenciar(self) -> None:
        self.hide()
        self.silenciado.emit()

    def detener(self) -> None:
        self._timer.stop()
        self.hide()

    def hideEvent(self, ev) -> None:
        self._timer.stop()
        super().hideEvent(ev)
