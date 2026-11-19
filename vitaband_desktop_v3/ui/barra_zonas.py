"""Barra horizontal segmentada con el reparto del tiempo por zonas cardíacas (Z1–Z5) y su leyenda."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from domain.zonas_actividad import NOMBRES_ZONAS, RANGOS_ZONAS, ReparticionZonas

COLORES = ("#9bb7d4", "#6cbf6c", "#f2d03b", "#f28c28", "#d93025")
SIN_DATOS = "Zonas cardíacas: sin datos suficientes."


def _minutos(segundos: float) -> str:
    return f"{segundos / 60:.1f}".replace(".", ",")


class _Barra(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(18)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.anchos: tuple[float, ...] = ()           # fracción del ancho de cada zona

    def paintEvent(self, _evento) -> None:
        p = QPainter(self)
        if not self.anchos:
            p.fillRect(self.rect(), QColor("#e0e0e0"))
            return
        x = 0.0
        for fraccion, color in zip(self.anchos, COLORES):
            ancho = fraccion * self.width()
            if ancho > 0:
                p.fillRect(QRectF(x, 0, ancho, self.height()), QColor(color))
            x += ancho


class BarraZonas(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        capa = QVBoxLayout(self)
        capa.setContentsMargins(0, 0, 0, 0)
        capa.setSpacing(2)
        self.barra = _Barra()
        self.lbl_leyenda = QLabel(SIN_DATOS)
        self.lbl_leyenda.setWordWrap(True)
        self.lbl_leyenda.setTextFormat(Qt.TextFormat.RichText)
        capa.addWidget(self.barra)
        capa.addWidget(self.lbl_leyenda)

    @property
    def anchos(self) -> tuple[float, ...]:
        return self.barra.anchos

    def mostrar(self, reparticion: Optional[ReparticionZonas]) -> None:
        if reparticion is None or reparticion.total_s <= 0:
            self.barra.anchos = ()
            self.lbl_leyenda.setText(SIN_DATOS)
            self.barra.update()
            return
        pct = reparticion.porcentajes
        self.barra.anchos = tuple(p / 100.0 for p in pct)
        piezas = [
            f'<span style="color:{c}">■</span> <b>{n}</b> ({rango}) {p:.0f} % · {_minutos(s)} min'
            for n, rango, c, p, s in zip(NOMBRES_ZONAS, RANGOS_ZONAS, COLORES, pct, reparticion.segundos)
        ]
        self.lbl_leyenda.setText(
            f"Zonas cardíacas (FC máx. de referencia {reparticion.fc_max:.0f} BPM): " + " &nbsp; ".join(piezas))
        self.barra.update()
