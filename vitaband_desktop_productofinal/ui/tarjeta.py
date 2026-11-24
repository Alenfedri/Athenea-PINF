"""Tarjeta Verde Pino (``card="true"``) reutilizable. El .qss global no define selectores por propiedad,
así que cada tarjeta lleva su propio estilo acotado."""
from PySide6.QtWidgets import QFrame, QVBoxLayout

from ui.tema_vitaband import BORDE_BOSQUE, TARJETA_PINO


def tarjeta(*contenido, margen: int = 16) -> QFrame:
    t = QFrame()
    t.setProperty("card", "true")
    t.setStyleSheet(f'QFrame[card="true"] {{ background-color: {TARJETA_PINO}; border: 1px solid {BORDE_BOSQUE}; '
                    f'border-radius: 14px; }} QFrame[card="true"] QLabel {{ background: transparent; border: none; }}')
    v = QVBoxLayout(t)
    v.setContentsMargins(margen, margen, margen, margen)
    v.setSpacing(4)
    for w in contenido:
        v.addWidget(w)
    return t
