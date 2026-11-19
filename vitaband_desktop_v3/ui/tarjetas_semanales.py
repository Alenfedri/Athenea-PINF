"""Dashboard semanal: cuatro tarjetas «últimos 7 días vs. 7 anteriores» y el estado de carga."""

from __future__ import annotations

from typing import Optional, Sequence

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from services.metricas_avanzadas import Tarjeta


def _num(v: Optional[float], unidad: str) -> str:
    if v is None:
        return "—"
    return f"{v:.0f}".replace(".", ",") + (f" {unidad}" if unidad else "")


class _TarjetaWidget(QFrame):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        capa = QVBoxLayout(self)
        capa.setContentsMargins(8, 4, 8, 4)
        self.lbl_nombre = QLabel()
        self.lbl_nombre.setStyleSheet("color:#666; font-size: 12px;")
        self.lbl_valor = QLabel("—")
        self.lbl_valor.setStyleSheet("font-size: 22px; font-weight: bold;")
        self.lbl_cambio = QLabel()
        capa.addWidget(self.lbl_nombre)
        capa.addWidget(self.lbl_valor)
        capa.addWidget(self.lbl_cambio)

    def mostrar(self, t: Tarjeta) -> None:
        self.lbl_nombre.setText(t.nombre)
        self.lbl_valor.setText(_num(t.actual, t.unidad))
        d, p = t.delta, t.pct
        if d is None:
            texto = "sin datos para comparar"
        else:
            pct = "" if p is None else f" ({p:+.0f} %)".replace(".", ",")
            texto = f"{t.flecha} {d:+.0f}".replace(".", ",") + (f" {t.unidad}" if t.unidad else "") + pct + " vs. anterior"
        self.lbl_cambio.setText(texto)
        self.lbl_cambio.setStyleSheet(f"color:{t.color}; font-weight: bold;")


class PanelTarjetasSemanales(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        capa = QVBoxLayout(self)
        capa.setContentsMargins(0, 0, 0, 0)
        fila = QHBoxLayout()
        self.tarjetas = [_TarjetaWidget() for _ in range(4)]
        for t in self.tarjetas:
            fila.addWidget(t)
        capa.addLayout(fila)
        self.lbl_carga = QLabel()
        self.lbl_carga.setStyleSheet("font-weight: bold; color: #1a5276;")
        capa.addWidget(self.lbl_carga)

    def mostrar(self, tarjetas: Sequence[Tarjeta], texto_carga: str) -> None:
        for w, t in zip(self.tarjetas, tarjetas):
            w.mostrar(t)
        self.lbl_carga.setText(texto_carga)
