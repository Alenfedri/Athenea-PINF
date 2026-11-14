"""Diálogo de acceso: inicio de sesión, registro y verificación MFA.

Toda la lógica de negocio está en ServicioAuth; aquí solo se recogen datos, se
muestran los mensajes de error y se avanza de pantalla.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from services import totp
from services.servicio_auth import (
    CodigoMfaInvalido,
    CredencialesInvalidas,
    CuentaBloqueada,
    CuentaDuplicada,
    DatosInvalidos,
    DesafioCaducado,
    DesafioMfa,
    ErrorAuth,
    ServicioAuth,
)

PAG_LOGIN, PAG_REGISTRO, PAG_MFA = 0, 1, 2

_ESTILO_ERROR = "color: #b00020; padding: 4px;"
_ESTILO_INFO = "color: #1b5e20; padding: 4px;"


def _campo_password() -> QLineEdit:
    campo = QLineEdit()
    campo.setEchoMode(QLineEdit.EchoMode.Password)
    return campo


class LoginDialog(QDialog):

    def __init__(self, auth: ServicioAuth, parent=None):
        super().__init__(parent)
        self._auth = auth
        self._desafio: DesafioMfa | None = None

        self.setWindowTitle("VitaBand Desktop — Acceso")
        self.setModal(True)
        self.resize(460, 420)

        self._paginas = QStackedWidget()
        self._paginas.addWidget(self._construir_login())
        self._paginas.addWidget(self._construir_registro())
        self._paginas.addWidget(self._construir_mfa())

        raiz = QVBoxLayout(self)
        raiz.addWidget(self._paginas)

        self._ir_a(PAG_LOGIN)

    # ------------------------------------------------------------------
    # CONSTRUCCIÓN
    # ------------------------------------------------------------------

    def _titulo(self, texto: str) -> QLabel:
        lbl = QLabel(texto)
        lbl.setStyleSheet("font-size: 18px; font-weight: bold; padding-bottom: 6px;")
        return lbl

    def _construir_login(self) -> QWidget:
        pagina = QWidget()
        lay = QVBoxLayout(pagina)
        lay.addWidget(self._titulo("Iniciar sesión"))

        self.login_email = QLineEdit()
        self.login_password = _campo_password()
        form = QFormLayout()
        form.addRow("Correo:", self.login_email)
        form.addRow("Contraseña:", self.login_password)
        lay.addLayout(form)

        self.login_error = QLabel()
        self.login_error.setWordWrap(True)
        lay.addWidget(self.login_error)

        self.btn_entrar = QPushButton("Continuar")
        self.btn_entrar.setDefault(True)
        self.btn_ir_registro = QPushButton("Crear cuenta nueva")
        lay.addWidget(self.btn_entrar)
        lay.addWidget(self.btn_ir_registro)
        lay.addStretch()

        self.btn_entrar.clicked.connect(self.accion_entrar)
        self.login_password.returnPressed.connect(self.accion_entrar)
        self.btn_ir_registro.clicked.connect(lambda: self._ir_a(PAG_REGISTRO))
        return pagina

    def _construir_registro(self) -> QWidget:
        pagina = QWidget()
        lay = QVBoxLayout(pagina)
        lay.addWidget(self._titulo("Crear cuenta"))

        self.reg_nombre = QLineEdit()
        self.reg_email = QLineEdit()
        self.reg_password = _campo_password()
        self.reg_password2 = _campo_password()
        form = QFormLayout()
        form.addRow("Nombre:", self.reg_nombre)
        form.addRow("Correo:", self.reg_email)
        form.addRow("Contraseña:", self.reg_password)
        form.addRow("Repetir contraseña:", self.reg_password2)
        lay.addLayout(form)

        ayuda = QLabel("La contraseña necesita al menos 10 caracteres, una letra y un número.")
        ayuda.setWordWrap(True)
        lay.addWidget(ayuda)

        self.reg_error = QLabel()
        self.reg_error.setWordWrap(True)
        lay.addWidget(self.reg_error)

        self.btn_registrar = QPushButton("Crear cuenta")
        self.btn_volver_login = QPushButton("Ya tengo cuenta")
        lay.addWidget(self.btn_registrar)
        lay.addWidget(self.btn_volver_login)
        lay.addStretch()

        self.btn_registrar.clicked.connect(self.accion_registrar)
        self.btn_volver_login.clicked.connect(lambda: self._ir_a(PAG_LOGIN))
        return pagina

    def _construir_mfa(self) -> QWidget:
        pagina = QWidget()
        lay = QVBoxLayout(pagina)
        lay.addWidget(self._titulo("Verificación en dos pasos"))

        self.mfa_instrucciones = QLabel()
        self.mfa_instrucciones.setWordWrap(True)
        lay.addWidget(self.mfa_instrucciones)

        # Solo visible al activar el MFA de una cuenta nueva
        self.mfa_secreto = QPlainTextEdit()
        self.mfa_secreto.setReadOnly(True)
        self.mfa_secreto.setMaximumHeight(110)
        lay.addWidget(self.mfa_secreto)

        self.mfa_codigo = QLineEdit()
        self.mfa_codigo.setMaxLength(7)
        self.mfa_codigo.setPlaceholderText("Código de 6 dígitos")
        self.mfa_codigo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mfa_codigo.setStyleSheet("font-size: 20px; letter-spacing: 4px;")
        lay.addWidget(self.mfa_codigo)

        self.mfa_error = QLabel()
        self.mfa_error.setWordWrap(True)
        lay.addWidget(self.mfa_error)

        fila = QHBoxLayout()
        self.btn_verificar = QPushButton("Verificar")
        self.btn_verificar.setDefault(True)
        self.btn_cancelar_mfa = QPushButton("Cancelar")
        fila.addWidget(self.btn_cancelar_mfa)
        fila.addWidget(self.btn_verificar)
        lay.addLayout(fila)
        lay.addStretch()

        self.btn_verificar.clicked.connect(self.accion_verificar)
        self.mfa_codigo.returnPressed.connect(self.accion_verificar)
        self.btn_cancelar_mfa.clicked.connect(self._cancelar_mfa)
        return pagina

    # ------------------------------------------------------------------
    # NAVEGACIÓN
    # ------------------------------------------------------------------

    def _ir_a(self, pagina: int) -> None:
        for lbl in (self.login_error, self.reg_error, self.mfa_error):
            lbl.clear()
        self._paginas.setCurrentIndex(pagina)

    @staticmethod
    def _error(etiqueta: QLabel, texto: str) -> None:
        etiqueta.setStyleSheet(_ESTILO_ERROR)
        etiqueta.setText(texto)

    def _mostrar_mfa(self, desafio: DesafioMfa) -> None:
        self._desafio = desafio
        self.mfa_codigo.clear()
        self.mfa_error.clear()

        if desafio.requiere_activacion:
            self.mfa_instrucciones.setText(
                "Añade VitaBand a tu app autenticadora (Google Authenticator, Microsoft "
                "Authenticator, Authy…) usando «Introducir clave de configuración» con esta "
                "clave, y escribe el código de 6 dígitos que genere."
            )
            self.mfa_secreto.setPlainText(
                f"Clave: {totp.secreto_legible(desafio.secreto or '')}\n\n"
                f"URI: {desafio.uri}"
            )
            self.mfa_secreto.setVisible(True)
        else:
            self.mfa_instrucciones.setText(
                "Introduce el código de 6 dígitos de tu app autenticadora."
            )
            self.mfa_secreto.clear()
            self.mfa_secreto.setVisible(False)

        self._ir_a(PAG_MFA)
        self.mfa_codigo.setFocus()

    @Slot()
    def _cancelar_mfa(self) -> None:
        self._auth.cerrar_sesion()
        self._desafio = None
        self.login_password.clear()
        self._ir_a(PAG_LOGIN)

    # ------------------------------------------------------------------
    # ACCIONES
    # ------------------------------------------------------------------

    @Slot()
    def accion_entrar(self) -> None:
        try:
            desafio = self._auth.iniciar_sesion(
                self.login_email.text(), self.login_password.text()
            )
        except (CredencialesInvalidas, CuentaBloqueada) as exc:
            self._error(self.login_error, str(exc))
            return
        except ErrorAuth as exc:
            self._error(self.login_error, str(exc))
            return

        self.login_password.clear()
        self._mostrar_mfa(desafio)

    @Slot()
    def accion_registrar(self) -> None:
        email = self.reg_email.text()
        password = self.reg_password.text()
        try:
            self._auth.registrar(
                self.reg_nombre.text(), email, password, self.reg_password2.text()
            )
        except DatosInvalidos as exc:
            self._error(self.reg_error, "\n".join(f"• {e}" for e in exc.errores))
            return
        except CuentaDuplicada as exc:
            self._error(self.reg_error, str(exc))
            return

        # Cuenta creada: se continúa con el alta del MFA, que exige la contraseña
        # recién escrita para abrir el desafío.
        try:
            desafio = self._auth.iniciar_sesion(email, password)
        except ErrorAuth as exc:
            self._error(self.reg_error, str(exc))
            return

        self.login_email.setText(email)
        for campo in (self.reg_nombre, self.reg_password, self.reg_password2):
            campo.clear()
        self._mostrar_mfa(desafio)

    @Slot()
    def accion_verificar(self) -> None:
        try:
            self._auth.verificar_mfa(self.mfa_codigo.text())
        except CodigoMfaInvalido as exc:
            self.mfa_codigo.clear()
            self._error(self.mfa_error, str(exc))
            return
        except CuentaBloqueada as exc:
            self._error(self.mfa_error, str(exc))
            return
        except DesafioCaducado as exc:
            self._ir_a(PAG_LOGIN)  # limpia los mensajes; el error se pone después
            self._error(self.login_error, str(exc))
            return
        except ErrorAuth as exc:
            self._error(self.mfa_error, str(exc))
            return

        self.accept()
