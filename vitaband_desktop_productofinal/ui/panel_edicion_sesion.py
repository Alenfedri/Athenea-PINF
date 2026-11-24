"""Edición e higiene del dato en «Actividades»: Session Trimmer, limpieza R-R, dividir, fusionar y Coach Pack."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import pyqtgraph as pg
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from services import edicion_sesiones as ed
from services import modo_entrenador as me
from ui.confirmaciones import confirmar
from ui.tema_vitaband import ESMERALDA_ECG


class DialogoCoachPack(QDialog):
    """Privacidad por diseño: etiquetas personales desmarcadas por defecto."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Exportar Coach Pack (.vbcoach)")
        form = QFormLayout(self)
        self.combo_dias = QComboBox()
        self.combo_dias.addItem("42 días", 42)
        self.combo_dias.addItem("90 días", 90)
        self.edit_alias = QLineEdit()
        self.edit_alias.setPlaceholderText("Alias opcional (si se deja vacío se usa tu nombre)")
        self.chk_etiquetas = QCheckBox("Incluir etiquetas personales y hábitos")
        self.chk_etiquetas.setChecked(False)
        form.addRow("Rango", self.combo_dias)
        form.addRow("Alias", self.edit_alias)
        form.addRow(self.chk_etiquetas)
        form.addRow(QLabel("El paquete nunca incluye tu correo. Las etiquetas (Café, Estrés…) solo se comparten si lo marcas."))
        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        form.addRow(botones)

    def valores(self) -> dict:
        return {"dias": self.combo_dias.currentData(), "alias_opcional": self.edit_alias.text().strip(),
                "incluir_etiquetas": self.chk_etiquetas.isChecked()}


class PanelEdicionSesion(QWidget):
    def __init__(self, vm, nombre_usuario: str = "", parent=None):
        super().__init__(parent)
        self.vm, self.nombre = vm, nombre_usuario
        self.actividad_id: Optional[int] = None
        self._sesion: Optional[ed.Sesion] = None
        self._construido = False                       # se crea al seleccionar la primera actividad (ahorra memoria)

    def _construir(self) -> None:
        if self._construido:
            return
        self._construido = True
        capa = QVBoxLayout(self)
        capa.setContentsMargins(0, 0, 0, 0)
        self.grafica = pg.PlotWidget(title="Session Trimmer: arrastra los dos cursores para recortar el tramo")
        self.grafica.setMinimumHeight(150)
        self.grafica.setMaximumHeight(190)
        self.curva = self.grafica.plot([], [], pen=pg.mkPen(ESMERALDA_ECG, width=2))
        self.region = pg.LinearRegionItem([0, 1])
        self.grafica.addItem(self.region)
        capa.addWidget(self.grafica)
        fila = QHBoxLayout()
        self.btn_recorte = QPushButton("Aplicar Recorte")
        self.btn_artefactos = QPushButton("Limpiar Artefactos R-R")
        self.btn_dividir = QPushButton("Dividir Sesión")
        self.btn_fusionar = QPushButton("Fusionar con...")
        self.btn_coach = QPushButton("Exportar Coach Pack (.vbcoach)")
        for b in (self.btn_recorte, self.btn_artefactos, self.btn_dividir, self.btn_fusionar, self.btn_coach):
            fila.addWidget(b)
        capa.addLayout(fila)
        self.lbl_info = QLabel()
        capa.addWidget(self.lbl_info)
        self.btn_recorte.clicked.connect(self.aplicar_recorte)
        self.btn_artefactos.clicked.connect(self.limpiar_artefactos)
        self.btn_dividir.clicked.connect(self.dividir)
        self.btn_fusionar.clicked.connect(self.fusionar)
        self.btn_coach.clicked.connect(self.exportar_coach_pack)

    # --- selección
    def set_actividad(self, actividad_id: Optional[int]) -> None:
        if actividad_id is None and not self._construido:
            return
        self._construir()
        self.actividad_id = actividad_id
        repo = self.vm.repositorio
        self._sesion = None if repo is None or actividad_id is None else ed.cargar_sesion(repo, actividad_id)
        s = self._sesion
        for b in (self.btn_recorte, self.btn_artefactos, self.btn_dividir, self.btn_fusionar):
            b.setEnabled(s is not None)
        if s is None or not s.ts:
            self.curva.setData([], [])
            self.lbl_info.setText("")
            return
        self.curva.setData([t - s.inicio_ts for t in s.ts], list(s.bpm))
        dur = max(1, s.fin_ts - s.inicio_ts)
        self.region.setRegion([0, dur])
        self.region.setBounds([0, dur])
        self._info()

    def _info(self) -> None:
        m = ed.metricas(self._sesion, self.vm.perfil(), self.vm.fc_max())
        self.lbl_info.setText(f"{m.duracion_s // 60} min · BPM medio {m.bpm_medio or 0:.0f} / máx {m.bpm_max or 0:.0f} · "
                              f"TRIMP {m.trimp or 0:.0f} · {len(self._sesion.rr_ms)} intervalos R-R")

    def _rango_abs(self) -> tuple[int, int]:
        a, b = self.region.getRegion()
        return int(self._sesion.inicio_ts + a), int(self._sesion.inicio_ts + b)

    def _cambiado(self) -> None:
        self.vm.historial_actualizado.emit()
        self.set_actividad(self.actividad_id if self.vm.repositorio.obtener_actividad(self.actividad_id or -1) else None)

    # --- acciones
    def aplicar_recorte(self) -> None:
        if self._sesion is None:
            return
        t0, t1 = self._rango_abs()
        if confirmar(self, "Recortar sesión", "Se borrarán las mediciones fuera de la selección. No se puede deshacer.", "Recortar"):
            ed.aplicar_recorte(self.vm.repositorio, self.actividad_id, t0, t1)
            self._cambiado()

    def limpiar_artefactos(self) -> None:
        """Corrige los latidos ectópicos / artefactos de contacto de la serie R-R de la sesión."""
        if self._sesion is None:
            return
        n = ed.aplicar_limpieza_rr(self.vm.repositorio, self.actividad_id)
        self.lbl_info.setText(f"Se corrigieron {n} artefactos R-R (duración total intacta)." if n else
                              "No se detectaron artefactos R-R (desviación > 20 % de la mediana local).")
        if n:
            self._sesion = ed.cargar_sesion(self.vm.repositorio, self.actividad_id)

    def dividir(self) -> None:
        if self._sesion is None:
            return
        corte = self._rango_abs()[0]
        if ed.aplicar_division(self.vm.repositorio, self.actividad_id, corte) is None:
            QMessageBox.information(self, "Dividir sesión", "Coloca el cursor izquierdo dentro de la sesión.")
            return
        self._cambiado()

    def fusionar(self) -> None:
        repo = self.vm.repositorio
        ahora = int(self.vm.tiempo())
        otras = [a for a in repo.actividades_rango(0, ahora + 1) if a.id != self.actividad_id][:50]
        if not otras:
            QMessageBox.information(self, "Fusionar", "No hay otra sesión con la que fusionar.")
            return
        nombres = [f"{datetime.fromtimestamp(a.inicio_ts):%d/%m/%Y %H:%M} · {a.duracion_s // 60} min" for a in otras]
        elegido, ok = QInputDialog.getItem(self, "Fusionar con...", "Sesión:", nombres, 0, False)
        if ok and ed.aplicar_fusion(repo, self.actividad_id, otras[nombres.index(elegido)].id) is not None:
            self._cambiado()
        elif ok:
            QMessageBox.information(self, "Fusionar", "Las sesiones se solapan y no se pueden fusionar.")

    def exportar_coach_pack(self) -> None:
        dlg = DialogoCoachPack(self)
        if not dlg.exec():
            return
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar Coach Pack", "coach_pack.vbcoach", "Coach Pack (*.vbcoach)")
        if ruta:
            hoy = datetime.fromtimestamp(self.vm.tiempo()).date()
            me.exportar_coach_pack(self.vm.repositorio, ruta, hoy, nombre=self.nombre, **dlg.valores())
            self.lbl_info.setText(f"Coach Pack guardado en {ruta}")
