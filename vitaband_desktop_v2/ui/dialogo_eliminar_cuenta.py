"""Segunda confirmación de la eliminación de cuenta (RF-39).

Exige escribir la palabra ELIMINAR y la contraseña: no se puede hacer por un clic accidental.
La contraseña se comprueba después en ``ServicioAuth.eliminar_cuenta``.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

PALABRA_CLAVE = "ELIMINAR"


class DialogoEliminarCuenta(QDialog):

    def __init__(self, nombre_usuario: str, parent: QWidget = None):
        super().__init__(parent)
        self.setWindowTitle("Eliminar cuenta definitivamente")
        self.setModal(True)

        capa = QVBoxLayout(self)
        aviso = QLabel(
            f"<b>Vas a eliminar de forma permanente la cuenta de {nombre_usuario or 'este usuario'}.</b><br><br>"
            "Se borrarán todas sus mediciones, actividades, ECG y observaciones guardadas en este equipo. "
            "No se puede deshacer.<br><br>"
            "No se borran las copias fuera de la aplicación: archivos CSV exportados, paquetes de la "
            "carpeta de intercambio y datos del móvil."
        )
        aviso.setWordWrap(True)
        capa.addWidget(aviso)

        form = QFormLayout()
        self.campo_palabra = QLineEdit()
        self.campo_palabra.setPlaceholderText(PALABRA_CLAVE)
        self.campo_password = QLineEdit()
        self.campo_password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(f"Escribe {PALABRA_CLAVE} para confirmar", self.campo_palabra)
        form.addRow("Contraseña", self.campo_password)
        capa.addLayout(form)

        self.botones = QDialogButtonBox()
        self.btn_eliminar = self.botones.addButton(
            "Eliminar cuenta definitivamente", QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_cancelar = self.botones.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        self.btn_cancelar.setDefault(True)
        self.btn_eliminar.setEnabled(False)
        capa.addWidget(self.botones)

        self.botones.accepted.connect(self.accept)
        self.botones.rejected.connect(self.reject)
        self.campo_palabra.textChanged.connect(self._revisar)
        self.campo_password.textChanged.connect(self._revisar)

    def _revisar(self) -> None:
        self.btn_eliminar.setEnabled(
            self.campo_palabra.text().strip() == PALABRA_CLAVE and bool(self.campo_password.text()))

    def password(self) -> str:
        return self.campo_password.text()
