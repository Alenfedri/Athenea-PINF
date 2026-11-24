"""Scroll vertical fluido: el contenido se desplaza y las gráficas no capturan la rueda (Ctrl + rueda = zoom)."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QFrame, QGraphicsView, QScrollArea, QWidget

ESTILO_SCROLL = (
    "QScrollArea { background: transparent; border: none; } "
    "QScrollArea > QWidget > QWidget { background: transparent; } "
    "QScrollBar:vertical { background: #0B1713; width: 12px; margin: 0; } "
    "QScrollBar::handle:vertical { background: #264B3F; border-radius: 5px; min-height: 36px; } "
    "QScrollBar::handle:vertical:hover { background: #10B981; } "
    "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; } "
    "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }"
)


class _FiltroRueda(QObject):
    """Sin Ctrl, la rueda sobre un lienzo mueve la página; con Ctrl llega al lienzo (zoom)."""

    def __init__(self, scroll: QScrollArea):
        super().__init__(scroll)
        self._scroll = scroll

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Wheel and not (ev.modifiers() & Qt.KeyboardModifier.ControlModifier):
            barra = self._scroll.verticalScrollBar()
            barra.setValue(barra.value() - int(ev.angleDelta().y() / 120 * barra.singleStep() * 3))
            return True
        return False


def crear_scroll(contenido: QWidget) -> QScrollArea:
    s = QScrollArea()
    s.setWidgetResizable(True)
    s.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    s.setFrameShape(QFrame.Shape.NoFrame)
    s.setStyleSheet(ESTILO_SCROLL)
    s.setWidget(contenido)
    s._filtro_rueda = _FiltroRueda(s)
    return s


def redirigir_rueda(scroll: QScrollArea, raiz: QWidget | None = None) -> None:
    """Instala el filtro en todos los lienzos (QGraphicsView) bajo ``raiz`` (por defecto, el contenido)."""
    raiz = raiz or scroll.widget()
    for vista in raiz.findChildren(QGraphicsView):
        for w in (vista, vista.viewport()):
            w.installEventFilter(scroll._filtro_rueda)
