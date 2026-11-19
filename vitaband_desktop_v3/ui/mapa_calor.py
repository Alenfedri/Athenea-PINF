"""Mapa de calor de constancia (12 semanas) con objetivo semanal y rachas."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Mapping, Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QProgressBar, QSpinBox, QToolTip, QVBoxLayout, QWidget)

from services import constancia

COLORES = ("#ebedf0", "#c6e48b", "#7bc96f", "#239a3b", "#196127")
CELDA, HUECO = 16, 3


class MapaCalor(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dias: Mapping[date, constancia.DiaActividad] = {}
        self._hoy = date.today()
        self.setMouseTracking(True)
        paso = CELDA + HUECO
        self.setFixedSize(constancia.SEMANAS_MAPA * paso + HUECO, 7 * paso + HUECO)

    def mostrar(self, dias, hoy: date) -> None:
        self._dias, self._hoy = dias, hoy
        self.update()

    def fechas(self) -> list[date]:
        """Días del mapa, de la semana más antigua a hoy."""
        d0 = constancia.primer_dia_mapa(self._hoy)
        return [d0 + timedelta(days=i) for i in range((self._hoy - d0).days + 1)]

    def _celda(self, d: date) -> QRectF:
        col, fila = (d - constancia.primer_dia_mapa(self._hoy)).days // 7, d.weekday()
        paso = CELDA + HUECO
        return QRectF(HUECO + col * paso, HUECO + fila * paso, CELDA, CELDA)

    def nivel_de(self, d: date) -> int:
        v = self._dias.get(d)
        return constancia.nivel(v.minutos) if v else 0

    def texto_dia(self, d: date) -> str:
        v = self._dias.get(d)
        minutos, kcal = (v.minutos, v.kcal) if v else (0.0, 0.0)
        extra = f" · {kcal:.0f} kcal" if kcal else ""
        return f"{d:%d/%m/%Y}: {minutos:.0f} min activos{extra}"

    def fecha_en(self, pos: QPointF) -> Optional[date]:
        for d in self.fechas():
            if self._celda(d).contains(pos):
                return d
        return None

    def paintEvent(self, _evento) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for d in self.fechas():
            p.setBrush(QColor(COLORES[self.nivel_de(d)]))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(self._celda(d), 3, 3)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        d = self.fecha_en(e.position())
        if d is None:
            QToolTip.hideText()
        else:
            QToolTip.showText(e.globalPosition().toPoint(), self.texto_dia(d), self)


class PanelConstancia(QWidget):
    objetivo_cambiado = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        capa = QHBoxLayout(self)
        capa.setContentsMargins(0, 0, 0, 0)
        self.mapa = MapaCalor()
        capa.addWidget(self.mapa)
        der = QVBoxLayout()
        fila = QHBoxLayout()
        fila.addWidget(QLabel("Objetivo semanal"))
        self.spin_objetivo = QSpinBox()
        self.spin_objetivo.setRange(10, 2000)
        self.spin_objetivo.setSingleStep(10)
        self.spin_objetivo.setSuffix(" min")
        self.spin_objetivo.setValue(constancia.OBJETIVO_DEFECTO_MIN)
        self.spin_objetivo.editingFinished.connect(lambda: self.objetivo_cambiado.emit(self.spin_objetivo.value()))
        fila.addWidget(self.spin_objetivo)
        fila.addStretch()
        self.barra = QProgressBar()
        self.barra.setFormat("%v / %m min esta semana")
        self.lbl_racha = QLabel()
        self.lbl_racha.setStyleSheet("font-weight: bold; color: #196127;")
        der.addLayout(fila)
        der.addWidget(self.barra)
        der.addWidget(self.lbl_racha)
        capa.addLayout(der, stretch=1)

    def mostrar(self, datos: dict) -> None:
        self.mapa.mostrar(datos["dias"], datos["hoy"])
        self.spin_objetivo.blockSignals(True)
        self.spin_objetivo.setValue(datos["objetivo"])
        self.spin_objetivo.blockSignals(False)
        self.barra.setMaximum(max(1, datos["objetivo"]))
        self.barra.setValue(int(min(datos["minutos_semana"], datos["objetivo"])))
        self.lbl_racha.setText(f"Racha: {datos['racha_semanas']} semanas cumpliendo el objetivo · "
                               f"{datos['racha_dias']} días seguidos con actividad")
