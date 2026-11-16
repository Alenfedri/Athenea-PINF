"""Panel de observaciones orientativas guardadas (RF-23..25, 29, 47..49)."""

from __future__ import annotations

from typing import Sequence

from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from domain.modelos import ObservacionGuardada
from domain.observaciones import DESCARGO
from ui.formato import fecha_hora_corta

MAX_MOSTRADAS = 200


def _titulo(o: ObservacionGuardada) -> str:
    if o.tipo == "DIARIA":
        return f"Día {o.clave[8:10]}/{o.clave[5:7]}/{o.clave[:4]}"
    return f"Actividad del {fecha_hora_corta(o.periodo_inicio_ts)}"


class PanelObservaciones(QWidget):

    def __init__(self, titulo: str = "Observaciones", parent=None):
        super().__init__(parent)
        capa = QVBoxLayout(self)
        capa.setContentsMargins(0, 0, 0, 0)

        self.lbl_titulo = QLabel(titulo)
        self.lbl_titulo.setStyleSheet("font-weight: bold;")
        self.texto_edit = QPlainTextEdit()
        self.texto_edit.setReadOnly(True)
        self.lbl_descargo = QLabel(DESCARGO)
        self.lbl_descargo.setWordWrap(True)
        self.lbl_descargo.setStyleSheet("font-style: italic; color: #555;")
        capa.addWidget(self.lbl_titulo)
        capa.addWidget(self.texto_edit, stretch=1)
        capa.addWidget(self.lbl_descargo)

    def texto(self) -> str:
        return self.texto_edit.toPlainText()

    def mostrar(
        self,
        observaciones: Sequence[ObservacionGuardada],
        vacio: str = "Sin observaciones para este periodo.",
    ) -> None:
        if not observaciones:
            self.texto_edit.setPlainText(vacio)
            return

        bloques = []
        for o in observaciones[:MAX_MOSTRADAS]:
            # El descargo se muestra una sola vez, fijo bajo el panel
            lineas = [l for l in o.lineas if l != DESCARGO]
            bloques.append(_titulo(o) + "\n" + "\n".join("  • " + l for l in lineas))
        if len(observaciones) > MAX_MOSTRADAS:
            bloques.append(f"… y {len(observaciones) - MAX_MOSTRADAS} más antiguas.")
        self.texto_edit.setPlainText("\n\n".join(bloques))
