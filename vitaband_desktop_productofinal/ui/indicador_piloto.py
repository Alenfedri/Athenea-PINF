"""Velocímetro horizontal del piloto automático de zona: banda objetivo, aguja del pulso y mensaje."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

COLORES = {"sube": "#2E86DE", "clavado": "#2ECC40", "frena": "#E8231A",
           "desactivado": "#8A8A8A", "sin_dato": "#8A8A8A"}


class IndicadorPiloto(QWidget):

    def __init__(self, oscuro: bool = False, parent=None):
        super().__init__(parent)
        self.oscuro = oscuro
        self.setMinimumHeight(54)
        self.resultado = None
        self.bpm: Optional[float] = None
        self.fc_max = 190.0

    def mostrar(self, resultado, bpm: Optional[float], fc_max: float) -> None:
        self.resultado, self.bpm, self.fc_max = resultado, bpm, fc_max
        self.update()

    @property
    def estado(self) -> str:
        return "desactivado" if self.resultado is None else self.resultado.estado

    @property
    def texto(self) -> str:
        return "Desactivado" if self.resultado is None else self.resultado.texto

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        frente = QColor("#FFFFFF" if self.oscuro else "#202020")
        color = QColor(COLORES.get(self.estado, "#8A8A8A"))
        f = QFont()
        f.setBold(True)
        f.setPixelSize(max(14, int(h * 0.38)))
        p.setFont(f)
        p.setPen(color)
        p.drawText(QRectF(0, 0, w, h * 0.5), int(Qt.AlignmentFlag.AlignCenter), self.texto)
        barra = QRectF(10, h * 0.62, w - 20, h * 0.18)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#3A3A3A" if self.oscuro else "#D8D8D8"))
        p.drawRoundedRect(barra, 5, 5)
        r = self.resultado
        if r is not None and r.rango is not None:
            lo, hi = r.rango
            margen = max(15.0, 0.5 * (hi - lo))
            a, b = lo - margen, hi + margen
            x = lambda v: barra.x() + barra.width() * max(0.0, min(1.0, (v - a) / (b - a)))
            p.setBrush(QColor("#2ECC40"))
            p.drawRoundedRect(QRectF(x(lo), barra.y(), max(4.0, x(hi) - x(lo)), barra.height()), 5, 5)
            if self.bpm:
                cx = x(self.bpm)
                p.setBrush(frente)
                p.drawPolygon(QPolygonF([QPointF(cx - 6, barra.y() - 9), QPointF(cx + 6, barra.y() - 9),
                                         QPointF(cx, barra.y() - 1)]))
                p.setPen(QPen(frente, 2))
                p.drawLine(int(cx), int(barra.y()), int(cx), int(barra.bottom()))
                p.setPen(frente)
                f.setPixelSize(11)
                f.setBold(False)
                p.setFont(f)
                p.drawText(QRectF(10, barra.bottom() + 1, w - 20, h * 0.2), int(Qt.AlignmentFlag.AlignCenter),
                           f"{self.bpm:.0f} BPM · objetivo {lo:.0f}–{hi:.0f}")
        p.end()
