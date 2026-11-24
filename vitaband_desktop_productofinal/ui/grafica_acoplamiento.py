"""Acoplamiento pulso-respiración en vivo: onda respiratoria (de las RPM) sobre la variación del pulso."""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from ui.tema_vitaband import CORAL_PULSO, ESMERALDA_BRILLO, TARJETA_PINO


class GraficaAcoplamiento(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        capa = QVBoxLayout(self)
        capa.setContentsMargins(0, 0, 0, 0)
        self.lbl = QLabel("Acoplamiento pulso-respiración: reúne ~20 s de pulso y respiración con la banda conectada.")
        self.lbl.setWordWrap(True)
        self.grafica = pg.PlotWidget()
        self.grafica.setBackground(TARJETA_PINO)
        self.grafica.setMinimumHeight(120)
        self.grafica.setMaximumHeight(170)
        self.grafica.setMouseEnabled(False, False)
        self.grafica.setLabel("left", "Δ BPM")
        self.grafica.setLabel("bottom", "s")
        self.grafica.addLegend(offset=(10, 5))
        self.curva_resp = self.grafica.plot(pen=pg.mkPen(ESMERALDA_BRILLO, width=2), name="Fase respiratoria (RPM)")
        self.curva_bpm = self.grafica.plot(pen=pg.mkPen(CORAL_PULSO, width=2), name="Pulso (BPM)")
        capa.addWidget(self.lbl)
        capa.addWidget(self.grafica)

    def mostrar(self, ondas, resultado) -> None:
        t, resp, bpm = ondas
        if not t or resultado is None:
            self.curva_resp.setData([], [])
            self.curva_bpm.setData([], [])
            self.lbl.setText("Acoplamiento pulso-respiración: reúne ~20 s de pulso y respiración con la banda conectada.")
            return
        self.curva_resp.setData(t, resp)
        self.curva_bpm.setData(t, bpm)
        self.lbl.setText(f"Sincronización pulso-respiración: {resultado.indice:.0f} % · oscilación "
                         f"{resultado.amplitud_bpm:.1f} bpm · {resultado.texto}")
