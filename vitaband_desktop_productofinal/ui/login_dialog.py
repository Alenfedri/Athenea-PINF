"""Diálogo de acceso: inicio de sesión, registro y verificación MFA.

Toda la lógica de negocio está en ServicioAuth; aquí solo se recogen datos, se
muestran los mensajes de error y se avanza de pantalla.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
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
from ui.portada_auth_widget import LuxuryGradientButton, PortadaAuthWidget
from ui.qr_totp import imagen_qr
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

_ESTILO_ERROR = "color: #FCA5A5; padding: 4px; background: transparent;"
_ESTILO_INFO = "color: #6EE7B7; padding: 4px; background: transparent;"
_ESTILO_ENLACE = ("QPushButton { color: #CBD5E1; font-size: 13px; text-decoration: underline; background: transparent; "
                  "border: none; } QPushButton:hover { color: #10B981; }")
_ESTILO_TARJETA = """
    QLabel { color: #CBD5E1; background: transparent; }
    QPlainTextEdit { background-color: rgba(9, 14, 12, 210); color: #F8FAFC; border: 1.3px solid #1B4D3E; border-radius: 10px; }
"""


def _campo_password() -> QLineEdit:
    campo = QLineEdit()
    campo.setEchoMode(QLineEdit.EchoMode.Password)
    return campo


class LoginDialog(QDialog):

    def __init__(self, auth: ServicioAuth, parent=None):
        super().__init__(parent)
        self._auth = auth
        self._desafio: DesafioMfa | None = None

        self.setWindowTitle("VitaBand App · Grupo Athenea")
        self.setModal(True)
        self.resize(1100, 700)
        self.setWindowState(Qt.WindowState.WindowMaximized)       # portada a pantalla completa

        self._paginas = QStackedWidget()
        self._paginas.addWidget(self._construir_login())
        self._paginas.addWidget(self._construir_registro())
        self._paginas.addWidget(self._construir_mfa())

        # Portada de lujo: los formularios reales se reparentan dentro de la AccessCard
        self.portada = PortadaAuthWidget(parent=self, formularios=False)
        self.portada.montar_formularios(self._paginas)
        self.portada.access_card.setStyleSheet(self.portada.access_card.styleSheet() + _ESTILO_TARJETA)
        self.portada.tab_header.tabChanged.connect(self._desde_selector)
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.addWidget(self.portada)

        for b in (self.portada.tab_header.btn_tab_login, self.portada.tab_header.btn_tab_signup, self.btn_olvide,
                  self.btn_ir_registro, self.btn_volver_login, self.btn_cancelar_mfa):
            b.setAutoDefault(False)                   # Enter solo activa el botón principal de cada página
        self.btn_entrar.setDefault(True)
        self._ir_a(PAG_LOGIN)

    # ------------------------------------------------------------------
    # CONSTRUCCIÓN
    # ------------------------------------------------------------------

    def _titulo(self, texto: str) -> QLabel:
        lbl = QLabel(texto)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("font-size: 22px; font-weight: 700; color: #F8FAFC; padding-bottom: 6px; background: transparent;")
        return lbl

    def _construir_login(self) -> QWidget:
        pagina = QWidget()
        lay = QVBoxLayout(pagina)
        lay.addWidget(self._titulo("Acceso a tu cuenta"))

        self.login_email = QLineEdit()
        self.login_email.setPlaceholderText("Correo Electrónico")
        self.login_password = _campo_password()
        self.login_password.setPlaceholderText("Contraseña")
        form = QFormLayout()
        form.addRow("Correo:", self.login_email)
        form.addRow("Contraseña:", self.login_password)
        lay.addLayout(form)

        self.login_error = QLabel()
        self.login_error.setWordWrap(True)
        lay.addWidget(self.login_error)

        self.chk_recordar = QCheckBox("Recordar sesión")
        self.chk_recordar.setToolTip("Recuerda solo tu correo en este equipo; la contraseña nunca se guarda")
        lay.addWidget(self.chk_recordar)
        self.btn_entrar = LuxuryGradientButton("INICIAR SESIÓN")
        self.btn_entrar.setDefault(True)
        self.btn_olvide = QPushButton("Olvidé mi contraseña?")
        self.btn_ir_registro = QPushButton("Crear cuenta nueva")
        lay.addWidget(self.btn_entrar)
        for enlace in (self.btn_olvide, self.btn_ir_registro):
            enlace.setFlat(True)
            enlace.setCursor(Qt.CursorShape.PointingHandCursor)
            enlace.setStyleSheet(_ESTILO_ENLACE)
            lay.addWidget(enlace, alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addStretch()
        self.btn_olvide.clicked.connect(lambda: self._error(
            self.login_error, "La contraseña no se puede recuperar por correo en esta versión local: "
                              "si la has olvidado, crea una cuenta nueva."))
        self._cargar_correo_recordado()

        self.btn_entrar.clicked.connect(self.accion_entrar)
        self.login_email.returnPressed.connect(self.login_password.setFocus)
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

        self.btn_registrar = LuxuryGradientButton("CREAR CUENTA")
        self.btn_volver_login = QPushButton("Ya tengo cuenta")
        self.btn_volver_login.setFlat(True)
        self.btn_volver_login.setStyleSheet(_ESTILO_ENLACE)
        lay.addWidget(self.btn_registrar)
        lay.addWidget(self.btn_volver_login, alignment=Qt.AlignmentFlag.AlignCenter)
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

        # Solo visibles al activar el MFA de una cuenta nueva: QR y, debajo, la clave en texto
        self.mfa_qr = QLabel()
        self.mfa_qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mfa_qr.setVisible(False)
        lay.addWidget(self.mfa_qr)

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
        self.btn_verificar = LuxuryGradientButton("VERIFICAR")
        self.btn_verificar.setDefault(True)
        self.btn_cancelar_mfa = QPushButton("Cancelar")
        fila.addWidget(self.btn_cancelar_mfa)
        fila.addWidget(self.btn_verificar)
        lay.addLayout(fila)
        lay.addStretch()

        self.btn_verificar.clicked.connect(self.accion_verificar)
        self.btn_cancelar_mfa.clicked.connect(self._cancelar_mfa)
        return pagina

    # ------------------------------------------------------------------
    # NAVEGACIÓN
    # ------------------------------------------------------------------

    def _ir_a(self, pagina: int) -> None:
        for lbl in (self.login_error, self.reg_error, self.mfa_error):
            lbl.clear()
        self._paginas.setCurrentIndex(pagina)
        if hasattr(self, "portada"):
            self.portada.mostrar_pagina(pagina)

    def _desde_selector(self, indice: int) -> None:
        self._ir_a(PAG_LOGIN if indice == 0 else PAG_REGISTRO)

    _CLAVE_CORREO = "acceso/correo_recordado"

    def _cargar_correo_recordado(self) -> None:
        try:
            correo = QSettings("VitaBand", "Desktop").value(self._CLAVE_CORREO, "")
        except Exception:
            correo = ""
        if correo:
            self.login_email.setText(str(correo))
            self.chk_recordar.setChecked(True)

    def _recordar_correo(self) -> None:
        try:
            ajustes = QSettings("VitaBand", "Desktop")
            if self.chk_recordar.isChecked():
                ajustes.setValue(self._CLAVE_CORREO, self.login_email.text().strip())
            else:
                ajustes.remove(self._CLAVE_CORREO)
        except Exception:
            pass

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
                "Escanea el código QR con tu app autenticadora (Google Authenticator, Microsoft "
                "Authenticator, Authy…), o añade la clave a mano con «Introducir clave de "
                "configuración», y escribe el código de 6 dígitos que genere."
            )
            self.mfa_secreto.setPlainText(
                f"Clave: {totp.secreto_legible(desafio.secreto or '')}\n\n"
                f"URI: {desafio.uri}"
            )
            self.mfa_secreto.setVisible(True)
            self.mfa_qr.setPixmap(QPixmap.fromImage(imagen_qr(desafio.uri)))
            self.mfa_qr.setVisible(True)
        else:
            self.mfa_instrucciones.setText(
                "Introduce el código de 6 dígitos de tu app autenticadora."
            )
            self.mfa_secreto.clear()
            self.mfa_secreto.setVisible(False)
            self.mfa_qr.clear()
            self.mfa_qr.setVisible(False)

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
        except ErrorAuth as exc:
            self._error(self.login_error, str(exc))
            self.login_password.clear()          # el siguiente intento empieza de cero
            self.login_password.setFocus()
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

        self._recordar_correo()
        self.accept()
