"""Pulso (BPM) y respiración (RPM) de una actividad sobre el mismo eje de tiempo, con el umbral de fatiga."""

from __future__ import annotations

from typing import Optional, Sequence

import numpy as np
import pyqtgraph as pg

from domain import analisis
from domain.modelos import Medicion
from domain.zonas_actividad import UmbralFatiga

COLOR_BPM = "#d62728"
COLOR_RPM = "#1f77b4"
COLOR_UMBRAL = "#6a1b9a"


class GraficaCruce(pg.PlotWidget):

    def __init__(self, parent=None):
        super().__init__(parent, axisItems={"bottom": pg.DateAxisItem(orientation="bottom")})
        item = self.getPlotItem()
        item.showGrid(x=True, y=True, alpha=0.3)
        item.setLabel("left", "Pulso (BPM)", color=COLOR_BPM)
        item.showAxis("right")
        item.setLabel("right", "Respiración (RPM)", color=COLOR_RPM)

        self._curva_bpm = item.plot(pen=pg.mkPen(COLOR_BPM, width=1.5), connect="finite")
        # La respiración va en un segundo eje vertical, sincronizado en el tiempo
        self._vista_rpm = pg.ViewBox()
        item.scene().addItem(self._vista_rpm)
        item.getAxis("right").linkToView(self._vista_rpm)
        self._vista_rpm.setXLink(item)
        self._curva_rpm = pg.PlotCurveItem(pen=pg.mkPen(COLOR_RPM, width=1.5), connect="finite")
        self._vista_rpm.addItem(self._curva_rpm)
        item.vb.sigResized.connect(self._ajustar_vista_rpm)
        self._ajustar_vista_rpm()

        self._linea: Optional[pg.InfiniteLine] = None
        self._texto = pg.TextItem("", anchor=(0.5, 0.5), color="#555")
        self.addItem(self._texto)
        self.limpiar()

    def _ajustar_vista_rpm(self) -> None:
        self._vista_rpm.setGeometry(self.getPlotItem().vb.sceneBoundingRect())
        self._vista_rpm.linkedViewChanged(self.getPlotItem().vb, self._vista_rpm.XAxis)

    # ------------------------------------------------------------------

    @property
    def puntos_bpm(self) -> int:
        _, y = self._curva_bpm.getData()
        return 0 if y is None else int(np.isfinite(y).sum())

    @property
    def puntos_rpm(self) -> int:
        x, y = self._curva_rpm.getData()
        return 0 if y is None else int(np.isfinite(y).sum())

    @property
    def linea_umbral(self) -> Optional[pg.InfiniteLine]:
        return self._linea

    @property
    def etiqueta_umbral(self) -> str:
        return "" if self._linea is None else self._linea.label.toPlainText()

    @property
    def mensaje(self) -> str:
        return self._texto.toPlainText()

    def limpiar(self) -> None:
        self._curva_bpm.setData([], [])
        self._curva_rpm.setData([], [])
        self._quitar_linea()
        self._texto.setText("")

    def _quitar_linea(self) -> None:
        if self._linea is not None:
            self.removeItem(self._linea)
            self._linea = None

    def mostrar(
        self,
        mediciones: Sequence[Medicion],
        desde_ts: int,
        hasta_ts: int,
        umbral: Optional[UmbralFatiga],
        motivo: str = "",
    ) -> None:
        self.limpiar()
        gap = analisis.umbral_interrupcion([m.ts for m in mediciones], 5) if mediciones else 0
        bpm = analisis.serie_con_huecos([(m.ts, m.bpm) for m in mediciones if m.bpm], gap)
        rpm = analisis.serie_con_huecos([(m.ts, m.rpm) for m in mediciones if m.rpm], gap)
        self._curva_bpm.setData(np.asarray(bpm[0], dtype=np.float64), np.asarray(bpm[1], dtype=np.float64))
        self._curva_rpm.setData(np.asarray(rpm[0], dtype=np.float64), np.asarray(rpm[1], dtype=np.float64))
        self.setXRange(desde_ts, hasta_ts, padding=0.02)

        if umbral is not None:
            self._linea = pg.InfiniteLine(
                pos=umbral.ts, angle=90, pen=pg.mkPen(COLOR_UMBRAL, width=2, style=pg.QtCore.Qt.PenStyle.DashLine),
                label=umbral.texto,
                labelOpts={"position": 0.92, "color": COLOR_UMBRAL, "rotateAxis": (1, 0),
                           "fill": pg.mkBrush(255, 255, 255, 200)},
            )
            self.addItem(self._linea)
        elif motivo:
            self._texto.setText(motivo)
            self._texto.setPos((desde_ts + hasta_ts) / 2, self._vista_y_central())

    def _vista_y_central(self) -> float:
        (_, _), (y0, y1) = self.getPlotItem().vb.viewRange()
        return (y0 + y1) / 2
