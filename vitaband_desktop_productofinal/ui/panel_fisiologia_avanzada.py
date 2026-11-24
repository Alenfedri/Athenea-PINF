"""Pestaña «Análisis avanzado»: PMC (CTL/ATL/TSB), umbrales ventilatorios VT1/VT2 y curva de pulso máximo."""
from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from services import edicion_sesiones as ed
from services import fisiologia_avanzada as fa
from ui.tema_vitaband import CORAL_PULSO, ESMERALDA_ECG, ORO_CHAMPAN, TEXTO_SALVIA

ETIQUETAS_DURACION = {5: "5 s", 60: "1 min", 300: "5 min", 1200: "20 min", 3600: "60 min"}


class PanelFisiologiaAvanzada(QWidget):
    def __init__(self, vm, parent=None):
        super().__init__(parent)
        self.vm = vm
        self._construido = False                       # las gráficas se crean al mostrar la pestaña (ahorra memoria)

    def _construir(self):
        if self._construido:
            return
        self._construido = True
        vm = self.vm
        capa = QVBoxLayout(self)

        fila = QHBoxLayout()
        fila.addWidget(QLabel("Rango del PMC"))
        self.combo_rango = QComboBox()
        for d in (42, 60, 90):
            self.combo_rango.addItem(f"{d} días", d)
        fila.addWidget(self.combo_rango)
        fila.addStretch(1)
        capa.addLayout(fila)

        self.grafica_pmc = pg.PlotWidget(title="Gestión del rendimiento: CTL (fitness) · ATL (fatiga) · TSB (forma)")
        self.grafica_pmc.addLegend()
        self.grafica_pmc.showGrid(x=True, y=True, alpha=0.2)
        self.curvas = {
            "ctl": self.grafica_pmc.plot([], [], pen=pg.mkPen(ESMERALDA_ECG, width=2), name="CTL (fitness)"),
            "atl": self.grafica_pmc.plot([], [], pen=pg.mkPen(CORAL_PULSO, width=2), name="ATL (fatiga)"),
            "tsb": self.grafica_pmc.plot([], [], pen=pg.mkPen(ORO_CHAMPAN, width=2), name="TSB (forma)"),
        }
        self.lbl_pmc = QLabel()
        capa.addWidget(self.grafica_pmc, 3)
        capa.addWidget(self.lbl_pmc)

        fila_vt = QHBoxLayout()
        self.lbl_umbrales = QLabel("Umbrales ventilatorios: elige una sesión y pulsa «Recalcular sobre sesión».")
        self.lbl_umbrales.setWordWrap(True)
        self.combo_sesion = QComboBox()
        self.btn_recalcular = QPushButton("Recalcular sobre sesión")
        fila_vt.addWidget(self.lbl_umbrales, 1)
        fila_vt.addWidget(self.combo_sesion)
        fila_vt.addWidget(self.btn_recalcular)
        capa.addLayout(fila_vt)

        self.grafica_pico = pg.PlotWidget(title="Curva de pulso máximo sostenido: temporada actual vs. anterior")
        self.grafica_pico.addLegend()
        self.grafica_pico.showGrid(y=True, alpha=0.2)
        self.grafica_pico.getAxis("bottom").setTicks([[(i, t) for i, t in enumerate(ETIQUETAS_DURACION.values())]])
        capa.addWidget(self.grafica_pico, 2)
        from ui.modo_escritorio import ResumenBalanceMental
        self.resumen_balance = ResumenBalanceMental()
        capa.addWidget(self.resumen_balance)

        self.combo_rango.currentIndexChanged.connect(self.actualizar)
        self.btn_recalcular.clicked.connect(self.recalcular_umbrales)
        vm.historial_actualizado.connect(self.actualizar)

    def showEvent(self, ev):
        self.actualizar()
        super().showEvent(ev)

    def _hoy(self) -> date:
        return datetime.fromtimestamp(self.vm.tiempo()).date()

    def actualizar(self, *_):
        self._construir()
        repo = self.vm.repositorio
        if repo is None:
            return
        hoy = self._hoy()
        pmc = fa.calcular_pmc(fa.trimp_diario(repo, hoy), hoy, self.combo_rango.currentData() or 42)
        x = np.arange(len(pmc))
        for clave, c in self.curvas.items():
            c.setData(x, [getattr(p, clave) for p in pmc])
        u = pmc[-1]
        self.lbl_pmc.setText(f"Hoy: CTL {u.ctl:.1f} · ATL {u.atl:.1f} · TSB {u.tsb:+.1f}"
                             + (" (fresco)" if u.tsb > 5 else " (fatigado)" if u.tsb < -10 else ""))
        # pico por duración
        actual, anterior = fa.curvas_por_temporada(repo, hoy)
        self.grafica_pico.clear()
        xs = np.arange(len(fa.DURACIONES_PICO_S))
        for desp, curva, color, nombre in ((-0.2, anterior, TEXTO_SALVIA, "Temporada anterior"),
                                           (0.2, actual, ESMERALDA_ECG, "Temporada actual")):
            vals = [curva.get(d) or 0 for d in fa.DURACIONES_PICO_S]
            self.grafica_pico.addItem(pg.BarGraphItem(x=xs + desp, height=vals, width=0.35, brush=color, name=nombre))
        self.grafica_pico.setYRange(0, max([v or 0 for v in (*actual.values(), *anterior.values())] + [100]) * 1.1)
        # sesiones recientes para los umbrales
        actual_id = self.combo_sesion.currentData()
        self.combo_sesion.blockSignals(True)
        self.combo_sesion.clear()
        ahora = int(self.vm.tiempo())
        for a in repo.actividades_rango(ahora - 90 * 86400, ahora + 1)[:30]:
            self.combo_sesion.addItem(f"{datetime.fromtimestamp(a.inicio_ts):%d/%m %H:%M} · {a.duracion_s // 60} min", a.id)
        i = self.combo_sesion.findData(actual_id)
        self.combo_sesion.setCurrentIndex(max(i, 0))
        self.combo_sesion.blockSignals(False)

    def recalcular_umbrales(self):
        self._construir()
        repo = self.vm.repositorio
        aid = self.combo_sesion.currentData()
        s = None if repo is None or aid is None else ed.cargar_sesion(repo, aid)
        if s is None or len(s.rr_ms) < 200:
            self.lbl_umbrales.setText("Umbrales ventilatorios: la sesión no tiene suficientes intervalos R-R "
                                      "(se necesitan ≈ 200 latidos).")
            return
        t_rpm = [t - s.inicio_ts for t, r in zip(s.ts, s.rpm) if r]
        rpm = [r for r in s.rpm if r]
        res = fa.detectar_umbrales_ventilatorios(s.rr_ms, t_rpm, rpm)
        vt1, vt2 = res["VT1"], res["VT2"]
        txt = lambda u, nom: (f"{nom}: {u.bpm:.0f} BPM (min {u.t_s / 60:.0f}, {u.metodo})" if u else f"{nom}: no detectado")
        self.lbl_umbrales.setText(f"{txt(vt1, 'VT1')} · {txt(vt2, 'VT2')}. Estimación orientativa, sin prueba de gases.")
