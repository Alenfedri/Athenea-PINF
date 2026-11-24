"""Planificación: Workout Builder, panel de ejecución en Tiempo real y calendario planificado vs. ejecutado."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from PySide6.QtCore import QDate, QTimer, Signal
from PySide6.QtGui import QColor, QTextCharFormat
from PySide6.QtWidgets import (
    QCalendarWidget, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QProgressBar,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from services import planificacion_entrenamiento as pl


def _mmss(s: float) -> str:
    s = max(0, int(round(s)))
    return f"{s // 60:02d}:{s % 60:02d}"


class PanelEjecucion(QWidget):
    """Panel de «Tiempo real»: bloque actual, cuenta atrás y progreso; cambia la zona del Piloto Automático."""

    def __init__(self, vm, parent=None):
        super().__init__(parent)
        self.vm = vm
        self.ejecutor: Optional[pl.EjecutorBloques] = None
        self.entrenamiento: Optional[pl.EntrenamientoEstructurado] = None
        capa = QHBoxLayout(self)
        capa.setContentsMargins(0, 0, 0, 0)
        self.lbl_bloque = QLabel("Entrenamiento estructurado: nada cargado")
        self.barra_bloque = QProgressBar()
        self.barra_bloque.setRange(0, 1000)
        self.barra_bloque.setFormat("Bloque %p %")
        self.lbl_cuenta = QLabel("--:--")
        self.barra_total = QProgressBar()
        self.barra_total.setRange(0, 1000)
        self.barra_total.setFormat("Total %p %")
        self.btn_iniciar = QPushButton("Iniciar")
        self.btn_detener = QPushButton("Detener")
        self.btn_iniciar.setEnabled(False)
        self.btn_detener.setEnabled(False)
        for w, e in ((self.lbl_bloque, 2), (self.barra_bloque, 2), (self.lbl_cuenta, 0), (self.barra_total, 2),
                     (self.btn_iniciar, 0), (self.btn_detener, 0)):
            capa.addWidget(w, e)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)
        self.btn_iniciar.clicked.connect(self.iniciar)
        self.btn_detener.clicked.connect(self.detener)

    def cargar(self, entrenamiento: pl.EntrenamientoEstructurado) -> None:
        self.detener()
        self.entrenamiento = entrenamiento
        self.ejecutor = pl.EjecutorBloques(entrenamiento)
        self.lbl_bloque.setText(f"{entrenamiento.nombre}: {entrenamiento.resumen()}")
        self.btn_iniciar.setEnabled(True)

    def iniciar(self) -> None:
        if self.ejecutor is None:
            return
        self.ejecutor.iniciar(self.vm.tiempo())
        self.btn_detener.setEnabled(True)
        self.timer.start()
        self.tick()

    def detener(self) -> None:
        self.timer.stop()
        if self.ejecutor is not None and self.ejecutor.activo:
            self.vm.set_zona_objetivo(None)
        if self.ejecutor is not None:
            self.ejecutor.detener()
        self.btn_detener.setEnabled(False)
        self.lbl_cuenta.setText("--:--")
        self.barra_bloque.setValue(0)
        self.barra_total.setValue(0)

    def tick(self) -> None:
        if self.ejecutor is None or not self.ejecutor.activo:
            return
        e = self.ejecutor.actualizar(self.vm.tiempo())
        if e.terminado:
            self.vm.set_zona_objetivo(None)
            self.timer.stop()
            self.lbl_bloque.setText("Entrenamiento completado")
            self.lbl_cuenta.setText("00:00")
            self.barra_bloque.setValue(1000)
            self.barra_total.setValue(1000)
            self.btn_detener.setEnabled(False)
            return
        if e.cambio_de_bloque:
            self.vm.set_zona_objetivo(e.zona)
        self.lbl_bloque.setText(f"{e.bloque.nombre} · {pl.NOMBRES_ZONA[e.zona]}")
        self.lbl_cuenta.setText(_mmss(e.restante_bloque_s))
        self.barra_bloque.setValue(int(e.progreso_bloque * 1000))
        self.barra_total.setValue(int(e.progreso_total * 1000))


class PanelPlanificacion(QWidget):
    entrenamiento_cargado = Signal(object)
    sesion_iniciada = Signal(object)                    # «Iniciar ahora»: SesionPlanificada

    def __init__(self, vm, parent=None):
        super().__init__(parent)
        self.vm = vm
        self.entrenamiento: Optional[pl.EntrenamientoEstructurado] = None
        self._construido = False                       # la interfaz se crea al mostrar la pestaña (ahorra memoria)

    def showEvent(self, ev):
        self._construir()
        super().showEvent(ev)

    def _construir(self):
        if self._construido:
            return
        self._construido = True
        vm = self.vm
        raiz = QHBoxLayout(self)

        # --- Workout Builder
        izq = QVBoxLayout()
        izq.addWidget(QLabel("Workout Builder (grupo > 0: los bloques con el mismo grupo se repiten juntos)"))
        self.tabla = QTableWidget(0, 5)
        self.tabla.setHorizontalHeaderLabels(["Bloque", "Minutos", "Zona", "Grupo", "Repeticiones"])
        izq.addWidget(self.tabla)
        fila = QHBoxLayout()
        self.btn_anadir = QPushButton("Añadir bloque")
        self.btn_quitar = QPushButton("Quitar bloque")
        self.btn_cargar = QPushButton("Cargar en Tiempo Real")
        for b in (self.btn_anadir, self.btn_quitar, self.btn_cargar):
            fila.addWidget(b)
        izq.addLayout(fila)
        self.lbl_resumen = QLabel()
        izq.addWidget(self.lbl_resumen)
        raiz.addLayout(izq, 3)

        # --- Calendario
        der = QVBoxLayout()
        self.calendario = QCalendarWidget()
        self.calendario.setMinimumDate(QDate.currentDate().addMonths(-3))
        der.addWidget(self.calendario)
        self.lista = QListWidget()
        der.addWidget(self.lista)
        f2 = QHBoxLayout()
        self.edit_nombre = QLineEdit()
        self.edit_nombre.setPlaceholderText("Nombre de la sesión")
        self.spin_min = QSpinBox()
        self.spin_min.setRange(5, 600)
        self.spin_min.setValue(45)
        self.spin_min.setSuffix(" min")
        self.spin_trimp = QDoubleSpinBox()
        self.spin_trimp.setRange(0, 1000)
        self.spin_trimp.setPrefix("TRIMP ")
        self.btn_agendar = QPushButton("Agendar")
        self.btn_borrar = QPushButton("Quitar")
        for w in (self.edit_nombre, self.spin_min, self.spin_trimp, self.btn_agendar, self.btn_borrar):
            f2.addWidget(w)
        der.addLayout(f2)
        self.barra_cumpl = QProgressBar()
        self.barra_cumpl.setRange(0, 100)
        self.lbl_cumpl = QLabel()
        der.addWidget(self.lbl_cumpl)
        der.addWidget(self.barra_cumpl)
        raiz.addLayout(der, 2)

        self.btn_anadir.clicked.connect(lambda: self.anadir_bloque())
        self.btn_quitar.clicked.connect(self._quitar_bloque)
        self.btn_cargar.clicked.connect(self.cargar_en_tiempo_real)
        self.tabla.itemChanged.connect(lambda *_: self._resumen())
        self.btn_agendar.clicked.connect(self.agendar)
        self.btn_borrar.clicked.connect(self.quitar_sesion)
        self.calendario.selectionChanged.connect(self.actualizar)
        self.calendario.currentPageChanged.connect(lambda *_: self._pintar())
        vm.historial_actualizado.connect(self.actualizar)
        self.anadir_bloque("Calentamiento", 10, 0)
        self.actualizar()

    # --- Builder
    def anadir_bloque(self, nombre: str = "Bloque", minutos: float = 5, zona: int = 1, grupo: int = 0, veces: int = 1):
        f = self.tabla.rowCount()
        self.tabla.blockSignals(True)
        self.tabla.insertRow(f)
        self.tabla.setItem(f, 0, QTableWidgetItem(nombre))
        self.tabla.setItem(f, 1, QTableWidgetItem(f"{minutos:g}"))
        combo = QComboBox()
        combo.addItems(pl.NOMBRES_ZONA)
        combo.setCurrentIndex(zona)
        combo.currentIndexChanged.connect(lambda *_: self._resumen())
        self.tabla.setCellWidget(f, 2, combo)
        self.tabla.setItem(f, 3, QTableWidgetItem(str(grupo)))
        self.tabla.setItem(f, 4, QTableWidgetItem(str(veces)))
        self.tabla.blockSignals(False)
        self._resumen()

    def _quitar_bloque(self):
        f = self.tabla.currentRow()
        if f >= 0:
            self.tabla.removeRow(f)
            self._resumen()

    def construir(self) -> Optional[pl.EntrenamientoEstructurado]:
        pasos: list = []
        grupo_actual, bloques_g, veces_g = None, [], 1

        def cerrar():
            nonlocal bloques_g
            if bloques_g:
                pasos.append(pl.Repeticion(veces_g, tuple(bloques_g)))
            bloques_g = []

        try:
            for f in range(self.tabla.rowCount()):
                txt = lambda c: self.tabla.item(f, c).text().strip()
                b = pl.Bloque(txt(0) or "Bloque", int(round(float(txt(1).replace(",", ".")) * 60)),
                              self.tabla.cellWidget(f, 2).currentIndex())
                g, v = int(txt(3) or 0), max(1, int(txt(4) or 1))
                if g > 0:
                    if g != grupo_actual:
                        cerrar()
                        grupo_actual, veces_g = g, v
                    bloques_g.append(b)
                else:
                    cerrar()
                    grupo_actual = None
                    pasos.append(pl.Repeticion(v, (b,)) if v > 1 else b)
            cerrar()
        except (ValueError, AttributeError):
            return None
        return pl.EntrenamientoEstructurado("Mi entrenamiento", pasos) if pasos else None

    def _resumen(self):
        e = self.construir()
        self.entrenamiento = e
        self.lbl_resumen.setText("Revisa los valores de la tabla." if e is None else
                                 f"{e.resumen()} — total {e.duracion_total_s // 60} min")
        self.btn_cargar.setEnabled(e is not None)

    def cargar_en_tiempo_real(self):
        self._construir()
        if self.entrenamiento is not None:
            self.entrenamiento_cargado.emit(self.entrenamiento)

    # --- Calendario
    def _gestor(self) -> Optional[pl.GestorCalendarioPlanificado]:
        return None if self.vm.repositorio is None else pl.GestorCalendarioPlanificado(self.vm.repositorio)

    def _fecha(self) -> date:
        return self.calendario.selectedDate().toPython()

    def agendar(self):
        g = self._gestor()
        if g is None:
            return
        g.agendar(self._fecha(), self.edit_nombre.text() or "Sesión", self.spin_min.value(),
                  self.spin_trimp.value() or None, self.entrenamiento)
        self.edit_nombre.clear()
        self.actualizar()

    def _poner_botones(self, item, texto: str, s) -> None:
        fila = QWidget()
        fila.setStyleSheet("background:#111916;")
        h = QHBoxLayout(fila)
        h.setContentsMargins(8, 2, 8, 2)
        lbl = QLabel(texto)
        lbl.setStyleSheet("background:transparent; color:#F2F6F4;")
        b_ini = QPushButton("Iniciar ahora")
        b_ini.setStyleSheet("background:#10B981; color:#090E0C; font-weight:bold; border:none; border-radius:6px; padding:3px 10px;")
        b_del = QPushButton("Eliminar")
        b_del.setStyleSheet("background:transparent; color:#FCA5A5; border:1px solid #FCA5A5; border-radius:6px; padding:3px 10px;")
        b_ini.clicked.connect(lambda _=False, x=s: self.iniciar_ahora(x.id))
        b_del.clicked.connect(lambda _=False, x=s: self.eliminar_sesion(x.id))
        for w in (lbl,):
            h.addWidget(w, 1)
        h.addWidget(b_ini)
        h.addWidget(b_del)
        fila.btn_iniciar_ahora, fila.btn_eliminar = b_ini, b_del
        item.setSizeHint(fila.sizeHint())
        self.lista.setItemWidget(item, fila)

    def eliminar_sesion(self, sesion_id: int) -> None:
        g = self._gestor()
        if g and g.eliminar(sesion_id):
            self.vm.invalidar_zona_objetivo()
            self.actualizar()

    def iniciar_ahora(self, sesion_id: int) -> None:
        """La sesión pasa a ser el objetivo de hoy (zona y duración) y se salta a Tiempo Real."""
        g = self._gestor()
        if g is None:
            return
        hoy = date.today()
        s = next((x for x in g.entre(self._fecha(), self._fecha()) if x.id == sesion_id), None)
        if s is None:
            return
        if s.fecha != hoy:
            g.mover(sesion_id, hoy)
        g.fijar_objetivo_hoy(sesion_id, hoy)
        self.calendario.setSelectedDate(QDate(hoy.year, hoy.month, hoy.day))
        self.actualizar()
        self.sesion_iniciada.emit(s)

    def quitar_sesion(self):
        g, it = self._gestor(), self.lista.currentItem()
        if g and it:
            g.eliminar(it.data(0x0100))
            self.actualizar()

    def _pintar(self):
        g = self._gestor()
        if g is None:
            return
        self.calendario.setDateTextFormat(QDate(), QTextCharFormat())
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#1B4D3E"))
        fmt.setForeground(QColor("#F2F6F4"))
        for s in g.del_mes(self.calendario.yearShown(), self.calendario.monthShown()):
            self.calendario.setDateTextFormat(QDate(s.fecha.year, s.fecha.month, s.fecha.day), fmt)

    def actualizar(self, *_):
        g = self._gestor()
        if g is None:
            return
        d = self._fecha()
        self.lista.clear()
        for s in g.entre(d, d):
            texto = f"{s.nombre} · {s.minutos:g} min" + (f" · TRIMP {s.trimp:g}" if s.trimp else "")
            self.lista.addItem(texto)
            item = self.lista.item(self.lista.count() - 1)
            item.setData(0x0100, s.id)
            self._poner_botones(item, texto, s)
        c = g.cumplimiento_semanal(d)
        if c.pct is None:
            self.lbl_cumpl.setText("Semana sin sesiones planificadas")
            self.barra_cumpl.setValue(0)
        else:
            self.lbl_cumpl.setText(f"Cumplimiento semanal: {c.pct:.0f} % · {c.sesiones_real}/{c.sesiones_plan} sesiones · "
                                   f"{c.minutos_real:.0f}/{c.minutos_plan:.0f} min")
            self.barra_cumpl.setValue(int(c.pct))
        self._pintar()
