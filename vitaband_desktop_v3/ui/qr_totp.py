"""Código QR de la URI otpauth:// dibujado con Qt, sin depender de Pillow."""

from __future__ import annotations

import qrcode
from qrcode.constants import ERROR_CORRECT_M
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter

QUIET_ZONE = 4          # módulos blancos alrededor (mínimo del estándar QR)
ESCALA_PX = 6           # píxeles por módulo


def matriz_qr(texto: str) -> list[list[bool]]:
    """Matriz de módulos (True = negro), sin margen."""
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, border=0)
    qr.add_data(texto)
    qr.make(fit=True)
    return qr.get_matrix()


def imagen_qr(texto: str, escala: int = ESCALA_PX, margen: int = QUIET_ZONE) -> QImage:
    """QImage con el QR, fondo blanco y margen blanco (quiet zone) para que lo lea la cámara."""
    matriz = matriz_qr(texto)
    lado = (len(matriz) + 2 * margen) * escala
    imagen = QImage(lado, lado, QImage.Format.Format_RGB32)
    imagen.fill(QColor("white"))
    pintor = QPainter(imagen)
    negro_qt = QColor("black")
    for y, fila in enumerate(matriz):
        for x, negro in enumerate(fila):
            if negro:
                pintor.fillRect(QRect((x + margen) * escala, (y + margen) * escala, escala, escala), negro_qt)
    pintor.end()
    return imagen
