"""Selector de rango de fechas, variable y resolución del historial (RF-14, 15, 16)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Callable, Optional

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import QComboBox, QDateEdit, QHBoxLayout, QLabel, QPushButton, QWidget

from domain import analisis

RESOLUCIONES_UI = (
    ("Automática", "auto"),
    ("Sin agrupar", analisis.SIN_AGRUPAR),
    ("Por minuto", "minuto"),
    ("Por hora", "hora"),
    ("Por día", "dia"),
)


class SelectorRango(QWidget):
    """Rango de días [desde, hasta] (ambos incluidos) más variable y resolución opcionales."""

    cambiado = Signal()

    def __init__(
        self,
        con_variable: bool = True,
        con_resolucion: bool = True,
        rango_disponible: Optional[Callable[[], Optional[tuple[int, int]]]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._rango_disponible = rango_disponible
        hoy = QDate.currentDate()

        fila = QHBoxLayout(self)
        fila.setContentsMargins(0, 0, 0, 0)

        self.fecha_desde = self._nuevo_selector_fecha(hoy)
        self.fecha_hasta = self._nuevo_selector_fecha(hoy)
        fila.addWidget(QLabel("Desde"))
        fila.addWidget(self.fecha_desde)
        fila.addWidget(QLabel("hasta"))
        fila.addWidget(self.fecha_hasta)

        self.btn_hoy = QPushButton("Hoy")
        self.btn_7 = QPushButton("7 días")
        self.btn_30 = QPushButton("30 días")
        self.btn_hoy.clicked.connect(lambda: self.establecer_ultimos_dias(1))
        self.btn_7.clicked.connect(lambda: self.establecer_ultimos_dias(7))
        self.btn_30.clicked.connect(lambda: self.establecer_ultimos_dias(30))
        for b in (self.btn_hoy, self.btn_7, self.btn_30):
            fila.addWidget(b)

        self.btn_todo: Optional[QPushButton] = None
        if rango_disponible is not None:
            self.btn_todo = QPushButton("Todo")
            self.btn_todo.clicked.connect(self._seleccionar_todo)
            fila.addWidget(self.btn_todo)

        self.combo_variable: Optional[QComboBox] = None
        if con_variable:
            self.combo_variable = QComboBox()
            for clave in analisis.VARIABLES:
                self.combo_variable.addItem(analisis.NOMBRE_VARIABLE[clave], clave)
            fila.addWidget(QLabel("Variable"))
            fila.addWidget(self.combo_variable)
            self.combo_variable.currentIndexChanged.connect(self.cambiado)

        self.combo_resolucion: Optional[QComboBox] = None
        if con_resolucion:
            self.combo_resolucion = QComboBox()
            for texto, clave in RESOLUCIONES_UI:
                self.combo_resolucion.addItem(texto, clave)
            fila.addWidget(QLabel("Resolución"))
            fila.addWidget(self.combo_resolucion)
            self.combo_resolucion.currentIndexChanged.connect(self.cambiado)

        fila.addStretch()
        self.fecha_desde.dateChanged.connect(lambda: self._on_fecha(desde=True))
        self.fecha_hasta.dateChanged.connect(lambda: self._on_fecha(desde=False))

    @staticmethod
    def _nuevo_selector_fecha(fecha: QDate) -> QDateEdit:
        w = QDateEdit(fecha)
        w.setCalendarPopup(True)
        w.setDisplayFormat("dd/MM/yyyy")
        w.setMaximumDate(QDate.currentDate())
        return w

    # ------------------------------------------------------------------

    def rango_dias(self) -> tuple[date, date]:
        return self.fecha_desde.date().toPython(), self.fecha_hasta.date().toPython()

    def rango_ts(self) -> tuple[int, int]:
        """[00:00 del primer día, 00:00 del día siguiente al último) en segundos Unix."""
        return analisis.rango_de_dias(*self.rango_dias())

    def variable(self) -> str:
        return self.combo_variable.currentData() if self.combo_variable else "bpm"

    def resolucion(self) -> str:
        return self.combo_resolucion.currentData() if self.combo_resolucion else "auto"

    def termina_hoy(self) -> bool:
        return self.rango_dias()[1] >= date.today()

    def establecer_rango(self, desde: date, hasta: date) -> None:
        if desde > hasta:
            desde, hasta = hasta, desde
        self._fijar(QDate(desde.year, desde.month, desde.day), QDate(hasta.year, hasta.month, hasta.day))

    def establecer_ultimos_dias(self, dias: int) -> None:
        hoy = date.today()
        self.establecer_rango(hoy - timedelta(days=dias - 1), hoy)

    # ------------------------------------------------------------------

    def _fijar(self, desde: QDate, hasta: QDate) -> None:
        for w, valor in ((self.fecha_desde, desde), (self.fecha_hasta, hasta)):
            w.blockSignals(True)
            w.setDate(valor)
            w.blockSignals(False)
        self.cambiado.emit()

    def _on_fecha(self, desde: bool) -> None:
        """Mantiene desde <= hasta: la fecha que se acaba de tocar arrastra a la otra."""
        d, h = self.fecha_desde.date(), self.fecha_hasta.date()
        if d > h:
            if desde:
                h = d
            else:
                d = h
        self._fijar(d, h)

    def _seleccionar_todo(self) -> None:
        rango = self._rango_disponible() if self._rango_disponible else None
        if rango is None:
            return
        self.establecer_rango(date.fromtimestamp(rango[0]), date.fromtimestamp(rango[1]))
