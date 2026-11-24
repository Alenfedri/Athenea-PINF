"""Coherencia cardíaca: respiración guiada a 6 RPM con la curva real de BPM y RPM en vivo."""

from __future__ import annotations

from typing import Callable, Optional

import pyqtgraph as pg
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from services import coherencia
from ui.modo_entrenamiento import numero


def _mmss(s: float) -> str:
    s = max(0, int(s))
    return f"{s // 60}:{s % 60:02d}"


class DialogoCoherencia(QDialog):

    def __init__(self, vm, reloj: Optional[Callable[[], float]] = None, parent=None):
        super().__init__(parent)
        self.vm = vm
        self._reloj = reloj or vm.tiempo
        self.setWindowTitle("Coherencia cardíaca")
        self.resize(640, 520)
        capa = QVBoxLayout(self)
        fila = QHBoxLayout()
        fila.addWidget(QLabel("Duración:"))
        self.combo_duracion = QComboBox()
        for m in coherencia.DURACIONES_MIN:
            self.combo_duracion.addItem(f"{m} min", m)
        self.btn_iniciar = QPushButton("Iniciar")
        fila.addWidget(self.combo_duracion)
        fila.addWidget(QLabel(f"Ritmo guiado: {coherencia.RPM_GUIA:.0f} RPM (5 s inhalar / 5 s exhalar)"), 1)
        fila.addWidget(self.btn_iniciar)
        capa.addLayout(fila)
        self.lbl_fase = QLabel("Con la banda pectoral conectada, pulsa «Iniciar» y respira al ritmo de la onda.")
        self.lbl_fase.setStyleSheet("font-size: 28px; font-weight: bold;")
        self.lbl_fase.setWordWrap(True)
        self.lbl_tiempo = QLabel("")
        self.lbl_vivo = QLabel("BPM: -- · RPM: --")
        capa.addWidget(self.lbl_fase)
        capa.addWidget(self.lbl_tiempo)
        capa.addWidget(self.lbl_vivo)

        self.grafica = pg.PlotWidget()
        self.grafica.setBackground("w")
        self.grafica.setYRange(-0.05, 1.05)
        self.grafica.setMouseEnabled(False, False)
        self.grafica.addLegend(offset=(10, 5))
        self.curva_objetivo = self.grafica.plot(pen=pg.mkPen("#2980b9", width=3), name="Guía (6 RPM)")
        self.curva_bpm = self.grafica.plot(pen=pg.mkPen("#c0392b", width=2), name="BPM (oscilación)")
        self.curva_rpm = self.grafica.plot(pen=pg.mkPen("#27ae60", width=2, style=pg.QtCore.Qt.PenStyle.DashLine),
                                           name="RPM real (÷12)")
        capa.addWidget(self.grafica, 1)
        self.lbl_resultado = QLabel()
        self.lbl_resultado.setWordWrap(True)
        self.lbl_resultado.setStyleSheet("font-size: 15px;")
        capa.addWidget(self.lbl_resultado)
        self.btn_cerrar = QPushButton("Cerrar")
        capa.addWidget(self.btn_cerrar)
        self.btn_iniciar.clicked.connect(self.iniciar)
        self.btn_cerrar.clicked.connect(self.close)

        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.tick)
        self.en_curso = False
        self.resultado: Optional[coherencia.ResultadoCoherencia] = None
        self._t0 = 0.0
        self._dur_s = 0.0
        self._ultimo_bpm: Optional[float] = None
        self._ultimo_rpm: Optional[float] = None
        self._ts: list[float] = []
        self._obj: list[float] = []
        self._bpm: list[float] = []
        self._rpm: list[float] = []

    def iniciar(self) -> None:
        if self.en_curso:
            return
        self._dur_s = 60.0 * int(self.combo_duracion.currentData())
        self._t0 = self._reloj()
        self._ts, self._obj, self._bpm, self._rpm = [], [], [], []
        self.resultado, self.en_curso = None, True
        self.lbl_resultado.setText("")
        self.btn_iniciar.setEnabled(False)
        self.combo_duracion.setEnabled(False)
        self.vm.iniciar_coherencia()
        self.vm.state_changed.connect(self._on_estado)
        self._timer.start()
        self.tick()

    def _on_estado(self, st) -> None:
        self._ultimo_bpm, self._ultimo_rpm = numero(st.bpmTexto), numero(st.rpmTexto)
        self.lbl_vivo.setText(
            f"BPM: {'--' if self._ultimo_bpm is None else f'{self._ultimo_bpm:.0f}'} · "
            f"RPM: {'--' if self._ultimo_rpm is None else f'{self._ultimo_rpm:.1f}'}")

    def tick(self) -> None:
        if not self.en_curso:
            return
        t = self._reloj() - self._t0
        if t >= self._dur_s:
            self._terminar()
            return
        self.lbl_fase.setText(coherencia.fase(t))
        self.lbl_tiempo.setText(f"Quedan {_mmss(self._dur_s - t)}")
        self._ts.append(t)
        self._obj.append(coherencia.onda_objetivo(t))
        self._bpm.append(self._ultimo_bpm if self._ultimo_bpm is not None else float("nan"))
        self._rpm.append(self._ultimo_rpm if self._ultimo_rpm is not None else float("nan"))
        self._dibujar()

    def _dibujar(self) -> None:
        ventana = 3 * coherencia.periodo_s()
        ini = next((i for i, t in enumerate(self._ts) if t >= self._ts[-1] - ventana), 0)
        ts = self._ts[ini:]
        self.curva_objetivo.setData(ts, self._obj[ini:])
        validos = [b for b in self._bpm[ini:] if b == b]
        if len(validos) >= 2 and max(validos) > min(validos):
            lo, hi = min(validos), max(validos)
            self.curva_bpm.setData(ts, [(b - lo) / (hi - lo) if b == b else float("nan") for b in self._bpm[ini:]])
        self.curva_rpm.setData(ts, [min(1.0, r / 12.0) if r == r else float("nan") for r in self._rpm[ini:]])
        self.grafica.setXRange(ts[0], max(ts[0] + ventana, ts[-1]), padding=0)

    def _desconectar(self) -> None:
        self._timer.stop()
        try:
            self.vm.state_changed.disconnect(self._on_estado)
        except (RuntimeError, TypeError):
            pass

    def _terminar(self) -> None:
        self.en_curso = False
        self._desconectar()
        self.resultado = self.vm.detener_coherencia()
        self.btn_iniciar.setEnabled(True)
        self.combo_duracion.setEnabled(True)
        self.lbl_fase.setText("Sesión terminada")
        self.lbl_tiempo.setText("")
        self.lbl_resultado.setText(self.resultado.texto())
        QApplication.beep()

    def closeEvent(self, e) -> None:
        if self.en_curso:
            self.en_curso = False
            self._desconectar()
            self.vm.detener_coherencia()
        super().closeEvent(e)
