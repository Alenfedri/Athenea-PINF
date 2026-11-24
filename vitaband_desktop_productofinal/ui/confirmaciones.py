"""Diálogos de confirmación para acciones destructivas (RF-38, 39)."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget


def confirmar(parent: QWidget, titulo: str, texto: str, accion: str = "Eliminar") -> bool:
    """Pide confirmación explícita. «Cancelar» es la opción por defecto (Intro y Esc cancelan)."""
    caja = QMessageBox(QMessageBox.Icon.Warning, titulo, texto, QMessageBox.StandardButton.NoButton, parent)
    boton = caja.addButton(accion, QMessageBox.ButtonRole.DestructiveRole)
    cancelar = caja.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
    caja.setDefaultButton(cancelar)
    caja.setEscapeButton(cancelar)
    caja.exec()
    return caja.clickedButton() is boton
