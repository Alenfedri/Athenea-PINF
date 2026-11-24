"""Exportación rápida de una gráfica a PNG (sin generar un PDF completo)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFileDialog, QMessageBox, QPushButton, QWidget

ESCALA = 2          # alta resolución: el doble de píxeles que en pantalla


def captura_alta_resolucion(widget: QWidget) -> QPixmap:
    ancho, alto = max(widget.width(), 1), max(widget.height(), 1)
    pm = QPixmap(ancho * ESCALA, alto * ESCALA)
    pm.setDevicePixelRatio(ESCALA)
    pm.fill()
    QWidget.render(widget, pm)      # evita el render() propio de pyqtgraph.GraphicsView
    return pm


def exportar_grafica_png(widget: QWidget, nombre_base: str, parent: Optional[QWidget] = None) -> Optional[str]:
    """Pide dónde guardar y escribe la captura del widget. Devuelve la ruta o None si se cancela/falla."""
    padre = parent or widget
    sugerido = f"{nombre_base}_{datetime.now():%Y-%m-%d_%H%M}.png"
    ruta, _ = QFileDialog.getSaveFileName(padre, "Exportar gráfica a PNG", sugerido, "Imágenes PNG (*.png)")
    if not ruta:
        return None
    if not ruta.lower().endswith(".png"):
        ruta += ".png"
    if not captura_alta_resolucion(widget).save(ruta, "PNG"):
        QMessageBox.warning(padre, "No se pudo exportar", f"No se pudo escribir la imagen en:\n{ruta}")
        return None
    from ui import animations
    animations.show_toast(padre, "Imagen PNG exportada")
    return ruta


def boton_png(widget, nombre_base: str) -> QPushButton:
    """Botón compacto «PNG». ``widget`` puede ser el widget o una función que lo devuelva (se evalúa al pulsar)."""
    boton = QPushButton("PNG")
    boton.setFixedWidth(48)
    boton.setToolTip("Guardar esta gráfica como imagen PNG")
    boton.clicked.connect(lambda: exportar_grafica_png(widget() if callable(widget) else widget, nombre_base))
    return boton
