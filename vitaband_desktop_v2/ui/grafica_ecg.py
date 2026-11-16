"""ECG histórico compacto (RF-33, 34): envolvente mínimo/máximo por intervalo de tiempo.

No es la señal completa a 100 Hz, sino su resumen: permite ver la forma general y
los periodos sin señal, no la morfología de cada latido.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Signal

from domain.ecg_historico import EcgReducido

COLOR = "#2a9d8f"


MIN_SELECCION_S = 5


class GraficaEcg(pg.PlotWidget):
    """Con ``con_seleccion=True`` incluye un intervalo arrastrable para ampliarlo (RF-35)."""

    region_cambiada = Signal(int, int)          # (desde_ts, hasta_ts) al soltar el ratón

    def __init__(self, parent=None, titulo: str = "ECG histórico", con_seleccion: bool = False):
        super().__init__(parent, axisItems={"bottom": pg.DateAxisItem(orientation="bottom")})
        self._titulo = titulo
        self.showGrid(x=True, y=True, alpha=0.3)
        self.setLabel("left", "ECG (ADC)")
        self.region: Optional[pg.LinearRegionItem] = None
        self._limites = (None, None)
        if con_seleccion:
            # El desplazamiento y el zoom se hacen con la región y los botones del panel
            self.setMouseEnabled(x=False, y=False)
            self.setMenuEnabled(False)
            self.region = pg.LinearRegionItem(values=(0, 1), movable=True, brush=pg.mkBrush(42, 157, 143, 45))
            self.region.setZValue(10)
            self.region.hide()
            self.addItem(self.region)
            self.region.sigRegionChangeFinished.connect(self._on_region_soltada)
        # Segmentos verticales (mín -> máx) por intervalo; los huecos quedan en blanco
        self._envolvente = pg.PlotCurveItem(pen=pg.mkPen(COLOR, width=2), connect="pairs")
        self.addItem(self._envolvente)
        self._puntos = 0
        self.mostrar(None, 0, 1)

    @property
    def intervalos_dibujados(self) -> int:
        return self._puntos

    # --- Intervalo seleccionable (RF-35) ---

    def seleccion(self) -> Optional[tuple[int, int]]:
        if self.region is None or not self.region.isVisible():
            return None
        a, b = self.region.getRegion()
        return int(round(a)), int(round(b))

    def fijar_seleccion(self, desde_ts: int, hasta_ts: int) -> None:
        """Mueve el intervalo por código (no emite ``region_cambiada``)."""
        if self.region is None:
            return
        self._colocar_region(desde_ts, hasta_ts)
        self.region.show()

    def _colocar_region(self, a: int, b: int) -> None:
        """Mueve la región sin emitir señales ni dejar que los límites anteriores la recorten."""
        self.region.blockSignals(True)
        try:
            self.region.setBounds((None, None))
            self.region.setRegion((a, b))
            self.region.setBounds(self._limites)
        finally:
            self.region.blockSignals(False)

    def ocultar_seleccion(self) -> None:
        if self.region is not None:
            self.region.hide()

    def _on_region_soltada(self) -> None:
        a, b = self.seleccion() or (0, 0)
        if b - a < MIN_SELECCION_S:                     # un intervalo casi nulo no se puede ampliar
            centro = (a + b) // 2
            a, b = centro - MIN_SELECCION_S // 2, centro - MIN_SELECCION_S // 2 + MIN_SELECCION_S
            self.fijar_seleccion(a, b)
        self.region_cambiada.emit(a, b)

    def mostrar(
        self,
        reducido: Optional[EcgReducido],
        desde_ts: int,
        hasta_ts: int,
        mensaje: Optional[str] = None,
    ) -> None:
        self._puntos = 0
        self._envolvente.setData([], [])

        if mensaje:
            self.ocultar_seleccion()
            self.setTitle(mensaje)
            return
        if reducido is None or not reducido.tiene_datos:
            self.ocultar_seleccion()
            self.setTitle(f"{self._titulo}: sin datos en este periodo")
            return
        if self.region is not None:
            self._limites = (desde_ts, hasta_ts)
            # Región actual fuera del nuevo rango: se recoloca antes de fijar los límites
            a, b = self.region.getRegion()
            if a < desde_ts or b > hasta_ts or b - a < 1:
                self._colocar_region(desde_ts, min(hasta_ts, desde_ts + MIN_SELECCION_S))
            else:
                self.region.blockSignals(True)
                self.region.setBounds(self._limites)
                self.region.blockSignals(False)

        validos = ~np.isnan(reducido.minimo)
        x = reducido.x[validos]
        mn = reducido.minimo[validos]
        mx = np.maximum(reducido.maximo[validos], mn + 1)       # un segmento de longitud 0 no se vería
        self._puntos = int(len(x))
        self._envolvente.setData(np.repeat(x, 2), np.column_stack((mn, mx)).ravel())
        self.setTitle(f"{self._titulo} (envolvente mín/máx) · {reducido.segundos_con_dato} s con señal")
        self.setXRange(desde_ts, hasta_ts, padding=0.01)
