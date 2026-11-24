"""Gráfica temporal de una variable del historial con interrupciones visibles (RF-14, 16, 27).

* Los periodos sin datos NO se unen con una línea: se cortan y se sombrean.
* En modo agrupado se dibuja la media de cada intervalo con barras de mínimo/máximo.
"""

from __future__ import annotations

from typing import Optional, Sequence

from PySide6.QtCore import Qt, Signal

import numpy as np
import pyqtgraph as pg
from ui.ejes_tiempo import EjeHoras

from domain import analisis
from ui.tema_vitaband import ALFA_REJILLA, CORAL_PULSO, ESMERALDA_BRILLO, ESMERALDA_ECG

COLOR = ESMERALDA_ECG
COLOR_BARRAS = ESMERALDA_BRILLO
MAX_REGIONES = 300


COLOR_MARCADOR = CORAL_PULSO


class GraficaSerie(pg.PlotWidget):

    # Clic sobre la gráfica: (ts, posición global en pantalla)
    clic_en_tiempo = Signal(float, object)

    def __init__(self, parent=None):
        super().__init__(parent, axisItems={"bottom": EjeHoras()})
        self.showGrid(x=True, y=True, alpha=ALFA_REJILLA)
        self._curva = self.plot(
            pen=pg.mkPen(COLOR, width=1.5), symbol="o", symbolSize=4,
            symbolBrush=COLOR, symbolPen=None, connect="finite",
        )
        self._barras = pg.ErrorBarItem(pen=pg.mkPen(COLOR_BARRAS, width=1))
        self.addItem(self._barras)
        self._regiones: list[pg.LinearRegionItem] = []
        self._marcadores: list = []
        self._ts_marcadores: list[int] = []
        self.scene().sigMouseClicked.connect(self._on_clic)
        self.limpiar()

    # ------------------------------------------------------------------
    # Marcadores de contexto
    # ------------------------------------------------------------------

    def _on_clic(self, evento) -> None:
        if evento.button() != Qt.MouseButton.LeftButton or evento.double():
            return
        vista = self.getPlotItem().vb
        if not vista.sceneBoundingRect().contains(evento.scenePos()):
            return
        ts = vista.mapSceneToView(evento.scenePos()).x()
        self.clic_en_tiempo.emit(float(ts), evento.screenPos())

    def marcador_cercano(self, ts: float, tolerancia_px: int = 12) -> Optional[int]:
        """ts del marcador más próximo al instante clicado (dentro de unos píxeles), o None."""
        if not self._ts_marcadores:
            return None
        ancho_x = self.getPlotItem().vb.viewRange()[0]
        px = max(self.getPlotItem().vb.width(), 1.0)
        tol_s = (ancho_x[1] - ancho_x[0]) / px * tolerancia_px
        mejor = min(self._ts_marcadores, key=lambda t: abs(t - ts))
        return mejor if abs(mejor - ts) <= tol_s else None

    def mostrar_marcadores(self, marcadores: Sequence[tuple[int, str]]) -> None:
        for item in self._marcadores:
            self.removeItem(item)
        self._marcadores = []
        self._ts_marcadores = [ts for ts, _ in marcadores]
        for ts, etiqueta in marcadores:
            linea = pg.InfiniteLine(
                pos=ts, angle=90, movable=False, pen=pg.mkPen(COLOR_MARCADOR, width=1, style=Qt.PenStyle.DashLine),
                label=etiqueta, labelOpts={"position": 0.95, "color": COLOR_MARCADOR, "rotateAxis": (1, 0)})
            linea.setZValue(5)
            self.addItem(linea)
            self._marcadores.append(linea)

    @property
    def marcadores(self) -> int:
        return len(self._marcadores)

    # ------------------------------------------------------------------

    def limpiar(self) -> None:
        self._curva.setData([], [])
        self._barras.setData(x=None, y=None)
        self._quitar_regiones()

    def _quitar_regiones(self) -> None:
        for r in self._regiones:
            self.removeItem(r)
        self._regiones = []

    @property
    def regiones(self) -> int:
        return len(self._regiones)

    @property
    def puntos(self) -> int:
        x, _ = self._curva.getData()
        return 0 if x is None else int(len(x))

    @property
    def tiene_barras(self) -> bool:
        return self._barras.opts.get("x") is not None

    # ------------------------------------------------------------------

    def _titular(self, variable: str) -> None:
        unidad = analisis.UNIDAD_VARIABLE[variable]
        etiqueta = analisis.NOMBRE_VARIABLE[variable] + (f" ({unidad})" if unidad else "")
        self.setLabel("left", etiqueta)

    def _sombrear(self, interrupciones: Sequence[analisis.Interrupcion]) -> None:
        self._quitar_regiones()
        # Si hay demasiadas, se sombrean las más largas para no saturar la escena
        elegidas = sorted(interrupciones, key=lambda i: -i.duracion_s)[:MAX_REGIONES]
        for i in elegidas:
            r = pg.LinearRegionItem(
                values=(i.inicio, i.fin), movable=False, brush=pg.mkBrush(255, 140, 0, 50))
            for linea in r.lines:
                linea.setPen(pg.mkPen(None))
            r.setZValue(-10)
            self.addItem(r)
            self._regiones.append(r)

    # ------------------------------------------------------------------

    def mostrar_serie(self, serie) -> None:
        """Dibuja una ``SerieHistorica`` del servicio de consultas."""
        self._titular(serie.variable)
        if serie.agrupada:
            self._dibujar_cubos(serie.cubos)
        else:
            self._dibujar_pares(serie.pares, serie.umbral_interrupcion_s)
        self._sombrear(serie.interrupciones)
        self.setXRange(serie.desde_ts, serie.hasta_ts, padding=0.01)

    def mostrar_pares(
        self,
        variable: str,
        pares: Sequence[tuple[int, float]],
        interrupciones: Sequence[analisis.Interrupcion],
        umbral_s: float,
        desde_ts: int,
        hasta_ts: int,
    ) -> None:
        """Dibuja (ts, valor) sueltos, p. ej. los de una actividad."""
        self._titular(variable)
        self._dibujar_pares(pares, umbral_s)
        self._sombrear(interrupciones)
        self.setXRange(desde_ts, hasta_ts, padding=0.02)

    def _dibujar_pares(self, pares, umbral_s: float) -> None:
        self._barras.setData(x=None, y=None)
        xs, ys = analisis.serie_con_huecos(pares, umbral_s)
        self._curva.setData(np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64))

    def _dibujar_cubos(self, cubos: Sequence[analisis.Cubo]) -> None:
        if not cubos:
            self.limpiar()
            return
        centros = np.array([(c.inicio + c.fin) / 2 for c in cubos], dtype=np.float64)
        medias = np.array([np.nan if c.vacio else c.media for c in cubos], dtype=np.float64)
        self._curva.setData(centros, medias)

        con_datos = [c for c in cubos if not c.vacio]
        if not con_datos:
            self._barras.setData(x=None, y=None)
            return
        m = np.array([c.media for c in con_datos])
        self._barras.setData(
            x=np.array([(c.inicio + c.fin) / 2 for c in con_datos], dtype=np.float64),
            y=m,
            top=np.array([c.maximo for c in con_datos]) - m,
            bottom=m - np.array([c.minimo for c in con_datos]),
            beam=0.15 * (cubos[0].fin - cubos[0].inicio),
        )
