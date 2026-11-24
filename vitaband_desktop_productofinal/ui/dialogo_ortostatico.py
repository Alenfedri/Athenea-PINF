"""Test ortostático guiado de 3 min: 2 min en reposo y 1 min de pie, con temporizador en vivo."""

from __future__ import annotations

import time
from typing import Callable, Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QVBoxLayout

from services import calculos_fisiologicos as calc
from ui.modo_entrenamiento import numero

INSTRUCCION = {0: "Fase 1 · En reposo (0:00–2:00): túmbate o siéntate quieto y respira con normalidad.",
               1: "Fase 2 · De pie (2:00–3:00): ponte de pie ahora y quédate quieto."}


def _mmss(s: float) -> str:
    s = max(0, int(s))
    return f"{s // 60}:{s % 60:02d}"


class DialogoOrtostatico(QDialog):

    def __init__(self, vm, reloj: Optional[Callable[[], float]] = None, parent=None):
        super().__init__(parent)
        self.vm = vm
        self._reloj = reloj or vm.tiempo
        self.setWindowTitle("Test ortostático (3 min)")
        capa = QVBoxLayout(self)
        self.lbl_fase = QLabel("Con la banda pectoral colocada y conectada, pulsa «Iniciar». Dura 3 minutos.")
        self.lbl_fase.setWordWrap(True)
        self.lbl_fase.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.lbl_tiempo = QLabel("0:00 / 3:00")
        self.lbl_tiempo.setStyleSheet("font-size: 48px; font-weight: bold;")
        self.lbl_fc = QLabel("FC: --")
        self.lbl_resultado = QLabel()
        self.lbl_resultado.setWordWrap(True)
        self.btn_iniciar = QPushButton("Iniciar")
        self.btn_cerrar = QPushButton("Cerrar")
        for w in (self.lbl_fase, self.lbl_tiempo, self.lbl_fc, self.lbl_resultado, self.btn_iniciar, self.btn_cerrar):
            capa.addWidget(w)
        self.btn_iniciar.clicked.connect(self.iniciar)
        self.btn_cerrar.clicked.connect(self.close)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.tick)
        self.en_curso = False
        self.resultado: Optional[calc.ResultadoOrtostatico] = None
        self._bpm: list[tuple[float, float]] = []
        self._fase = 0
        self._t0 = 0.0
        self._inicio_ts = 0

    def iniciar(self) -> None:
        if self.en_curso:
            return
        self._t0, self._inicio_ts = self._reloj(), int(time.time())
        self._bpm, self.resultado, self._fase, self.en_curso = [], None, 0, True
        self.lbl_resultado.setText("")
        self.btn_iniciar.setEnabled(False)
        self.vm.iniciar_captura_ecg()
        self.vm.state_changed.connect(self._on_estado)
        self.lbl_fase.setText(INSTRUCCION[0])
        self._timer.start()
        self.tick()

    def _on_estado(self, st) -> None:
        bpm = numero(st.bpmTexto)
        if bpm is not None and self.en_curso:
            self._bpm.append((self._reloj() - self._t0, bpm))
            self.lbl_fc.setText(f"FC: {bpm:.0f} BPM")

    def tick(self) -> None:
        if not self.en_curso:
            return
        t = self._reloj() - self._t0
        fase = calc.fase_ortostatica(t)
        self.lbl_tiempo.setText(f"{_mmss(t)} / 3:00")
        if fase != self._fase:
            self._fase = fase
            QApplication.beep()                                  # aviso de cambio de fase / fin
            if fase == 1:
                self.lbl_fase.setText(INSTRUCCION[1])
        if fase == 2:
            self._terminar()

    def _desconectar(self) -> None:
        self._timer.stop()
        try:
            self.vm.state_changed.disconnect(self._on_estado)
        except (RuntimeError, TypeError):
            pass

    def _terminar(self) -> None:
        self.en_curso = False
        self._desconectar()
        ecg = [(t - self._t0, v) for t, v in self.vm.detener_captura_ecg()]
        self.btn_iniciar.setEnabled(True)
        r = calc.evaluar_ortostatico(self._bpm, ecg)
        if r is None:
            self.lbl_fase.setText("Test terminado sin datos suficientes.")
            self.lbl_resultado.setText("No se recibió FC en los últimos 60 s de reposo o al incorporarte. "
                                       "Comprueba que la banda está conectada y repite el test.")
            return
        self.resultado = r
        self.vm.guardar_test_ortostatico(r, self._inicio_ts)
        self.lbl_fase.setText("Test terminado")
        extra = lambda v, u: "sin datos" if v is None else f"{v:.0f} {u}"
        self.lbl_resultado.setText(
            f"FC basal {r.fc_basal:.0f} BPM · pico al ponerte de pie {r.fc_pico:.0f} BPM · "
            f"estabilizada {extra(r.fc_estable, 'BPM')} · ΔFC {r.delta_fc:+.0f} BPM\n"
            f"RMSSD basal {extra(r.rmssd_basal, 'ms')} · RMSSD de pie {extra(r.rmssd_pie, 'ms')}\n\n{r.valoracion}")

    def closeEvent(self, e) -> None:
        if self.en_curso:
            self.en_curso = False
            self._desconectar()
            self.vm.detener_captura_ecg()
        super().closeEvent(e)
