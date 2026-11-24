"""Aviso limpio y centrado sobre una gráfica sin datos (sesiones parciales del móvil)."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QLabel, QWidget

ECG_NO_DISPONIBLE = "Datos ECG crudos no disponibles en esta sesión"
TERMICO_NO_DISPONIBLE = "Datos térmicos no disponibles en esta sesión"


class AvisoCentrado(QLabel):
    """Etiqueta superpuesta y centrada en `destino`; se recoloca sola al redimensionar."""

    def __init__(self, destino: QWidget):
        super().__init__(destino)
        self._destino = destino
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setStyleSheet("background: rgba(9, 14, 12, 235); color: #CBD5E1; font-size: 14px; "
                           "border: 1px solid #1B4D3E; border-radius: 10px; padding: 10px 16px;")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        destino.installEventFilter(self)
        self.hide()

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:
        if obj is self._destino and ev.type() in (QEvent.Type.Resize, QEvent.Type.Show) and self.isVisible():
            self._colocar()
        return False

    def _colocar(self) -> None:
        ancho = min(max(self._destino.width() - 40, 160), 460)
        self.setFixedWidth(ancho)
        self.adjustSize()
        self.move((self._destino.width() - self.width()) // 2, (self._destino.height() - self.height()) // 2)
        self.raise_()

    def mostrar(self, texto: str) -> None:
        self.setText(texto)
        self.show()
        self._colocar()

    def ocultar(self) -> None:
        self.hide()
