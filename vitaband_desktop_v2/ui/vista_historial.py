"""Pestaña "Historial periódico": mediciones guardadas cada 10 s por el escritorio y las
importadas del móvil (RF-13..16, 22, 27, 34, 45).

Todo el cálculo (estadísticas, agrupación, interrupciones) lo hace el ViewModel; esta
vista solo organiza y dibuja.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from domain import analisis
from services.consultas_historial import MAX_SPAN_ECG_S
from ui.formato import fecha_hora, texto_interrupciones
from ui.confirmaciones import confirmar
from ui.grafica_serie import GraficaSerie
from ui.panel_ecg_zoom import PanelEcgZoom
from ui.panel_observaciones import PanelObservaciones
from ui.selector_rango import SelectorRango
from viewmodel.vitaband_vm import VitaBandViewModel

MAX_FILAS_TABLA = 5000
BINS_ECG = 800

_ETIQUETAS_LEGIBLES = {
    "PERIODICO": "Periódico",
    "ACTIVIDAD": "Actividad",
    "AMBOS": "Periódico y actividad",
}
_DECIMALES = {"bpm": 1, "rpm": 1, "temp": 2, "actividad": 2}
_FORMATO_CUBO = {"minuto": "%d/%m %H:%M", "hora": "%d/%m %H:00", "dia": "%d/%m/%Y"}
_NOMBRE_RESOLUCION = {
    analisis.SIN_AGRUPAR: "sin agrupar", "minuto": "por minuto", "hora": "por hora", "dia": "por día",
}


def formatear_valor(v: Optional[float], variable: str) -> str:
    return "—" if v is None else f"{v:.{_DECIMALES[variable]}f}"


def celda(texto: str, centrada: bool = True) -> QTableWidgetItem:
    item = QTableWidgetItem(texto)
    if centrada:
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return item


class VistaHistorialPeriodico(QWidget):

    def __init__(self, view_model: VitaBandViewModel, parent=None):
        super().__init__(parent)
        self.vm = view_model
        self._construir_ui()

        self.selector.cambiado.connect(self.actualizar)
        self.tabla.itemSelectionChanged.connect(self._revisar_botones)
        self.btn_eliminar_seleccion.clicked.connect(self._eliminar_seleccion)
        self.btn_eliminar_periodo.clicked.connect(self._eliminar_periodo)
        self.vm.historial_actualizado.connect(self._on_datos_nuevos)
        self.vm.observaciones_actualizadas.connect(self._on_datos_nuevos)
        self.actualizar()

    # ------------------------------------------------------------------

    def _construir_ui(self) -> None:
        capa = QVBoxLayout(self)

        self.selector = SelectorRango(rango_disponible=self.vm.rango_disponible)
        capa.addWidget(self.selector)

        # Eliminación de registros (RF-38): siempre con confirmación explícita
        fila_borrado = QHBoxLayout()
        self.btn_eliminar_seleccion = QPushButton("Eliminar seleccionadas")
        self.btn_eliminar_periodo = QPushButton("Eliminar periodo…")
        self.lbl_info = QLabel()
        fila_borrado.addWidget(self.btn_eliminar_seleccion)
        fila_borrado.addWidget(self.btn_eliminar_periodo)
        fila_borrado.addWidget(self.lbl_info, stretch=1)
        capa.addLayout(fila_borrado)
        self._modo_individual = True

        self.lbl_resumen = QLabel()
        self.lbl_resumen.setStyleSheet("font-size: 14px; padding: 2px;")
        self.lbl_interrupciones = QLabel()
        self.lbl_interrupciones.setStyleSheet("color: #8a4b00;")
        capa.addWidget(self.lbl_resumen)
        capa.addWidget(self.lbl_interrupciones)

        self.grafica = GraficaSerie()
        self.tabla = QTableWidget(0, 3)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.observaciones = PanelObservaciones("Observaciones del periodo")
        # ECG con vista general y ampliación de un intervalo (RF-35)
        self.panel_ecg = PanelEcgZoom(lambda a, b, n: self.vm.ecg_historico(a, b, n))
        self.grafica_ecg = self.panel_ecg.vista_general

        medio = QSplitter(Qt.Orientation.Horizontal)
        medio.addWidget(self.tabla)
        medio.addWidget(self.observaciones)
        medio.setSizes([600, 400])

        vertical = QSplitter(Qt.Orientation.Vertical)
        vertical.addWidget(self.grafica)
        vertical.addWidget(medio)
        vertical.addWidget(self.panel_ecg)
        vertical.setSizes([260, 200, 280])
        capa.addWidget(vertical, stretch=1)

    # ------------------------------------------------------------------

    @Slot()
    def _on_datos_nuevos(self) -> None:
        # Solo se redibuja si se está mirando y el rango llega hasta hoy
        if self.isVisible() and self.selector.termina_hoy():
            self.actualizar()

    @Slot()
    def actualizar(self, *_args) -> None:
        desde, hasta = self.selector.rango_ts()
        variable = self.selector.variable()

        serie = self.vm.serie_historica(variable, desde, hasta, self.selector.resolucion())
        if serie is None:
            self.grafica.limpiar()
            self.tabla.setRowCount(0)
            self._revisar_botones()
            self.lbl_resumen.setText("No se pudo consultar el historial.")
            self.lbl_interrupciones.setText("")
        else:
            self.grafica.mostrar_serie(serie)
            self._rellenar_tabla(serie)
            self._revisar_botones()
            self._rellenar_resumen(serie)
            self.lbl_interrupciones.setText(texto_interrupciones(serie.interrupciones))

        self.observaciones.mostrar(self.vm.observaciones(desde, hasta, "DIARIA"))
        self._actualizar_ecg(desde, hasta)

    def _actualizar_ecg(self, desde: int, hasta: int) -> None:
        if hasta - desde > MAX_SPAN_ECG_S:
            self.panel_ecg.mostrar(None, desde, hasta, "ECG histórico: elige un periodo de hasta 7 días")
            return
        self.panel_ecg.mostrar(self.vm.ecg_historico(desde, hasta, BINS_ECG), desde, hasta)

    # ------------------------------------------------------------------

    def _rellenar_resumen(self, serie) -> None:
        e = serie.estadisticas
        if e is None:
            self.lbl_resumen.setText("Sin registros en este periodo.")
            return
        v, u = serie.variable, analisis.UNIDAD_VARIABLE[serie.variable]
        u = f" {u}" if u else ""
        self.lbl_resumen.setText(
            f"{e.cantidad} registros · media {formatear_valor(e.media, v)}{u} · "
            f"mínimo {formatear_valor(e.minimo, v)}{u} · máximo {formatear_valor(e.maximo, v)}{u} · "
            f"resolución {_NOMBRE_RESOLUCION[serie.resolucion]}"
        )

    def _rellenar_tabla(self, serie) -> None:
        v = serie.variable
        if serie.agrupada:
            self._tabla_agrupada(serie, v)
        else:
            self._tabla_individual(serie, v)

    def _preparar_columnas(self, cabeceras: list[str]) -> None:
        self.tabla.setColumnCount(len(cabeceras))
        self.tabla.setHorizontalHeaderLabels(cabeceras)

    def _tabla_individual(self, serie, v: str) -> None:
        self._modo_individual = True
        self._preparar_columnas(["Fecha y hora", analisis.NOMBRE_VARIABLE[v], "Tipo"])
        filas = [(m, analisis.valor_de(m, v)) for m in serie.mediciones]
        filas = [(m, x) for m, x in filas if x is not None][-MAX_FILAS_TABLA:]
        self.tabla.setRowCount(len(filas))
        for i, (m, x) in enumerate(filas):
            primera = celda(fecha_hora(m.ts))
            primera.setData(Qt.ItemDataRole.UserRole, m.id)          # id para poder eliminarla
            self.tabla.setItem(i, 0, primera)
            self.tabla.setItem(i, 1, celda(formatear_valor(x, v)))
            self.tabla.setItem(i, 2, celda(_ETIQUETAS_LEGIBLES.get(m.etiqueta, m.etiqueta), False))

    def _tabla_agrupada(self, serie, v: str) -> None:
        self._modo_individual = False
        self._preparar_columnas(["Periodo", "Registros", "Media", "Mínimo", "Máximo"])
        formato = _FORMATO_CUBO[serie.resolucion]
        cubos = serie.cubos[:MAX_FILAS_TABLA]
        self.tabla.setRowCount(len(cubos))
        for i, c in enumerate(cubos):
            self.tabla.setItem(i, 0, celda(datetime.fromtimestamp(c.inicio).strftime(formato)))
            if c.vacio:                                  # RF-27: el hueco se ve, no se rellena
                self.tabla.setItem(i, 1, celda("Sin datos"))
                for col in (2, 3, 4):
                    self.tabla.setItem(i, col, celda("—"))
                continue
            self.tabla.setItem(i, 1, celda(str(c.cantidad)))
            for col, valor in ((2, c.media), (3, c.minimo), (4, c.maximo)):
                self.tabla.setItem(i, col, celda(formatear_valor(valor, v)))

    # ------------------------------------------------------------------
    # Eliminación de registros (RF-38)
    # ------------------------------------------------------------------

    @Slot()
    def _revisar_botones(self) -> None:
        # Solo se pueden elegir filas sueltas cuando la tabla lista mediciones (no intervalos agrupados)
        self.btn_eliminar_seleccion.setEnabled(self._modo_individual and bool(self._ids_seleccionados()))

    def _ids_seleccionados(self) -> list[int]:
        filas = {i.row() for i in self.tabla.selectedIndexes()}
        ids = [self.tabla.item(f, 0).data(Qt.ItemDataRole.UserRole) for f in sorted(filas) if self.tabla.item(f, 0)]
        return [i for i in ids if i is not None]

    @Slot()
    def _eliminar_seleccion(self) -> None:
        ids = self._ids_seleccionados()
        if not ids:
            return
        if not confirmar(
            self, "Eliminar mediciones",
            f"Se eliminarán {len(ids)} medición(es) del historial periódico.\n\n"
            "Si alguna también pertenece a una actividad, se conserva en esa actividad.\n"
            "Esta acción no se puede deshacer.",
            "Eliminar",
        ):
            return
        self._ejecutar_borrado(lambda: self.vm.borrar_mediciones_periodicas(ids))

    @Slot()
    def _eliminar_periodo(self) -> None:
        desde, hasta = self.selector.rango_ts()
        consultas = self.vm.consultas
        n = len(consultas.mediciones(desde, hasta, "periodico")) if consultas is not None else 0
        d1, d2 = self.selector.rango_dias()
        if n == 0:
            self.lbl_info.setText("No hay mediciones periódicas en el periodo elegido.")
            return
        if not confirmar(
            self, "Eliminar periodo",
            f"Se eliminarán TODAS las mediciones del historial periódico del {d1:%d/%m/%Y} al {d2:%d/%m/%Y} "
            f"({n} registros).\n\n"
            "Las que también pertenecen a una actividad se conservan en esa actividad.\n"
            "Esta acción no se puede deshacer.",
            "Eliminar periodo",
        ):
            return
        self._ejecutar_borrado(lambda: self.vm.borrar_periodo(desde, hasta))

    def _ejecutar_borrado(self, accion) -> None:
        try:
            n = accion()
        except Exception as error:
            QMessageBox.warning(self, "No se pudo eliminar", str(error))
            return
        self.actualizar()
        self.lbl_info.setText(f"Se eliminaron {n} medición(es) del historial periódico.")
