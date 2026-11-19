"""Vista «Antes vs. Ahora»: BPM y RPM de dos sesiones superpuestas en minutos relativos + resumen."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from domain.comparador_sesiones import AHORA, ANTES, Comparativa, SesionComparada
from ui.formato import duracion, fecha_hora

COLOR_AHORA = "#d62728"
COLOR_ANTES = "#7f7f7f"
NOTA = ("Un pulso medio más bajo solo indica mejor forma si el esfuerzo fue equivalente "
        "(misma duración, tipo y ritmo).")


def _n(x: Optional[float], dec: int = 1, signo: bool = False) -> str:
    if x is None:
        return "—"
    return (f"{x:+.{dec}f}" if signo else f"{x:.{dec}f}").replace(".", ",")


def _con_huecos(serie) -> tuple[np.ndarray, np.ndarray]:
    """x, y con un NaN en cada interrupción (separación > 3× la mediana, mínimo 0,5 min)."""
    if not serie:
        return np.empty(0), np.empty(0)
    x = np.array([p[0] for p in serie])
    y = np.array([p[1] for p in serie])
    if len(x) > 2:
        pasos = np.diff(x)
        limite = max(0.5, 3 * float(np.median(pasos[pasos > 0]))) if np.any(pasos > 0) else 0.5
        huecos = np.flatnonzero(pasos > limite)
        x = np.insert(x, huecos + 1, np.nan)
        y = np.insert(y, huecos + 1, np.nan)
    return x, y


class _GraficaMinutos(pg.PlotWidget):
    def __init__(self, etiqueta_y: str, parent=None):
        super().__init__(parent)
        self.showGrid(x=True, y=True, alpha=0.3)
        self.setLabel("left", etiqueta_y)
        self.setLabel("bottom", "Minutos desde el inicio de la sesión")
        self.addLegend(offset=(10, 10))
        self.curva_antes = self.plot(
            pen=pg.mkPen(COLOR_ANTES, width=2, style=Qt.PenStyle.DashLine), name=ANTES, connect="finite")
        self.curva_ahora = self.plot(pen=pg.mkPen(COLOR_AHORA, width=2), name=AHORA, connect="finite")

    def limpiar(self) -> None:
        self.curva_antes.setData([], [])
        self.curva_ahora.setData([], [])

    def mostrar(self, antes, ahora) -> None:
        self.curva_antes.setData(*_con_huecos(antes))
        self.curva_ahora.setData(*_con_huecos(ahora))
        self.setXRange(0, max([0.0] + [p[0] for p in antes] + [p[0] for p in ahora]) or 1.0, padding=0.02)

    @staticmethod
    def datos(curva) -> tuple[np.ndarray, np.ndarray]:
        x, y = curva.getData()
        return (np.empty(0), np.empty(0)) if x is None else (np.asarray(x), np.asarray(y))


class PanelComparador(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        capa = QVBoxLayout(self)
        capa.setContentsMargins(0, 0, 0, 0)
        self.lbl_mensaje = QLabel()
        self.lbl_mensaje.setWordWrap(True)
        self.lbl_mensaje.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.lbl_resumen = QLabel()
        self.lbl_resumen.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_resumen.setWordWrap(True)
        self.grafica_bpm = _GraficaMinutos("Pulso (BPM)")
        self.grafica_rpm = _GraficaMinutos("Respiración (RPM)")
        self.grafica_rpm.setXLink(self.grafica_bpm)
        for w, e in ((self.lbl_mensaje, 0), (self.lbl_resumen, 0), (self.grafica_bpm, 1), (self.grafica_rpm, 1)):
            capa.addWidget(w, stretch=e)
        self.mostrar_mensaje("")

    def mostrar_mensaje(self, texto: str) -> None:
        self.lbl_mensaje.setText(texto)
        self.lbl_mensaje.setVisible(bool(texto))
        self.lbl_resumen.setText("")
        self.lbl_resumen.setVisible(False)
        self.grafica_bpm.limpiar()
        self.grafica_rpm.limpiar()
        self.grafica_bpm.setVisible(False)
        self.grafica_rpm.setVisible(False)

    def mostrar(self, c: Comparativa) -> None:
        self.lbl_mensaje.setVisible(False)
        self.lbl_resumen.setText(self.texto_resumen(c))
        self.lbl_resumen.setVisible(True)
        self.grafica_bpm.setVisible(True)
        self.grafica_rpm.setVisible(True)
        self.grafica_bpm.mostrar(c.antes.bpm, c.ahora.bpm)
        self.grafica_rpm.mostrar(c.antes.rpm, c.ahora.rpm)

    @staticmethod
    def _cabecera(s: SesionComparada) -> str:
        tipo = f" ({s.actividad.tipo})" if s.actividad.tipo else ""
        return f"<b>{s.etiqueta}</b>{tipo}: {fecha_hora(s.actividad.inicio_ts)} · {duracion(s.duracion_s)}"

    @classmethod
    def texto_resumen(cls, c: Comparativa) -> str:
        a, b = c.antes, c.ahora
        filas = [
            ("FC media (BPM)", _n(a.bpm_medio), _n(b.bpm_medio), _n(c.d_bpm_medio, signo=True)),
            ("FC máx. (BPM)", _n(a.bpm_max, 0), _n(b.bpm_max, 0), _n(c.d_bpm_max, 0, True)),
            ("FR media (RPM)", _n(a.rpm_medio), _n(b.rpm_medio), _n(c.d_rpm_medio, signo=True)),
            ("Duración", duracion(a.duracion_s), duracion(b.duracion_s),
             ("+" if c.d_duracion_s >= 0 else "−") + duracion(abs(c.d_duracion_s))),
        ]
        celdas = "".join(
            f"<tr><td>{n}</td><td align='right'>&nbsp;{x}</td><td align='right'>&nbsp;{y}</td>"
            f"<td align='right'>&nbsp;<b>{d}</b></td></tr>" for n, x, y, d in filas)
        return (f"{cls._cabecera(a)}<br>{cls._cabecera(b)}"
                f"<table><tr><th></th><th>&nbsp;{ANTES}</th><th>&nbsp;{AHORA}</th><th>&nbsp;Δ Ahora − Antes</th></tr>"
                f"{celdas}</table><i>{NOTA}</i>")
