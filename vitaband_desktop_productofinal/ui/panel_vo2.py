"""VO2máx (Uth), nivel por edad y sexo, edad cardiovascular y su evolución mensual."""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from ui.tema_vitaband import ORO_CHAMPAN, TARJETA_PINO

SIN_DATOS = ("VO2máx: N/D. Hace falta FC en reposo (≥ 20 registros en reposo en 30 días) y la edad en "
             "«Perfil fisiológico» (o una FCmáx observada).")


class PanelVo2(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        capa = QVBoxLayout(self)
        capa.setContentsMargins(0, 0, 0, 0)
        self.lbl = QLabel(SIN_DATOS)
        self.lbl.setWordWrap(True)
        self.lbl_evolucion = QLabel("")
        self.grafica = pg.PlotWidget()
        self.grafica.setBackground(TARJETA_PINO)
        self.grafica.setMaximumHeight(130)
        self.grafica.setMouseEnabled(False, False)
        self.grafica.setLabel("left", "Edad CV")
        self.curva = self.grafica.plot(pen=pg.mkPen(ORO_CHAMPAN, width=2), symbol="o", symbolBrush=ORO_CHAMPAN)
        self.grafica.setVisible(False)
        for w in (self.lbl, self.grafica, self.lbl_evolucion):
            capa.addWidget(w)

    def mostrar(self, estimacion, evolucion) -> None:
        self.lbl.setText(SIN_DATOS if estimacion is None
                         else estimacion.texto() + " · Estimación orientativa, no es una prueba de esfuerzo.")
        con_edad = [(i, e.edad_cv) for i, (_, e) in enumerate(evolucion) if e.edad_cv is not None]
        self.grafica.setVisible(len(con_edad) >= 2)
        if len(con_edad) >= 2:
            self.curva.setData([i for i, _ in con_edad], [v for _, v in con_edad])
        self.lbl_evolucion.setText("" if not evolucion else "Evolución mensual: " + " · ".join(
            f"{mes}: {e.vo2:.1f}" + ("" if e.edad_cv is None else f" (CV {e.edad_cv})") for mes, e in evolucion))
