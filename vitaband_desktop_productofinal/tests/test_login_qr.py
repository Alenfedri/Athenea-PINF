"""Login tras un fallo (bloqueo por intentos, Enter, estado limpio) y QR del alta de TOTP."""

import os
import tempfile
import unittest
from urllib.parse import parse_qs, unquote, urlparse

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import qrcode
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from services import totp
from services.repositorio_cuentas import RepositorioCuentas
from services.servicio_auth import CredencialesInvalidas, CuentaBloqueada, ServicioAuth
from ui.login_dialog import LoginDialog, PAG_LOGIN, PAG_MFA
from ui.qr_totp import QUIET_ZONE, imagen_qr, matriz_qr

_app = QApplication.instance() or QApplication([])
EMAIL, PASSWORD = "ana@correo.com", "Clave-Segura-123"


class BaseCuenta(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.t = [1_700_000_000.0]
        self.repo = RepositorioCuentas(os.path.join(self.dir.name, "t.db"))
        self.auth = ServicioAuth(self.repo, reloj=lambda: self.t[0])
        self.auth.registrar("Ana", EMAIL, PASSWORD, PASSWORD)

    def tearDown(self):
        self.repo.cerrar()
        self.dir.cleanup()


class TestLoginTrasFallo(BaseCuenta):

    def test_fallo_y_despues_contrasena_correcta(self):
        with self.assertRaises(CredencialesInvalidas):
            self.auth.iniciar_sesion(EMAIL, "equivocada1")
        desafio = self.auth.iniciar_sesion(EMAIL, PASSWORD)          # el caso reportado
        self.assertEqual(desafio.usuario_id, self.repo.obtener_por_email(EMAIL).id)

    def test_varios_fallos_por_debajo_del_umbral_no_impiden_entrar(self):
        for _ in range(4):
            with self.assertRaises(CredencialesInvalidas):
                self.auth.iniciar_sesion(EMAIL, "equivocada1")
        self.auth.iniciar_sesion(EMAIL, PASSWORD)

    def test_fallo_y_exito_completo_con_mfa(self):
        with self.assertRaises(CredencialesInvalidas):
            self.auth.iniciar_sesion(EMAIL, "equivocada1")
        d = self.auth.iniciar_sesion(EMAIL, PASSWORD)
        sesion = self.auth.verificar_mfa(totp.codigo_actual(d.secreto, self.t[0]))
        self.assertEqual(sesion.email, EMAIL)
        self.assertEqual(self.repo.obtener_por_email(EMAIL).intentos_fallidos, 0)   # contador limpio

    def test_el_estado_interno_queda_limpio_tras_un_fallo(self):
        self.auth.iniciar_sesion(EMAIL, PASSWORD)
        with self.assertRaises(CredencialesInvalidas):
            self.auth.iniciar_sesion(EMAIL, "equivocada1")
        self.assertIsNone(self.auth._desafio)            # el desafío anterior no sobrevive
        self.assertIsNone(self.auth.sesion_actual)

    def test_bloqueo_a_los_cinco_fallos_con_mensaje_claro_y_desbloqueo(self):
        for _ in range(5):
            with self.assertRaises(CredencialesInvalidas):
                self.auth.iniciar_sesion(EMAIL, "equivocada1")
        with self.assertRaises(CuentaBloqueada) as ctx:
            self.auth.iniciar_sesion(EMAIL, PASSWORD)               # ni la correcta vale bloqueada
        self.assertIn("bloqueada temporalmente", str(ctx.exception))
        self.t[0] += 301
        self.auth.iniciar_sesion(EMAIL, PASSWORD)                   # pasado el bloqueo, entra


class TestLoginDialog(BaseCuenta):

    def setUp(self):
        super().setUp()
        self.dlg = LoginDialog(self.auth)
        self.dlg.show()
        self.dlg.login_email.setText(EMAIL)
        self.llamadas = []
        original = self.auth.iniciar_sesion
        self.auth.iniciar_sesion = lambda *a: (self.llamadas.append(a), original(*a))[1]

    def tearDown(self):
        self.dlg.close()
        super().tearDown()

    def enter_con(self, texto):
        self.dlg.login_password.setFocus()
        QTest.keyClicks(self.dlg.login_password, texto)
        QTest.keyClick(self.dlg.login_password, Qt.Key.Key_Return)

    def test_fallo_y_luego_acierto_por_boton(self):
        self.dlg.login_password.setText("equivocada1")
        self.dlg.accion_entrar()
        self.assertIn("incorrectos", self.dlg.login_error.text())
        self.assertEqual(self.dlg.login_password.text(), "")         # no se arrastra el texto anterior
        self.dlg.login_password.setText(PASSWORD)
        self.dlg.accion_entrar()
        self.assertEqual(self.dlg._paginas.currentIndex(), PAG_MFA)

    def test_un_enter_es_un_solo_intento(self):
        self.enter_con("equivocada1")
        self.assertEqual(len(self.llamadas), 1)                      # antes eran 2 y bloqueaba a la 3.ª vez
        self.assertEqual(self.repo.obtener_por_email(EMAIL).intentos_fallidos, 1)

    def test_con_teclado_fallo_y_acierto(self):
        self.enter_con("equivocada1")
        self.enter_con(PASSWORD)                                     # el campo se vació tras el fallo
        self.assertEqual(self.dlg._paginas.currentIndex(), PAG_MFA)
        self.assertEqual(len(self.llamadas), 2)

    def test_tres_fallos_con_enter_no_bloquean(self):
        for _ in range(3):
            self.enter_con("equivocada1")
        self.enter_con(PASSWORD)
        self.assertEqual(self.dlg._paginas.currentIndex(), PAG_MFA)

    def test_bloqueo_muestra_mensaje_claro(self):
        for _ in range(5):
            self.enter_con("equivocada1")
        self.enter_con(PASSWORD)
        self.assertEqual(self.dlg._paginas.currentIndex(), PAG_LOGIN)
        self.assertIn("bloqueada temporalmente", self.dlg.login_error.text())

    def test_enter_en_el_codigo_mfa_verifica_una_sola_vez(self):
        self.dlg.login_password.setText(PASSWORD)
        self.dlg.accion_entrar()
        llamadas = []
        original = self.auth.verificar_mfa
        self.auth.verificar_mfa = lambda c: (llamadas.append(c), original(c))[1]
        self.dlg.mfa_codigo.setFocus()
        QTest.keyClicks(self.dlg.mfa_codigo, "000000")
        QTest.keyClick(self.dlg.mfa_codigo, Qt.Key.Key_Return)
        self.assertEqual(len(llamadas), 1)


class TestQr(BaseCuenta):

    def uri(self):
        return self.auth.iniciar_sesion(EMAIL, PASSWORD).uri

    def test_uri_otpauth_estandar(self):
        u = urlparse(self.uri())
        self.assertEqual(u.scheme, "otpauth")
        self.assertEqual(u.netloc, "totp")
        self.assertEqual(unquote(u.path), f"/VitaBand:{EMAIL}")
        q = parse_qs(u.query)
        self.assertEqual(q["issuer"], ["VitaBand"])
        self.assertRegex(q["secret"][0], r"^[A-Z2-7]+$")

    def test_matriz_valida_y_contiene_la_uri(self):
        uri = self.uri()
        m = matriz_qr(uri)
        n = len(m)
        self.assertTrue(all(len(f) == n for f in m))
        self.assertEqual((n - 17) % 4, 0)                            # lado = 17 + 4·versión
        self.assertTrue(21 <= n <= 177)
        # La matriz es exactamente la del QR de esa URI (mismo texto de entrada)
        ref = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0)
        ref.add_data(uri)
        ref.make(fit=True)
        self.assertEqual(m, ref.get_matrix())
        self.assertEqual(b"".join(d.data for d in ref.data_list), uri.encode())

    def test_imagen_con_margen_blanco_y_modulos_negros(self):
        uri = self.uri()
        n = len(matriz_qr(uri))
        esc = 6
        img = imagen_qr(uri, escala=esc)
        self.assertEqual(img.width(), (n + 2 * QUIET_ZONE) * esc)
        self.assertEqual(img.width(), img.height())
        blanco, negro = QColor("white").rgb(), QColor("black").rgb()
        lado = img.width()
        for i in range(lado):                                        # el borde de 4 módulos es blanco
            for k in range(QUIET_ZONE * esc):
                for x, y in ((k, i), (lado - 1 - k, i), (i, k), (i, lado - 1 - k)):
                    self.assertEqual(img.pixel(x, y), blanco)
        # esquina del localizador (módulo 0,0): siempre negra
        self.assertEqual(img.pixel(QUIET_ZONE * esc + 1, QUIET_ZONE * esc + 1), negro)

    def test_el_dialogo_muestra_qr_y_clave_en_el_alta(self):
        dlg = LoginDialog(self.auth)
        dlg.show()
        dlg.login_email.setText(EMAIL)
        dlg.login_password.setText(PASSWORD)
        dlg.accion_entrar()
        self.assertTrue(dlg.mfa_qr.isVisible())
        self.assertFalse(dlg.mfa_qr.pixmap().isNull())
        self.assertIn("Clave:", dlg.mfa_secreto.toPlainText())       # la clave sigue visible y copiable
        self.assertIn("otpauth://", dlg.mfa_secreto.toPlainText())
        dlg.close()

    def test_sin_qr_cuando_el_mfa_ya_esta_activo(self):
        d = self.auth.iniciar_sesion(EMAIL, PASSWORD)
        self.auth.verificar_mfa(totp.codigo_actual(d.secreto, self.t[0]))
        self.auth.cerrar_sesion()
        dlg = LoginDialog(self.auth)
        dlg.show()
        dlg.login_email.setText(EMAIL)
        dlg.login_password.setText(PASSWORD)
        dlg.accion_entrar()
        self.assertFalse(dlg.mfa_qr.isVisible())
        dlg.close()


if __name__ == "__main__":
    unittest.main()
