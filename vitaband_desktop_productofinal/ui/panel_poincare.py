"""Diagrama de Poincaré (RR n frente a RR n+1) con SD1, SD2 y latidos atípicos marcados."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from services.poincare import Poincare
from ui.tema_vitaband import ESMERALDA_BRILLO, ORO_CHAMPAN, TARJETA_PINO, TEXTO_SALVIA


class PanelPoincare(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        capa = QVBoxLayout(self)
        capa.setContentsMargins(0, 0, 0, 0)
        self.lbl = QLabel("Sin intervalos R-R en este periodo.")
        self.lbl.setWordWrap(True)
        self.grafica = pg.PlotWidget()
        self.grafica.setBackground(TARJETA_PINO)
        self.grafica.setLabel("bottom", "RR n (ms)")
        self.grafica.setLabel("left", "RR n+1 (ms)")
        self.grafica.setAspectLocked(True)
        self.grafica.setMinimumHeight(220)
        self.diagonal = self.grafica.plot(pen=pg.mkPen(TEXTO_SALVIA, style=pg.QtCore.Qt.PenStyle.DashLine))
        self.puntos = pg.ScatterPlotItem(size=5, brush=pg.mkBrush(16, 185, 129, 150), pen=None)
        self.atipicos = pg.ScatterPlotItem(size=8, brush=pg.mkBrush(244, 63, 94, 230), pen=None, symbol="x")
        self.eje_sd1 = self.grafica.plot(pen=pg.mkPen(ORO_CHAMPAN, width=3))
        self.eje_sd2 = self.grafica.plot(pen=pg.mkPen(ESMERALDA_BRILLO, width=3))
        self.grafica.addItem(self.puntos)
        self.grafica.addItem(self.atipicos)
        capa.addWidget(self.lbl)
        capa.addWidget(self.grafica)
        self.datos: Optional[Poincare] = None

    def mostrar(self, p: Optional[Poincare]) -> None:
        self.datos = p
        if p is None or (p.n == 0 and p.n_atipicos == 0):
            self.puntos.setData([], [])
            self.atipicos.setData([], [])
            for c in (self.diagonal, self.eje_sd1, self.eje_sd2):
                c.setData([], [])
            self.lbl.setText("Sin intervalos R-R en este periodo (se guardan con la banda conectada y señal limpia).")
            return
        self.puntos.setData(list(p.x), list(p.y))
        self.atipicos.setData(list(p.atipicos_x), list(p.atipicos_y))
        todos = list(p.x) + list(p.atipicos_x) + list(p.y) + list(p.atipicos_y)
        lo, hi = min(todos) - 20, max(todos) + 20
        self.diagonal.setData([lo, hi], [lo, hi])
        if p.sd1 is not None and p.sd2 is not None and p.n:
            cx, cy = float(np.mean(p.x)), float(np.mean(p.y))
            k = 1 / np.sqrt(2)
            self.eje_sd2.setData([cx - p.sd2 * k, cx + p.sd2 * k], [cy - p.sd2 * k, cy + p.sd2 * k])
            self.eje_sd1.setData([cx + p.sd1 * k, cx - p.sd1 * k], [cy - p.sd1 * k, cy + p.sd1 * k])
        else:
            self.eje_sd1.setData([], [])
            self.eje_sd2.setData([], [])
        self.lbl.setText(p.texto() + "  (dorada = SD1, verde = SD2, ✕ rojas = latidos atípicos o artefactos)")
