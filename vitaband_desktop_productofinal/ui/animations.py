"""Animaciones centralizadas (estética Apple / Linear): QPropertyAnimation/QVariantAnimation con OutCubic.

Reglas: todo en el hilo principal de Qt, sin bloquear; una animación nueva cancela la anterior del mismo
widget; el QGraphicsOpacityEffect se retira SIEMPRE al terminar o interrumpirse (las gráficas ECG/PyQtGraph
nunca quedan con un efecto gráfico activo). Se desactivan en pruebas sin pantalla o con
VITABAND_SIN_ANIMACIONES=1 (los valores finales se aplican al instante).
"""
from __future__ import annotations

import math

from PySide6.QtCore import (QEasingCurve, QEvent, QObject, QParallelAnimationGroup, QPauseAnimation, QPoint,
                            QPropertyAnimation, QSequentialAnimationGroup, Qt, QTimer, QVariantAnimation)
from PySide6.QtGui import QColor, QPainter, QRadialGradient
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QGraphicsView, QLabel, QPushButton, QWidget

from ui.animaciones_vitaband import animaciones_activas

BASE = "#264B3F"
ACENTO = "#10B981"
_OUT = QEasingCurve.Type.OutCubic


def _vivo(w) -> bool:
    try:
        w.objectName()
        return True
    except RuntimeError:
        return False


def _cancelar(widget: QWidget) -> None:
    previa = getattr(widget, "_vb_fade", None)
    if previa is not None:
        previa.stop()
        widget._vb_fade = None
    if _vivo(widget):
        widget.setGraphicsEffect(None)


def fade_slide_in(widget: QWidget, duration: int = 200, offset_y: int = 12, delay: int = 0, forzar: bool = False):
    """Opacidad 0→1 + micro-desplazamiento vertical. Retira el efecto gráfico al terminar."""
    if widget is None or not (forzar or animaciones_activas()):
        return None
    _cancelar(widget)
    # Prohibido QGraphicsEffect sobre gráficas (pyqtgraph/QGraphicsView): provoca cierres nativos al hacer scroll
    if isinstance(widget, QGraphicsView) or widget.findChildren(QGraphicsView):
        return None
    efecto = QGraphicsOpacityEffect(widget)
    efecto.setOpacity(0.0)
    widget.setGraphicsEffect(efecto)
    pos = widget.pos()
    grupo = QSequentialAnimationGroup(widget)
    if delay:
        grupo.addAnimation(QPauseAnimation(delay))
    par = QParallelAnimationGroup()
    op = QPropertyAnimation(efecto, b"opacity")
    op.setDuration(duration)
    op.setStartValue(0.0)
    op.setEndValue(1.0)
    op.setEasingCurve(_OUT)
    par.addAnimation(op)
    if offset_y and widget.parentWidget() is not None:
        mov = QPropertyAnimation(widget, b"pos")
        mov.setDuration(duration)
        mov.setStartValue(QPoint(pos.x(), pos.y() + offset_y))
        mov.setEndValue(pos)
        mov.setEasingCurve(_OUT)
        par.addAnimation(mov)
        par.stateChanged.connect(lambda *_: None)
    grupo.addAnimation(par)

    def _fin(w=widget, p=pos):
        if _vivo(w):
            w.setGraphicsEffect(None)
            if offset_y and w.parentWidget() is not None and w.pos() != p and w.parentWidget().layout() is None:
                w.move(p)
        w._vb_fade = None

    grupo.finished.connect(_fin)
    widget._vb_fade = grupo
    grupo.start()
    return grupo


def stagger_widgets(widgets, delay_step: int = 40, duration: int = 200) -> None:
    """Entrada en cascada de tarjetas / KPIs."""
    for i, w in enumerate(widgets):
        fade_slide_in(w, duration=duration, offset_y=8, delay=i * delay_step)


def animate_number(label: QLabel, start_val: float, end_val: float, suffix: str = "", decimals: int = 0,
                   duration: int = 350):
    """Interpola un valor numérico en una etiqueta (BPM, TRIMP, TSB, HRV…)."""
    previa = getattr(label, "_vb_num", None)
    if previa is not None:
        previa.stop()
        label._vb_num = None
    final = f"{end_val:.{decimals}f}{suffix}"
    if not animaciones_activas() or start_val == end_val or not label.isVisible():
        label.setText(final)
        return None
    anim = QVariantAnimation(label)
    anim.setStartValue(float(start_val))
    anim.setEndValue(float(end_val))
    anim.setDuration(duration)
    anim.setEasingCurve(_OUT)
    anim.valueChanged.connect(lambda v: label.setText(f"{v:.{decimals}f}{suffix}") if _vivo(label) else None)
    anim.finished.connect(lambda: label.setText(final) if _vivo(label) else None)
    label._vb_num = anim
    anim.start()
    return anim


def _mezcla(a: str, b: str, t: float) -> str:
    ca, cb = QColor(a), QColor(b)
    return QColor(int(ca.red() + (cb.red() - ca.red()) * t), int(ca.green() + (cb.green() - ca.green()) * t),
                  int(ca.blue() + (cb.blue() - ca.blue()) * t)).name()


class _Glow(QObject):
    def __init__(self, widget: QWidget, base: str, hover: str, duration: int):
        super().__init__(widget)
        self.w, self.base, self.hover = widget, base, hover
        self.orig = widget.styleSheet()
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(duration)
        self.anim.setEasingCurve(_OUT)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.valueChanged.connect(self._paso)
        self.anim.finished.connect(self._fin)
        widget.installEventFilter(self)

    def _paso(self, t) -> None:
        c = _mezcla(self.base, self.hover, float(t))
        if self.base.lower() in self.orig.lower():
            ss = self.orig.replace(self.base, c).replace(self.base.lower(), c).replace(self.base.upper(), c)
        else:
            ss = self.orig + f"\n{self.w.metaObject().className()} {{ border-color: {c}; }}"
        self.w.setStyleSheet(ss)

    def _fin(self) -> None:
        if self.anim.currentValue() == 0.0:
            self.w.setStyleSheet(self.orig)

    def eventFilter(self, obj, ev):
        if obj is self.w and ev.type() in (QEvent.Type.Enter, QEvent.Type.Leave) and animaciones_activas():
            self.anim.stop()
            self.anim.setDirection(QVariantAnimation.Direction.Forward if ev.type() == QEvent.Type.Enter
                                   else QVariantAnimation.Direction.Backward)
            self.anim.start()
        return False


def install_hover_glow(widget: QWidget, base_border: str = BASE, hover_border: str = ACENTO, duration: int = 150):
    """Ilumina suavemente el borde de una tarjeta o botón al pasar el ratón. Idempotente."""
    if widget is None or getattr(widget, "_vb_glow", None) is not None:
        return None
    widget._vb_glow = _Glow(widget, base_border, hover_border, duration)
    return widget._vb_glow


def decorate(raiz: QWidget) -> None:
    """Instala el brillo hover en tarjetas (card=true/elevated) y botones de acción bajo ``raiz``."""
    for w in raiz.findChildren(QFrame):
        if w.property("card") in ("true", "elevated"):
            install_hover_glow(w)
    for b in raiz.findChildren(QPushButton):
        install_hover_glow(b)


def pulse_on_beat(label: QLabel, color_pulso: str = "#6EE7B7", color_base: str = ACENTO, duration: int = 240) -> None:
    """Destello breve del texto sincronizado con cada pico R (limitado a una animación activa)."""
    if not animaciones_activas() or not label.isVisible():
        return
    previa = getattr(label, "_vb_beat", None)
    if previa is not None:
        previa.stop()
    anim = QVariantAnimation(label)
    anim.setStartValue(1.0)
    anim.setEndValue(0.0)
    anim.setDuration(duration)
    anim.setEasingCurve(_OUT)
    base_ss = getattr(label, "_vb_beat_base", None)
    if base_ss is None:
        base_ss = label._vb_beat_base = label.styleSheet()
    anim.valueChanged.connect(lambda t: label.setStyleSheet(base_ss + f" color: {_mezcla(color_base, color_pulso, float(t))};")
                              if _vivo(label) else None)
    anim.finished.connect(lambda: label.setStyleSheet(base_ss) if _vivo(label) else None)
    label._vb_beat = anim
    anim.start()


def show_toast(parent: QWidget, message: str, icon: str = "✓", duration: int = 2600):
    """Píldora flotante abajo a la derecha: entra deslizándose hacia arriba y se desvanece sola."""
    if parent is None:
        return None
    ventana = parent.window()
    toast = QLabel(f"{icon}  {message}", ventana)
    toast.setStyleSheet("QLabel { background: #162C25; color: #E7F5EF; border: 1px solid #264B3F; "
                        "border-radius: 16px; padding: 9px 18px; font-size: 13px; }")
    toast.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    toast.adjustSize()
    activos = [t for t in getattr(ventana, "_vb_toasts", []) if _vivo(t)]
    ventana._vb_toasts = activos + [toast]
    x = ventana.width() - toast.width() - 24
    y = ventana.height() - toast.height() - 24 - len(activos) * (toast.height() + 8)
    toast.move(x, y)
    toast.show()
    toast.raise_()

    def _quitar():
        if _vivo(toast):
            toast.deleteLater()
        if toast in getattr(ventana, "_vb_toasts", []):
            ventana._vb_toasts.remove(toast)

    if not animaciones_activas():
        t = QTimer(toast)
        t.setSingleShot(True)
        t.timeout.connect(_quitar)
        t.start(duration)
        return toast
    efecto = QGraphicsOpacityEffect(toast)
    toast.setGraphicsEffect(efecto)
    entra = QParallelAnimationGroup()
    o = QPropertyAnimation(efecto, b"opacity")
    o.setDuration(220)
    o.setStartValue(0.0)
    o.setEndValue(1.0)
    m = QPropertyAnimation(toast, b"pos")
    m.setDuration(260)
    m.setStartValue(QPoint(x, y + 22))
    m.setEndValue(QPoint(x, y))
    m.setEasingCurve(_OUT)
    entra.addAnimation(o)
    entra.addAnimation(m)
    sale = QPropertyAnimation(efecto, b"opacity")
    sale.setDuration(350)
    sale.setStartValue(1.0)
    sale.setEndValue(0.0)
    sale.setEasingCurve(_OUT)
    sec = QSequentialAnimationGroup(toast)
    sec.addAnimation(entra)
    sec.addAnimation(QPauseAnimation(max(0, duration - 600)))
    sec.addAnimation(sale)
    sec.finished.connect(_quitar)
    sec.start()
    return toast


class EsferaRespiracion(QWidget):
    """Esfera de Coherencia Cardíaca: respira con interpolación sinusoidal continua (periodo = ciclo guiado)."""

    def __init__(self, periodo_s: float = 10.0, parent=None):
        super().__init__(parent)
        self._fase = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(int(periodo_s * 1000))
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._paso)
        self.setMinimumSize(120, 120)

    def _paso(self, v) -> None:
        self._fase = float(v)
        self.update()

    def iniciar(self) -> None:
        if animaciones_activas():
            self._anim.start()

    def detener(self) -> None:
        self._anim.stop()

    def hideEvent(self, ev) -> None:
        self.detener()
        super().hideEvent(ev)

    def paintEvent(self, _ev) -> None:
        e = (1 - math.cos(2 * math.pi * self._fase)) / 2          # 0 = espirado, 1 = inspirado (senoidal)
        r = min(self.width(), self.height()) / 2
        radio = r * (0.55 + 0.4 * e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = QRadialGradient(self.rect().center(), radio)
        g.setColorAt(0, QColor("#6EE7B7"))
        g.setColorAt(0.6, QColor(ACENTO))
        g.setColorAt(1, QColor(16, 185, 129, 40))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(self.rect().center(), radio, radio)
        p.end()
