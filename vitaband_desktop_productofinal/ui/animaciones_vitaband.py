"""Animaciones fluidas de VitaBand: fundidos de pestañas, pulso cardíaco, KPIs, paneles, barras y hover de tarjetas.

Reglas: todo QGraphicsOpacityEffect se retira (setGraphicsEffect(None)) al terminar o al detener la animación,
y los temporizadores/animaciones en bucle se detienen en closeEvent/hideEvent.
"""
from __future__ import annotations

import os
import re

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, QVariantAnimation, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QProgressBar, QTabWidget, QWidget

DURACION_MS = 180
_NUM = re.compile(r"-?\d+(?:[.,]\d+)?")


def animaciones_activas() -> bool:
    """Desactivables por entorno (VITABAND_SIN_ANIMACIONES=1) y en pruebas sin pantalla (offscreen)."""
    if os.environ.get("VITABAND_SIN_ANIMACIONES"):
        return False
    app = QApplication.instance()
    return not (app is not None and app.platformName() == "offscreen")


def fundido(widget: QWidget, ms: int = DURACION_MS) -> QPropertyAnimation | None:
    """Aparición OutCubic; el efecto de opacidad se retira siempre al acabar o al interrumpirse."""
    if widget is None:
        return None
    from PySide6.QtWidgets import QGraphicsView        # nunca QGraphicsEffect sobre/encima de gráficas pyqtgraph
    if isinstance(widget, QGraphicsView) or widget.findChildren(QGraphicsView):
        return None
    previa = getattr(widget, "_anim_fundido", None)
    if previa is not None:
        previa.stop()
        widget.setGraphicsEffect(None)
    efecto = QGraphicsOpacityEffect(widget)
    efecto.setOpacity(0.0)
    widget.setGraphicsEffect(efecto)
    anim = QPropertyAnimation(efecto, b"opacity", widget)
    anim.setDuration(ms)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    anim.finished.connect(lambda w=widget: (w.setGraphicsEffect(None), setattr(w, "_anim_fundido", None)))
    widget._anim_fundido = anim
    anim.start()
    return anim


def detener_fundido(widget: QWidget) -> None:
    anim = getattr(widget, "_anim_fundido", None)
    if anim is not None:
        anim.stop()
        widget.setGraphicsEffect(None)
        widget._anim_fundido = None


def suavizar_barra(barra: QProgressBar, valor: int, ms: int = 220) -> None:
    anim = getattr(barra, "_anim_valor", None)
    if anim is not None:
        anim.stop()
    if not barra.isVisible() or not animaciones_activas():
        barra.setValue(valor)
        return
    anim = QPropertyAnimation(barra, b"value", barra)
    anim.setDuration(ms)
    anim.setStartValue(barra.value())
    anim.setEndValue(valor)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    barra._anim_valor = anim
    anim.start()


def desplegar(panel: QWidget, visible: bool, ms: int = DURACION_MS) -> None:
    """Despliegue/pliegue animado por altura máxima; al terminar se liberan los límites."""
    anim = getattr(panel, "_anim_altura", None)
    if anim is not None:
        anim.stop()
    if not animaciones_activas() or not panel.window().isVisible():
        panel.setMaximumHeight(16777215)
        panel.setVisible(visible)
        return
    if visible:
        panel.setMaximumHeight(0)
        panel.setVisible(True)
        destino = max(panel.sizeHint().height(), 60)
    else:
        destino = 0
    anim = QPropertyAnimation(panel, b"maximumHeight", panel)
    anim.setDuration(ms)
    anim.setStartValue(panel.height() if not visible else 0)
    anim.setEndValue(destino)
    anim.setEasingCurve(QEasingCurve.OutCubic)

    def fin():
        panel.setMaximumHeight(16777215)
        if not visible:
            panel.setVisible(False)
    anim.finished.connect(fin)
    panel._anim_altura = anim
    anim.start()


class AnimadorVitaBand(QObject):
    """Controlador de animaciones de una ventana (hijo de ella: se destruye con ella)."""

    def __init__(self, ventana: QWidget, habilitado: bool | None = None):
        super().__init__(ventana)
        self._ventana = ventana
        self.habilitado = animaciones_activas() if habilitado is None else habilitado
        self._pulsos: dict[QWidget, QVariantAnimation] = {}
        self._kpis: dict[QWidget, QVariantAnimation] = {}
        self._hover: dict[QWidget, tuple] = {}

    # --- Pestañas y sub-pestañas ---
    def instalar_pestanas(self) -> None:
        for tw in [self._ventana, *self._ventana.findChildren(QTabWidget)]:
            if isinstance(tw, QTabWidget) and not tw.property("_fundido"):
                tw.setProperty("_fundido", True)
                tw.currentChanged.connect(self._cambio_pestana)

    @Slot(int)
    def _cambio_pestana(self, _indice: int) -> None:
        tw = self.sender()
        if self.habilitado and isinstance(tw, QTabWidget) and tw.isVisible():
            from ui import animations
            animations.decorate(tw.currentWidget())
            animations.fade_slide_in(tw.currentWidget(), 200, 10, forzar=True)

    # --- Pulso cardíaco luminoso (punto de conexión y tarjeta BPM) ---
    def pulso(self, widget: QWidget, activo: bool, color_base: str, color_pulso: str, estilo=None) -> None:
        """Latido de ~1 s mientras `activo`. `estilo(color)` devuelve la hoja de estilo para ese color."""
        anim = self._pulsos.get(widget)
        if not activo or not self.habilitado:
            if anim is not None:
                anim.stop()
                self._pulsos.pop(widget, None)
                if estilo:
                    widget.setStyleSheet(estilo(color_base))
            return
        if anim is not None:
            return
        a, b = QColor(color_base), QColor(color_pulso)
        anim = QVariantAnimation(self)
        anim.setDuration(1000)
        anim.setStartValue(0.0)
        anim.setKeyValueAt(0.18, 1.0)
        anim.setKeyValueAt(0.34, 0.25)
        anim.setKeyValueAt(0.5, 0.8)
        anim.setEndValue(0.0)
        anim.setLoopCount(-1)

        def paso(t, w=widget):
            c = QColor(int(a.red() + (b.red() - a.red()) * t), int(a.green() + (b.green() - a.green()) * t),
                       int(a.blue() + (b.blue() - a.blue()) * t))
            if estilo:
                w.setStyleSheet(estilo(c.name()))
        anim.valueChanged.connect(paso)
        self._pulsos[widget] = anim
        anim.start()

    # --- Interpolación numérica de KPIs conservando unidades ---
    def texto_kpi(self, etiqueta, texto: str, ms: int = 300) -> None:
        """setText con interpolación del primer número («FC: 72 BPM» → 75 …), conservando prefijo y unidades."""
        previo = self._kpis.get(etiqueta)
        if previo is not None:
            previo.stop()
        nuevo = _NUM.search(texto)
        antiguo = _NUM.search(etiqueta.text())
        if not self.habilitado or nuevo is None or antiguo is None or not etiqueta.isVisible():
            etiqueta.setText(texto)
            return
        decimales = len(nuevo.group().replace(",", ".").split(".")[1]) if "." in nuevo.group().replace(",", ".") else 0
        v0, v1 = float(antiguo.group().replace(",", ".")), float(nuevo.group().replace(",", "."))
        if v0 == v1:
            etiqueta.setText(texto)
            return
        pre, post = texto[:nuevo.start()], texto[nuevo.end():]
        anim = QVariantAnimation(self)
        anim.setDuration(ms)
        anim.setStartValue(v0)
        anim.setEndValue(v1)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.valueChanged.connect(lambda v: etiqueta.setText(f"{pre}{v:.{decimales}f}{post}"))
        anim.finished.connect(lambda: etiqueta.setText(texto))
        self._kpis[etiqueta] = anim
        anim.start()

    # --- Realce hover en tarjetas (card="true") ---
    def hover_tarjeta(self, tarjeta: QWidget, color_hover: str = "#10B981") -> None:
        base = tarjeta.styleSheet()
        anim = QVariantAnimation(self)
        anim.setDuration(160)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        self._hover[tarjeta] = (base, anim)
        anim.valueChanged.connect(lambda t, w=tarjeta, b=base: w.setStyleSheet(
            b + f" QFrame[card=\"true\"] {{ border: 1px solid rgba(16, 185, 129, {int(40 + 215 * t)}); }}"))
        anim.finished.connect(lambda w=tarjeta, b=base, an=anim: w.setStyleSheet(b) if an.currentValue() == 0.0 else None)
        tarjeta.installEventFilter(self)

    def eventFilter(self, obj, ev):
        datos = self._hover.get(obj)
        if datos and self.habilitado and ev.type() in (QEvent.Enter, QEvent.Leave):
            anim = datos[1]
            anim.stop()
            anim.setDirection(QVariantAnimation.Forward if ev.type() == QEvent.Enter else QVariantAnimation.Backward)
            anim.start()
        return False

    # --- Limpieza ---
    def detener(self) -> None:
        for anim in [*self._pulsos.values(), *self._kpis.values(), *(a for _, a in self._hover.values())]:
            anim.stop()
        self._pulsos.clear()
        for w, (base, _) in self._hover.items():
            w.setStyleSheet(base)
        for tw in self._ventana.findChildren(QWidget):
            if getattr(tw, "_anim_fundido", None) is not None:
                detener_fundido(tw)
