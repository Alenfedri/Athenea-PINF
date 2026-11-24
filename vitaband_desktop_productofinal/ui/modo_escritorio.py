"""Modo Escritorio (Pausa por estrés): píldora de vigilancia, icono de bandeja, pausa de respiración guiada y balance."""
from __future__ import annotations

import math
import time
from typing import Optional

from PySide6.QtCore import QObject, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QIcon, QPainter, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import (
    QApplication, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMenu, QPushButton, QSystemTrayIcon,
    QToolButton, QVBoxLayout, QWidget, QWidgetAction,
)

from domain import estres_cognitivo as ec

DURACION_PAUSA_S = 60.0
INHALA_S, EXHALA_S = 4.0, 6.0
POSPONER_S = 10 * 60
FONDO, VERDE, TEXTO, SALVIA = "#090E0C", "#10B981", "#F2F6F4", "#8BA096"


def icono_estado(color_hex: str, lado: int = 64) -> QIcon:
    """Icono circular vectorial (renderizado con QPainter) del color del estado autonómico."""
    pm = QPixmap(lado, lado)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor(color_hex)
    grad = QRadialGradient(QPointF(lado * 0.4, lado * 0.38), lado * 0.6)
    grad.setColorAt(0, c.lighter(135))
    grad.setColorAt(1, c)
    p.setBrush(QBrush(grad))
    p.setPen(QPen(QColor(FONDO), lado * 0.06))
    p.drawEllipse(QRectF(lado * 0.08, lado * 0.08, lado * 0.84, lado * 0.84))
    p.end()
    return QIcon(pm)


def fase_respiracion(t: float) -> tuple[str, float]:
    """(«Inhala»/«Exhala», radio relativo 0..1) para el instante t del ciclo de 10 s (4 s inhala, 6 s exhala)."""
    c = t % (INHALA_S + EXHALA_S)
    if c < INHALA_S:
        return "Inhala", 0.5 - 0.5 * math.cos(math.pi * c / INHALA_S)
    return "Exhala", 0.5 + 0.5 * math.cos(math.pi * (c - INHALA_S) / EXHALA_S)


class PausaEstresOverlay(QWidget):
    """Tarjeta flotante (abajo a la derecha) con círculo de coherencia a ~60 FPS y micro-pausa de 60 s."""
    completada = Signal()
    pospuesta = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(340, 430)
        self.transcurrido = 0.0
        self.bpm_inicio: Optional[float] = None
        self.bpm: Optional[float] = None
        self.rmssd: Optional[float] = None
        self.finalizada = False
        self._ultimo: Optional[float] = None

        self.lbl_fase = QLabel("Inhala")
        self.lbl_fase.setAlignment(Qt.AlignCenter)
        self.lbl_fase.setStyleSheet(f"color: {VERDE}; font-size: 18px; font-weight: bold;")
        self.lbl_tiempo = QLabel("60 s")
        self.lbl_tiempo.setAlignment(Qt.AlignCenter)
        self.lbl_tiempo.setStyleSheet(f"color: {SALVIA}; font-size: 13px;")
        self.lbl_datos = QLabel()
        self.lbl_datos.setAlignment(Qt.AlignCenter)
        self.lbl_datos.setStyleSheet(f"color: {TEXTO}; font-size: 13px;")
        self.btn_completar = QPushButton("Completar pausa")
        self.btn_posponer = QPushButton("Posponer 10 min")
        self.btn_completar.setStyleSheet(f"background:{VERDE}; color:{FONDO}; font-weight:bold; border:none; "
                                         "border-radius:8px; padding:6px 12px; min-height:30px;")
        self.btn_posponer.setStyleSheet(f"background:#17221E; color:{TEXTO}; border:1px solid #21312B; "
                                        "border-radius:8px; padding:6px 12px; min-height:30px;")
        self.btn_completar.clicked.connect(self._completar)
        self.btn_posponer.clicked.connect(self._posponer)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        titulo = QLabel("Pausa por estrés")
        titulo.setAlignment(Qt.AlignCenter)
        titulo.setStyleSheet(f"color: {TEXTO}; font-size: 15px; font-weight: bold;")
        lay.addWidget(titulo)
        lay.addSpacing(190)                                        # hueco del círculo (se pinta en paintEvent)
        for w in (self.lbl_fase, self.lbl_tiempo, self.lbl_datos):
            lay.addWidget(w)
        fila = QHBoxLayout()
        fila.addWidget(self.btn_completar)
        fila.addWidget(self.btn_posponer)
        lay.addLayout(fila)

        self._timer = QTimer(self)                                 # ~60 FPS
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._efecto: Optional[QGraphicsOpacityEffect] = None
        self._anim: Optional[QPropertyAnimation] = None

    # --- ciclo de vida ---
    def iniciar(self, bpm: Optional[float] = None, rmssd: Optional[float] = None) -> None:
        self.transcurrido, self.finalizada, self._ultimo = 0.0, False, None
        self.bpm_inicio = self.bpm = bpm
        self.rmssd = rmssd
        self._refrescar_texto()
        self._colocar()
        self.setWindowOpacity(1.0)
        self._efecto = QGraphicsOpacityEffect(self)                # fundido de entrada; se retira al terminar
        self._efecto.setOpacity(0.0)
        self.setGraphicsEffect(self._efecto)
        self._anim = QPropertyAnimation(self._efecto, b"opacity", self)
        self._anim.setDuration(250)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.finished.connect(self._fin_animacion)
        self.show()
        self._anim.start()
        self._timer.start()

    def _fin_animacion(self) -> None:
        self.setGraphicsEffect(None)
        self._efecto = None

    def _colocar(self) -> None:
        pantalla = QGuiApplication.primaryScreen()
        if pantalla is not None:
            g = pantalla.availableGeometry()
            self.move(g.right() - self.width() - 24, g.bottom() - self.height() - 24)

    def detener_timers(self) -> None:
        self._timer.stop()
        if self._anim is not None:
            self._anim.stop()
        self.setGraphicsEffect(None)
        self._efecto = None

    def actualizar_datos(self, bpm: Optional[float], rmssd: Optional[float]) -> None:
        self.bpm, self.rmssd = bpm, rmssd
        if self.bpm_inicio is None:
            self.bpm_inicio = bpm
        self._refrescar_texto()

    @property
    def descenso_bpm(self) -> Optional[float]:
        if self.bpm_inicio is None or self.bpm is None:
            return None
        return self.bpm_inicio - self.bpm

    def _refrescar_texto(self) -> None:
        bpm = "--" if self.bpm is None else f"{self.bpm:.0f}"
        rmssd = "--" if self.rmssd is None else f"{self.rmssd:.0f}"
        d = self.descenso_bpm
        extra = "" if d is None else f" · Descenso {d:.0f} BPM"
        self.lbl_datos.setText(f"BPM {bpm} · RMSSD {rmssd} ms{extra}")

    def _tick(self, dt: Optional[float] = None) -> None:
        if dt is None:
            ahora = time.monotonic()
            dt = 0.0 if self._ultimo is None else min(ahora - self._ultimo, 0.25)
            self._ultimo = ahora
        if not self.finalizada:
            self.transcurrido = min(DURACION_PAUSA_S, self.transcurrido + dt)
            if self.transcurrido >= DURACION_PAUSA_S:
                self.finalizada = True
                self.lbl_fase.setText("Pausa completada")
        if not self.finalizada:
            self.lbl_fase.setText(fase_respiracion(self.transcurrido)[0])
        self.lbl_tiempo.setText(f"{max(0, math.ceil(DURACION_PAUSA_S - self.transcurrido))} s")
        self.update()

    def _completar(self) -> None:
        self.detener_timers()
        self.hide()
        self.completada.emit()

    def _posponer(self) -> None:
        self.detener_timers()
        self.hide()
        self.pospuesta.emit()

    def hideEvent(self, ev) -> None:
        self._timer.stop()
        super().hideEvent(ev)

    def closeEvent(self, ev) -> None:
        self.detener_timers()
        super().closeEvent(ev)

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(FONDO))
        p.setPen(QPen(QColor(VERDE), 2))
        p.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 18, 18)
        centro = QPointF(self.width() / 2, 40 + 100)
        _, k = fase_respiracion(self.transcurrido)
        radio = 38 + 52 * k
        halo = QRadialGradient(centro, radio * 1.25)
        halo.setColorAt(0, QColor(16, 185, 129, 170))
        halo.setColorAt(0.7, QColor(16, 185, 129, 70))
        halo.setColorAt(1, QColor(16, 185, 129, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(halo))
        p.drawEllipse(centro, radio * 1.25, radio * 1.25)
        p.setBrush(QColor("#1B4D3E"))
        p.setPen(QPen(QColor("#34D399"), 2))
        p.drawEllipse(centro, radio, radio)
        p.end()


class BarraBalanceMental(QWidget):
    """Barra apilada compacta: foco calmado (verde) · tensión (ámbar) · estrés (rojo)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(14)
        self.setMinimumWidth(180)
        self._pct = (0.0, 0.0, 0.0)

    def fijar(self, calma: float, tension: float, estres: float) -> None:
        self._pct = (calma, tension, estres)
        self.update()

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#21312B"))
        p.drawRoundedRect(self.rect(), 6, 6)
        x, ancho = 0.0, float(self.width())
        for pct, estado in zip(self._pct, ec.ESTADOS):
            w = ancho * pct / 100.0
            if w > 0:
                p.setBrush(QColor(ec.COLORES[estado]))
                p.drawRoundedRect(QRectF(x, 0, w, self.height()), 6, 6)
                x += w
        p.end()


class _Punto(QWidget):
    """Punto luminoso con pulso suave del color del estado."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(18, 18)
        self.color = ec.COLORES[ec.CALMA]
        self.fase = 0.0

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor(self.color)
        a = 0.35 + 0.35 * (0.5 + 0.5 * math.sin(self.fase))
        g = QRadialGradient(QPointF(9, 9), 9)
        g.setColorAt(0, QColor(c.red(), c.green(), c.blue(), int(255 * a + 60)))
        g.setColorAt(1, QColor(c.red(), c.green(), c.blue(), 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QPointF(9, 9), 9, 9)
        p.setBrush(c)
        p.drawEllipse(QPointF(9, 9), 4.5, 4.5)
        p.end()


class PildoraVigilancia(QFrame):
    """«Vigilancia estrés: ACTIVA» + «Minimizar a bandeja»; al pulsar el texto muestra el balance del día."""
    minimizar_solicitado = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"QFrame#pildora {{ background:#111916; border:1px solid {VERDE}; border-radius:14px; }} "
                           f"QToolButton, QPushButton {{ color:{TEXTO}; border:none; background:transparent; font-size:12px; }}")
        self.setObjectName("pildora")
        self.punto = _Punto()
        self.btn_estado = QToolButton()
        self.btn_estado.setText("Vigilancia estrés: ACTIVA")
        self.btn_estado.setStyleSheet(f"color:{TEXTO}; font-weight:bold; font-size:12px; border:none;")
        self.btn_estado.setToolTip("Pulsa para ver el balance de carga mental de hoy")
        self.btn_minimizar = QPushButton("Minimizar a bandeja")
        self.btn_minimizar.setStyleSheet(f"color:{VERDE}; border:none; font-size:12px; padding:0 6px;")
        self.btn_minimizar.clicked.connect(self.minimizar_solicitado)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 2, 8, 2)
        lay.setSpacing(6)
        for w in (self.punto, self.btn_estado, self.btn_minimizar):
            lay.addWidget(w)

        self.menu_balance = QMenu(self.btn_estado)
        self.barra_balance = BarraBalanceMental()
        self.lbl_balance = QLabel("Aún sin datos de hoy")
        cont = QWidget()
        v = QVBoxLayout(cont)
        v.setContentsMargins(12, 8, 12, 8)
        t = QLabel("Balance de carga mental · hoy")
        t.setStyleSheet("font-weight: bold;")
        for w in (t, self.barra_balance, self.lbl_balance):
            v.addWidget(w)
        wa = QWidgetAction(self.menu_balance)
        wa.setDefaultWidget(cont)
        self.menu_balance.addAction(wa)
        self.btn_estado.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_estado.setMenu(self.menu_balance)
        self.menu_balance.aboutToShow.connect(lambda: self.alMostrarBalance and self.alMostrarBalance())
        self.alMostrarBalance = None

        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._pulso)
        self.activa = False
        self.setVisible(False)

    def _pulso(self) -> None:
        self.punto.fase += 0.25
        self.punto.update()

    def fijar_estado(self, estado: Optional[str]) -> None:
        self.punto.color = ec.COLORES.get(estado, ec.COLORES[ec.CALMA])
        self.punto.update()

    def fijar_balance(self, calma: float, tension: float, estres: float, texto: str) -> None:
        self.barra_balance.fijar(calma, tension, estres)
        self.lbl_balance.setText(texto)

    def activar(self, activa: bool) -> None:
        self.activa = activa
        self.setVisible(activa)
        if activa:
            self._timer.start()
        else:
            self._timer.stop()

    def detener_timers(self) -> None:
        self._timer.stop()

    def hideEvent(self, ev) -> None:
        self._timer.stop()
        super().hideEvent(ev)

    def showEvent(self, ev) -> None:
        if self.activa:
            self._timer.start()
        super().showEvent(ev)


class ControladorModoEscritorio(QObject):
    """Une el monitor de estrés, la bandeja, la píldora, el overlay y el balance diario."""

    def __init__(self, ventana, vm, pildora: PildoraVigilancia, monitor=None, balance=None):
        super().__init__(ventana)
        self.ventana, self.vm, self.pildora = ventana, vm, pildora
        self.monitor = monitor or ec.MonitorEstresCognitivo(reloj=vm._reloj)
        self.balance = balance
        self.activo = False
        self.bandeja: Optional[QSystemTrayIcon] = None
        self.overlay: Optional[PausaEstresOverlay] = None
        self._rmssd: Optional[float] = None
        self._bpm: Optional[float] = None
        self._pospuesto_hasta = 0.0
        self.pausas_lanzadas = 0
        self._timer_volcado = QTimer(self)
        self._timer_volcado.setInterval(30_000)
        self._timer_volcado.timeout.connect(self.refrescar_balance)
        pildora.minimizar_solicitado.connect(self.minimizar_a_bandeja)
        pildora.alMostrarBalance = self.refrescar_balance
        vm.state_changed.connect(self._on_estado)
        vm.rmssd_calculado.connect(self._on_rmssd)

    # --- activación ---
    def fijar_activo(self, activo: bool) -> None:
        activo = bool(activo)
        if activo == self.activo:
            return
        self.activo = activo
        self.pildora.activar(activo)
        if activo:
            self.monitor.reiniciar()
            self._timer_volcado.start()
            self._crear_bandeja()
            self.refrescar_balance()
        else:
            self._timer_volcado.stop()
            self.volcar_balance()
            self._cerrar_bandeja()
            if self.overlay is not None:
                self.overlay.detener_timers()
                self.overlay.hide()

    def _crear_bandeja(self) -> None:
        if self.bandeja is not None or not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.bandeja = QSystemTrayIcon(icono_estado(ec.COLORES[ec.CALMA]), self.ventana)
        menu = QMenu()
        self._menu_bandeja = menu
        a1 = menu.addAction("Restaurar VitaBand App")
        a2 = menu.addAction("Simular alerta de estrés (Demo)")
        a3 = menu.addAction("Desactivar Modo Escritorio")
        a1.triggered.connect(self.restaurar)
        a2.triggered.connect(self.simular_alerta)
        a3.triggered.connect(lambda: self.ventana.chk_escritorio.setChecked(False))
        self.acciones_bandeja = (a1, a2, a3)
        self.bandeja.setContextMenu(menu)
        self.bandeja.setToolTip("VitaBand · Vigilancia de estrés")
        self.bandeja.activated.connect(lambda r: r == QSystemTrayIcon.DoubleClick and self.restaurar())
        self.bandeja.show()

    def _cerrar_bandeja(self) -> None:
        if self.bandeja is not None:
            self.bandeja.hide()
            self.bandeja.deleteLater()
            self.bandeja = None

    def minimizar_a_bandeja(self) -> None:
        if self.bandeja is not None:
            self.bandeja.showMessage("VitaBand sigue vigilando tu estrés",
                                     "Doble clic en el icono para restaurar la ventana.",
                                     QSystemTrayIcon.Information, 4000)
            self.ventana.hide()
        else:
            self.ventana.showMinimized()                           # sin bandeja disponible: minimiza a la barra de tareas

    def restaurar(self) -> None:
        self.ventana.showNormal()
        self.ventana.raise_()
        self.ventana.activateWindow()

    # --- telemetría ---
    @Slot(float)
    def _on_rmssd(self, v: float) -> None:
        self._rmssd = v if v > 0 else None

    @Slot(object)
    def _on_estado(self, st) -> None:
        try:
            self._bpm = float(st.bpmTexto.split()[0].replace(",", "."))
        except (ValueError, IndexError, AttributeError):
            self._bpm = None
        if self.activo:
            self.procesar(self._bpm, self._rmssd)

    def procesar(self, bpm: Optional[float], rmssd: Optional[float], t: Optional[float] = None) -> None:
        if not self.activo:
            return
        lec = self.monitor.actualizar(bpm, rmssd, t)
        self._pintar_estado(lec.estado)
        if self.overlay is not None and self.overlay.isVisible():
            self.overlay.actualizar_datos(bpm, rmssd)
        ahora = self.vm._reloj() if t is None else t
        if lec.alerta and ahora >= self._pospuesto_hasta:
            self.lanzar_pausa(bpm, rmssd)

    def _pintar_estado(self, estado: Optional[str]) -> None:
        self.pildora.fijar_estado(estado)
        if self.bandeja is not None and estado is not None:
            self.bandeja.setIcon(icono_estado(ec.COLORES[estado]))

    # --- pausa ---
    def simular_alerta(self) -> None:
        """Demo: abre la pausa aunque no haya estrés real (también si el modo está desactivado)."""
        self.lanzar_pausa(self._bpm, self._rmssd)

    def lanzar_pausa(self, bpm: Optional[float] = None, rmssd: Optional[float] = None) -> PausaEstresOverlay:
        if self.overlay is None:
            self.overlay = PausaEstresOverlay(self.ventana)
            self.overlay.pospuesta.connect(self._posponer)
            self.overlay.completada.connect(lambda: None)
        self.pausas_lanzadas += 1
        self.overlay.iniciar(bpm, rmssd)
        return self.overlay

    def _posponer(self) -> None:
        self._pospuesto_hasta = self.vm._reloj() + POSPONER_S

    # --- balance ---
    def volcar_balance(self) -> None:
        acum = self.monitor.vaciar_acumulado()
        if self.balance is not None:
            try:
                self.balance.sumar(acum[ec.CALMA], acum[ec.TENSION], acum[ec.ESTRES])
            except Exception:
                pass

    def refrescar_balance(self) -> None:
        self.volcar_balance()
        if self.balance is None:
            return
        b = self.balance.dia()
        self.pildora.fijar_balance(*b.porcentajes(), b.texto())
        for vista in getattr(self.ventana, "_vistas_balance", ()):
            vista(b)

    def detener(self) -> None:
        """Para todos los temporizadores y cierra overlay/bandeja (closeEvent de la ventana)."""
        self._timer_volcado.stop()
        self.pildora.detener_timers()
        if self.activo:
            self.volcar_balance()
        if self.overlay is not None:
            self.overlay.detener_timers()
            self.overlay.hide()
        self._cerrar_bandeja()


class ResumenBalanceMental(QWidget):
    """Barra apilada + texto del balance de hoy (para Historial y Análisis avanzado)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.barra = BarraBalanceMental()
        self.lbl = QLabel("Balance de carga mental · hoy: aún sin datos")
        self.lbl.setStyleSheet(f"color: {SALVIA}; font-size: 12px;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.lbl)
        lay.addWidget(self.barra, 1)

    def fijar(self, b) -> None:
        self.barra.fijar(*b.porcentajes())
        self.lbl.setText("Carga mental · hoy: " + b.texto())
