"""Pestaña "Actividades": sesiones importadas del móvil, con su detalle (RF-32, 45, 48, 49).

Las actividades solo se crean en el móvil; aquí se consultan. Cada una muestra
estadísticas, gráfica, ECG de la sesión y su observación orientativa.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QItemSelectionModel, Qt, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from domain import analisis
from domain import ecg_historico
from services import disciplinas as disc, ratio_pulso_resp as ratio_mod
from services.metricas_avanzadas import texto_hrr60
from ui.formato import duracion, fecha_hora, texto_interrupciones
from ui.barra_zonas import BarraZonas
from ui.confirmaciones import confirmar
from ui.exportar_png import boton_png
from ui.grafica_cruce import GraficaCruce
from ui.grafica_serie import GraficaSerie
from ui.panel_comparador import PanelComparador
from ui.panel_ecg_zoom import PanelEcgZoom
from ui.panel_observaciones import PanelObservaciones
from ui.panel_poincare import PanelPoincare
from ui.selector_rango import SelectorRango
from ui.vista_historial import celda, formatear_valor
from viewmodel.vitaband_vm import VitaBandViewModel

CABECERAS = ["Inicio", "Tipo", "Duración", "Mediciones", "FC media", "FC máx."]
MENSAJE_VACIO = "No hay actividades en este periodo. Se importan desde el móvil con «Sincronizar ahora»."
BINS_ECG = 600


class VistaActividades(QWidget):

    def __init__(self, view_model: VitaBandViewModel, parent=None):
        super().__init__(parent)
        self.vm = view_model
        self._detalle = None
        self._etiquetas: dict = {}
        self._prs: dict = {}
        self._construir_ui()

        self.selector.cambiado.connect(self.actualizar)
        self.tabla.itemSelectionChanged.connect(self._on_seleccion)
        self.combo_variable.currentIndexChanged.connect(self._dibujar_grafica)
        self.chk_comparar.toggled.connect(self._on_modo_comparar)
        self.btn_eliminar.clicked.connect(self._eliminar_actividad)
        self.btn_tcx.clicked.connect(self._exportar_tcx)
        self.vm.historial_actualizado.connect(self._on_datos_nuevos)
        self.vm.observaciones_actualizadas.connect(self._on_datos_nuevos)

        self.selector.establecer_ultimos_dias(30)     # emite cambiado -> actualizar()

    # ------------------------------------------------------------------

    def _construir_ui(self) -> None:
        capa = QVBoxLayout(self)
        self.selector = SelectorRango(con_variable=False, con_resolucion=False)
        capa.addWidget(self.selector)
        self.lbl_carga = QLabel()
        self.lbl_carga.setStyleSheet("font-weight: bold; color: #1a5276; padding: 2px;")
        capa.addWidget(self.lbl_carga)
        fila_filtro = QHBoxLayout()
        fila_filtro.addWidget(QLabel("Disciplina"))
        self.combo_filtro_disciplina = QComboBox()
        self.combo_filtro_disciplina.addItem("Todas", None)
        for dname in disc.DISCIPLINAS:
            self.combo_filtro_disciplina.addItem(dname, dname)
        self.combo_filtro_disciplina.addItem("Sin disciplina", "")
        self.combo_filtro_disciplina.currentIndexChanged.connect(self.actualizar)
        fila_filtro.addWidget(self.combo_filtro_disciplina)
        fila_filtro.addStretch()
        capa.addLayout(fila_filtro)

        self.tabla = QTableWidget(0, len(CABECERAS))
        self.tabla.setHorizontalHeaderLabels(CABECERAS)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        detalle = QWidget()
        d = QVBoxLayout(detalle)
        d.setContentsMargins(0, 0, 0, 0)
        self.lbl_titulo = QLabel(MENSAJE_VACIO)
        self.lbl_titulo.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.lbl_titulo.setWordWrap(True)
        self.lbl_estadisticas = QLabel()
        fila = QHBoxLayout()
        fila.addWidget(QLabel("Variable"))
        self.combo_variable = QComboBox()
        for clave in analisis.VARIABLES:
            self.combo_variable.addItem(analisis.NOMBRE_VARIABLE[clave], clave)
        fila.addWidget(self.combo_variable)
        fila.addStretch()
        self.btn_eliminar = QPushButton("Eliminar actividad")      # RF-38
        self.btn_eliminar.setEnabled(False)
        fila.addWidget(self.btn_eliminar)
        self.btn_tcx = QPushButton("Exportar .TCX")             # Strava / Garmin
        self.btn_tcx.setEnabled(False)
        fila.addWidget(self.btn_tcx)
        self.grafica = GraficaSerie()
        self.grafica_cruce = GraficaCruce()                       # BPM + RPM y umbral de fatiga
        self.pestanas_grafica = QTabWidget()
        self.pestanas_grafica.addTab(self.grafica, "Serie")
        self.pestanas_grafica.addTab(self.grafica_cruce, "Pulso y respiración")
        self.panel_poincare = PanelPoincare()
        self.pestanas_grafica.addTab(self.panel_poincare, "Poincaré")
        self.barra_zonas = BarraZonas()
        self.lbl_umbral = QLabel()
        self.lbl_umbral.setWordWrap(True)
        self.lbl_umbral.setStyleSheet("font-weight: bold; color: #6a1b9a;")
        self.lbl_interrupciones = QLabel()
        self.lbl_interrupciones.setStyleSheet("color: #8a4b00;")
        self.panel_ecg = PanelEcgZoom(lambda a, b, n: self.vm.ecg_historico(a, b, n))   # RF-35
        self.grafica_ecg = self.panel_ecg.vista_general
        self.observacion = PanelObservaciones("Observación de la actividad")
        for w in (self.lbl_titulo, self.lbl_estadisticas):
            d.addWidget(w)
        d.addLayout(fila)
        d.addWidget(self.barra_zonas)

        # Disciplina y récords personales
        fila_disc = QHBoxLayout()
        fila_disc.addWidget(QLabel("Disciplina de esta sesión"))
        self.combo_disciplina = QComboBox()
        self.combo_disciplina.addItem("— sin disciplina —", "")
        for dname in disc.DISCIPLINAS:
            self.combo_disciplina.addItem(dname, dname)
        self.btn_disciplina = QPushButton("Guardar disciplina")
        self.btn_disciplina.clicked.connect(self._guardar_disciplina)
        fila_disc.addWidget(self.combo_disciplina)
        fila_disc.addWidget(self.btn_disciplina)
        fila_disc.addStretch()
        d.addLayout(fila_disc)
        self.lbl_prs = QLabel()
        self.lbl_prs.setWordWrap(True)
        self.lbl_prs.setStyleSheet("font-weight: bold; color: #b7950b;")
        d.addWidget(self.lbl_prs)

        # Desglose por vueltas (Lap) y valoración RPE
        self.tabla_vueltas = QTableWidget(0, 4)
        self.tabla_vueltas.setHorizontalHeaderLabels(["Vuelta", "Duración", "BPM medio", "RPM medio"])
        self.tabla_vueltas.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla_vueltas.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla_vueltas.setMaximumHeight(130)
        self.tabla_vueltas.setVisible(False)
        d.addWidget(self.tabla_vueltas)
        fila_rpe = QHBoxLayout()
        fila_rpe.addWidget(QLabel("RPE (1–10)"))
        self.spin_rpe = QSpinBox()
        self.spin_rpe.setRange(0, 10)
        self.spin_rpe.setSpecialValueText("—")
        self.edit_nota = QLineEdit()
        self.edit_nota.setPlaceholderText("Nota de la sesión")
        self.edit_nota.setMaxLength(300)
        self.btn_valoracion = QPushButton("Guardar valoración")
        self.btn_valoracion.clicked.connect(self._guardar_valoracion)
        for w in (self.spin_rpe, self.edit_nota, self.btn_valoracion):
            fila_rpe.addWidget(w, stretch=1 if w is self.edit_nota else 0)
        d.addLayout(fila_rpe)
        d.addWidget(self.lbl_umbral)
        d.addWidget(self.pestanas_grafica, stretch=3)
        d.addWidget(self.lbl_interrupciones)
        d.addWidget(self.panel_ecg, stretch=3)
        d.addWidget(self.observacion, stretch=2)

        # «Antes vs. Ahora»: con el modo activo se eligen dos filas y el detalle cede su sitio al comparador
        self.chk_comparar = QCheckBox("Comparar 2 sesiones (Antes vs. Ahora)")
        izquierda = QWidget()
        li = QVBoxLayout(izquierda)
        li.setContentsMargins(0, 0, 0, 0)
        fila_cmp = QHBoxLayout()
        fila_cmp.addWidget(self.chk_comparar, stretch=1)
        fila_cmp.addWidget(boton_png(lambda: self.comparador, "vitaband_comparador"))
        li.addLayout(fila_cmp)
        li.addWidget(self.tabla)
        self.comparador = PanelComparador()
        self.pila = QStackedWidget()
        self.pila.addWidget(detalle)
        self.pila.addWidget(self.comparador)

        division = QSplitter(Qt.Orientation.Horizontal)
        division.addWidget(izquierda)
        division.addWidget(self.pila)
        division.setSizes([420, 680])
        capa.addWidget(division, stretch=1)

    # ------------------------------------------------------------------

    def actividad_seleccionada(self) -> Optional[int]:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            return None
        return self.tabla.item(filas[0].row(), 0).data(Qt.ItemDataRole.UserRole)

    @property
    def comparando(self) -> bool:
        return self.chk_comparar.isChecked()

    def actividades_seleccionadas(self) -> list[int]:
        filas = sorted(i.row() for i in self.tabla.selectionModel().selectedRows())
        return [self.tabla.item(f, 0).data(Qt.ItemDataRole.UserRole) for f in filas]

    @Slot(bool)
    def _on_modo_comparar(self, activo: bool) -> None:
        previas = self.actividades_seleccionadas()
        self.tabla.clearSelection()
        self.tabla.setSelectionMode(
            QAbstractItemView.SelectionMode.MultiSelection if activo
            else QAbstractItemView.SelectionMode.SingleSelection)
        self.pila.setCurrentIndex(1 if activo else 0)
        if activo:
            self._seleccionar(previas[:1])               # la que se estaba viendo queda marcada
        else:
            self._seleccionar(previas[:1] or ([self.tabla.item(0, 0).data(Qt.ItemDataRole.UserRole)]
                                              if self.tabla.rowCount() else []))
        self._on_seleccion()

    def _seleccionar(self, ids) -> None:
        self.tabla.blockSignals(True)
        for fila in range(self.tabla.rowCount()):
            if self.tabla.item(fila, 0).data(Qt.ItemDataRole.UserRole) in ids:
                self.tabla.selectionModel().select(
                    self.tabla.model().index(fila, 0),
                    QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        self.tabla.blockSignals(False)

    def _mostrar_comparacion(self) -> None:
        self.btn_eliminar.setEnabled(False)
        self.btn_tcx.setEnabled(False)
        ids = self.actividades_seleccionadas()
        if len(ids) != 2:
            self.comparador.mostrar_mensaje({
                0: "Marca dos sesiones de la lista para compararlas.",
                1: "Marca una segunda sesión para compararla con la elegida.",
            }.get(len(ids), f"Has marcado {len(ids)} sesiones: deja solo dos."))
            return
        comparativa = self.vm.comparar_actividades(*ids)
        if comparativa is None:
            self.comparador.mostrar_mensaje("No se pudieron cargar las dos sesiones.")
        else:
            self.comparador.mostrar(comparativa)
            e = self.vm.disciplinas()
            self.comparador.mostrar_aviso(disc.aviso_comparacion(e.get(ids[0]), e.get(ids[1])))

    @Slot()
    def _on_datos_nuevos(self) -> None:
        if self.isVisible():
            self.actualizar()

    @Slot()
    def actualizar(self, *_args) -> None:
        previas = self.actividades_seleccionadas()
        previa = self.actividad_seleccionada()
        self.lbl_carga.setText(self.vm.carga_entrenamiento().texto)
        desde, hasta = self.selector.rango_ts()
        resumenes = self.vm.actividades(desde, hasta)
        self._etiquetas = self.vm.disciplinas()
        self._prs = self.vm.records_personales()
        filtro = self.combo_filtro_disciplina.currentData()
        if filtro is not None:
            resumenes = [r for r in resumenes if self._etiquetas.get(r.actividad.id, "") == filtro]

        self.tabla.blockSignals(True)
        self.tabla.setRowCount(len(resumenes))
        fila_previa = None
        for i, r in enumerate(resumenes):
            a = r.actividad
            valores = (
                fecha_hora(a.inicio_ts), self._texto_tipo(a), duracion(a.duracion_s), str(r.mediciones),
                formatear_valor(r.fc.media if r.fc else None, "bpm"),
                formatear_valor(r.fc.maximo if r.fc else None, "bpm"),
            )
            for col, texto in enumerate(valores):
                item = celda(texto, centrada=col != 1)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, a.id)
                self.tabla.setItem(i, col, item)
            if a.id == previa:
                fila_previa = i
        self.tabla.blockSignals(False)

        if self.comparando:                              # se conserva el conjunto marcado, no solo una fila
            self.tabla.clearSelection()
            self._seleccionar(previas)
            self._on_seleccion()
        elif not resumenes:
            self.tabla.clearSelection()
            self._mostrar_detalle(None)
        else:
            self.tabla.selectRow(fila_previa if fila_previa is not None else 0)
            self._on_seleccion()

    @Slot()
    def _on_seleccion(self) -> None:
        if self.comparando:
            self._mostrar_comparacion()
            return
        actividad_id = self.actividad_seleccionada()
        self._mostrar_detalle(None if actividad_id is None else self.vm.detalle_actividad(actividad_id))

    # ------------------------------------------------------------------

    def _texto_tipo(self, a) -> str:
        d = self._etiquetas.get(a.id)
        base = a.tipo or ("—" if not d else "")
        texto = f"{base} · {d}".strip(" ·") if d else base
        return texto + (" 🏆" if self._prs.get(a.id) else "")

    @Slot()
    def _guardar_disciplina(self) -> None:
        d = self._detalle
        if d is None:
            return
        try:
            self.vm.guardar_disciplina(d.actividad.id, self.combo_disciplina.currentData() or None)
            self.actualizar()
        except Exception as error:
            QMessageBox.warning(self, "No se pudo guardar", str(error))

    def _mostrar_detalle(self, detalle) -> None:
        self._detalle = detalle
        if detalle is None:
            self.lbl_titulo.setText(MENSAJE_VACIO)
            self.lbl_estadisticas.setText("")
            self.lbl_interrupciones.setText("")
            self.grafica.limpiar()
            self.grafica_cruce.limpiar()
            self.barra_zonas.mostrar(None)
            self.lbl_umbral.setText("")
            self.panel_ecg.mostrar(None, 0, 1)
            self.observacion.mostrar([], "Selecciona una actividad.")
            self.btn_eliminar.setEnabled(False)
            self.btn_tcx.setEnabled(False)
            self.tabla_vueltas.setVisible(False)
            self.panel_poincare.mostrar(None)
            self.lbl_prs.setText("")
            self.btn_disciplina.setEnabled(False)
            self.btn_valoracion.setEnabled(False)
            self.spin_rpe.setValue(0)
            self.edit_nota.clear()
            return

        self.btn_eliminar.setEnabled(True)
        self.btn_tcx.setEnabled(True)

        a = detalle.actividad
        tipo = f" ({a.tipo})" if a.tipo else ""
        self.lbl_titulo.setText(f"Actividad{tipo} · {fecha_hora(a.inicio_ts)} · {duracion(a.duracion_s)}")
        self.lbl_estadisticas.setText(self._texto_estadisticas(detalle) + self._texto_metricas(detalle))
        self.lbl_interrupciones.setText(texto_interrupciones(detalle.interrupciones))
        self._dibujar_grafica()
        self._mostrar_zonas_y_umbral(detalle)
        self._mostrar_vueltas_y_valoracion(detalle)
        self._mostrar_disciplina_y_poincare(detalle)

        reducido = ecg_historico.reducir(detalle.ecg, a.inicio_ts, a.fin_ts + 1, BINS_ECG)
        self.panel_ecg.mostrar(reducido, a.inicio_ts, a.fin_ts + 1)
        self.observacion.mostrar(
            [detalle.observacion] if detalle.observacion else [],
            "Esta actividad aún no tiene observación.",
        )

    def _mostrar_zonas_y_umbral(self, detalle) -> None:
        a = detalle.actividad
        analisis_ = self.vm.analisis_actividad(detalle)
        self.barra_zonas.mostrar(analisis_.zonas)
        u = analisis_.umbral
        self.lbl_umbral.setText(u.umbral.texto if u.umbral else u.motivo)
        self.grafica_cruce.mostrar(detalle.mediciones, a.inicio_ts, a.fin_ts, u.umbral, u.motivo)

    @Slot()
    def _dibujar_grafica(self, *_args) -> None:
        d = self._detalle
        if d is None:
            return
        variable = self.combo_variable.currentData()
        pares = analisis.pares_de(d.mediciones, variable)
        umbral = analisis.umbral_interrupcion([m.ts for m in d.mediciones], 5)
        self.grafica.mostrar_pares(
            variable, pares, d.interrupciones, umbral, d.actividad.inicio_ts, d.actividad.fin_ts)

    def _mostrar_disciplina_y_poincare(self, detalle) -> None:
        a = detalle.actividad
        i = self.combo_disciplina.findData(self.vm.disciplinas().get(a.id, ""))
        self.combo_disciplina.setCurrentIndex(max(i, 0))
        self.btn_disciplina.setEnabled(True)
        prs = self.vm.records_personales().get(a.id, [])
        self.lbl_prs.setText("🏆 " + " · ".join(prs) if prs else "")
        self.panel_poincare.mostrar(self.vm.poincare(a.inicio_ts, a.fin_ts + 1))

    def _mostrar_vueltas_y_valoracion(self, detalle) -> None:
        vueltas = self.vm.desglose_vueltas(detalle)
        self.tabla_vueltas.setVisible(bool(vueltas))
        self.tabla_vueltas.setRowCount(len(vueltas))
        for i, v in enumerate(vueltas):
            valores = (f"#{v.numero}", duracion(v.duracion_s),
                       "—" if v.bpm_medio is None else f"{v.bpm_medio:.0f}",
                       "—" if v.rpm_medio is None else f"{v.rpm_medio:.0f}")
            for col, texto in enumerate(valores):
                self.tabla_vueltas.setItem(i, col, celda(texto, centrada=True))
        nota = self.vm.nota_sesion(detalle.actividad.id)
        self.spin_rpe.setValue(0 if nota is None or nota[0] is None else nota[0])
        self.edit_nota.setText("" if nota is None else nota[1])
        self.btn_valoracion.setEnabled(True)

    @Slot()
    def _guardar_valoracion(self) -> None:
        d = self._detalle
        if d is None:
            return
        rpe = self.spin_rpe.value() or None
        if rpe is None and not self.edit_nota.text().strip():
            return
        try:
            self.vm.guardar_nota_sesion(d.actividad.id, rpe, self.edit_nota.text())
        except Exception as error:
            QMessageBox.warning(self, "No se pudo guardar", str(error))

    def _texto_metricas(self, detalle) -> str:
        m = self.vm.metricas_actividad(detalle)
        t = m["trimp"]
        extra = [f"\nTRIMP: {'N/D' if t is None else f'{t:.0f}'} · Recuperación cardíaca 1 min (HRR-60): {texto_hrr60(m['hrr60'])}"]
        kcal = self.vm.kcal_actividad(detalle)
        r, bajos = ratio_mod.ratio_medio(detalle.mediciones)
        extra.append(f"Pulso/respiración medio: {ratio_mod.texto_ratio(r)}" + (
            f" ({ratio_mod.estado(r)}; óptimo ≈ 4:1)" if r is not None else "")
            + (f" · {bajos:.0f} % del tiempo por debajo de 3:1 (posible hiperventilación o fatiga respiratoria)"
               if bajos >= 20 else ""))
        extra.append("Energía estimada (Keytel): " + (
            f"{kcal:.0f} kcal" if kcal is not None else "N/D (indica edad y sexo en «Perfil fisiológico»)"))
        if m["deriva"] is not None:
            extra.append("⚠ " + m["deriva"].texto)
        return "\n".join(extra)

    @Slot()
    def _exportar_tcx(self) -> None:
        d = self._detalle
        if d is None:
            return
        sugerido = f"vitaband_actividad_{fecha_hora(d.actividad.inicio_ts)[:10].replace('/', '-')}.tcx"
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar actividad a TCX", sugerido, "Archivos TCX (*.tcx)")
        if not ruta:
            return
        if not ruta.lower().endswith(".tcx"):
            ruta += ".tcx"
        try:
            n = self.vm.exportar_tcx(d.actividad.id, ruta)
        except Exception as error:
            QMessageBox.warning(self, "No se pudo exportar", str(error))
            return
        QMessageBox.information(self, "TCX exportado", f"Se exportaron {n} puntos a:\n{ruta}")

    @staticmethod
    def _texto_estadisticas(d) -> str:
        lineas = []
        for v in analisis.VARIABLES:
            e = d.estadisticas.get(v)
            if e is None:
                continue
            u = analisis.UNIDAD_VARIABLE[v]
            u = f" {u}" if u else ""
            lineas.append(
                f"{analisis.NOMBRE_VARIABLE[v]}: media {formatear_valor(e.media, v)}{u}, "
                f"mín. {formatear_valor(e.minimo, v)}, máx. {formatear_valor(e.maximo, v)} ({e.cantidad} registros)"
            )
        return "\n".join(lineas) if lineas else "Sin mediciones asociadas."

    # ------------------------------------------------------------------
    # Eliminación de una actividad (RF-38)
    # ------------------------------------------------------------------

    @Slot()
    def _eliminar_actividad(self) -> None:
        d = self._detalle
        if d is None:
            return
        a = d.actividad
        tipo = f" ({a.tipo})" if a.tipo else ""
        if not confirmar(
            self, "Eliminar actividad",
            f"Se eliminará la actividad{tipo} del {fecha_hora(a.inicio_ts)} con sus {len(d.mediciones)} "
            "mediciones y su observación.\n\n"
            "Las mediciones que también están en el historial periódico se conservan allí.\n"
            "Esta acción no se puede deshacer.",
            "Eliminar actividad",
        ):
            return
        try:
            self.vm.borrar_actividad(a.id)
        except Exception as error:
            QMessageBox.warning(self, "No se pudo eliminar", str(error))
            return
        self.actualizar()
