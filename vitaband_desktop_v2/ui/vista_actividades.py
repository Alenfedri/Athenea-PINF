"""Pestaña "Actividades": sesiones importadas del móvil, con su detalle (RF-32, 45, 48, 49).

Las actividades solo se crean en el móvil; aquí se consultan. Cada una muestra
estadísticas, gráfica, ECG de la sesión y su observación orientativa.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from domain import analisis
from domain import ecg_historico
from ui.formato import duracion, fecha_hora, texto_interrupciones
from ui.confirmaciones import confirmar
from ui.grafica_serie import GraficaSerie
from ui.panel_ecg_zoom import PanelEcgZoom
from ui.panel_observaciones import PanelObservaciones
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
        self._construir_ui()

        self.selector.cambiado.connect(self.actualizar)
        self.tabla.itemSelectionChanged.connect(self._on_seleccion)
        self.combo_variable.currentIndexChanged.connect(self._dibujar_grafica)
        self.btn_eliminar.clicked.connect(self._eliminar_actividad)
        self.vm.historial_actualizado.connect(self._on_datos_nuevos)
        self.vm.observaciones_actualizadas.connect(self._on_datos_nuevos)

        self.selector.establecer_ultimos_dias(30)     # emite cambiado -> actualizar()

    # ------------------------------------------------------------------

    def _construir_ui(self) -> None:
        capa = QVBoxLayout(self)
        self.selector = SelectorRango(con_variable=False, con_resolucion=False)
        capa.addWidget(self.selector)

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
        self.grafica = GraficaSerie()
        self.lbl_interrupciones = QLabel()
        self.lbl_interrupciones.setStyleSheet("color: #8a4b00;")
        self.panel_ecg = PanelEcgZoom(lambda a, b, n: self.vm.ecg_historico(a, b, n))   # RF-35
        self.grafica_ecg = self.panel_ecg.vista_general
        self.observacion = PanelObservaciones("Observación de la actividad")
        for w in (self.lbl_titulo, self.lbl_estadisticas):
            d.addWidget(w)
        d.addLayout(fila)
        d.addWidget(self.grafica, stretch=3)
        d.addWidget(self.lbl_interrupciones)
        d.addWidget(self.panel_ecg, stretch=3)
        d.addWidget(self.observacion, stretch=2)

        division = QSplitter(Qt.Orientation.Horizontal)
        division.addWidget(self.tabla)
        division.addWidget(detalle)
        division.setSizes([420, 680])
        capa.addWidget(division, stretch=1)

    # ------------------------------------------------------------------

    def actividad_seleccionada(self) -> Optional[int]:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            return None
        return self.tabla.item(filas[0].row(), 0).data(Qt.ItemDataRole.UserRole)

    @Slot()
    def _on_datos_nuevos(self) -> None:
        if self.isVisible():
            self.actualizar()

    @Slot()
    def actualizar(self, *_args) -> None:
        previa = self.actividad_seleccionada()
        desde, hasta = self.selector.rango_ts()
        resumenes = self.vm.actividades(desde, hasta)

        self.tabla.blockSignals(True)
        self.tabla.setRowCount(len(resumenes))
        fila_previa = None
        for i, r in enumerate(resumenes):
            a = r.actividad
            valores = (
                fecha_hora(a.inicio_ts), a.tipo or "—", duracion(a.duracion_s), str(r.mediciones),
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

        if not resumenes:
            self.tabla.clearSelection()
            self._mostrar_detalle(None)
        else:
            self.tabla.selectRow(fila_previa if fila_previa is not None else 0)
            self._on_seleccion()

    @Slot()
    def _on_seleccion(self) -> None:
        actividad_id = self.actividad_seleccionada()
        self._mostrar_detalle(None if actividad_id is None else self.vm.detalle_actividad(actividad_id))

    # ------------------------------------------------------------------

    def _mostrar_detalle(self, detalle) -> None:
        self._detalle = detalle
        if detalle is None:
            self.lbl_titulo.setText(MENSAJE_VACIO)
            self.lbl_estadisticas.setText("")
            self.lbl_interrupciones.setText("")
            self.grafica.limpiar()
            self.panel_ecg.mostrar(None, 0, 1)
            self.observacion.mostrar([], "Selecciona una actividad.")
            self.btn_eliminar.setEnabled(False)
            return

        self.btn_eliminar.setEnabled(True)

        a = detalle.actividad
        tipo = f" ({a.tipo})" if a.tipo else ""
        self.lbl_titulo.setText(f"Actividad{tipo} · {fecha_hora(a.inicio_ts)} · {duracion(a.duracion_s)}")
        self.lbl_estadisticas.setText(self._texto_estadisticas(detalle))
        self.lbl_interrupciones.setText(texto_interrupciones(detalle.interrupciones))
        self._dibujar_grafica()

        reducido = ecg_historico.reducir(detalle.ecg, a.inicio_ts, a.fin_ts + 1, BINS_ECG)
        self.panel_ecg.mostrar(reducido, a.inicio_ts, a.fin_ts + 1)
        self.observacion.mostrar(
            [detalle.observacion] if detalle.observacion else [],
            "Esta actividad aún no tiene observación.",
        )

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
