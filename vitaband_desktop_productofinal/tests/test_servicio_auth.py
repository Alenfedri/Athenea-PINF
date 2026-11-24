import unittest

from services import totp
from services.repositorio_cuentas import RepositorioCuentas
from services.servicio_auth import (
    CodigoMfaInvalido,
    CredencialesInvalidas,
    CuentaBloqueada,
    CuentaDuplicada,
    DatosInvalidos,
    DesafioCaducado,
    ServicioAuth,
    SesionNoIniciada,
)

EMAIL = "ana@ejemplo.com"
PASSWORD = "clave-segura-123"


class Reloj:
    def __init__(self, t=1_700_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def avanzar(self, s):
        self.t += s


class BaseAuth(unittest.TestCase):

    def setUp(self):
        self.reloj = Reloj()
        self.repo = RepositorioCuentas(":memory:")
        self.auth = ServicioAuth(self.repo, reloj=self.reloj, max_intentos=3, bloqueo_s=300)

    def tearDown(self):
        self.repo.cerrar()

    def registrar(self, email=EMAIL, password=PASSWORD):
        return self.auth.registrar("Ana", email, password, password)

    def codigo(self, secreto):
        return totp.codigo_actual(secreto, self.reloj())

    def login_completo(self, secreto, email=EMAIL, password=PASSWORD):
        self.auth.iniciar_sesion(email, password)
        return self.auth.verificar_mfa(self.codigo(secreto))

    def cuenta_activa(self):
        """Registra y activa el MFA como un usuario real; devuelve (id, secreto vigente).

        Ojo: el secreto de registrar() se sustituye al completar el alta en el
        primer login, así que el vigente es el del desafío.
        """
        r = self.registrar()
        d = self.auth.iniciar_sesion(EMAIL, PASSWORD)
        self.auth.verificar_mfa(self.codigo(d.secreto))
        self.auth.cerrar_sesion()
        self.reloj.avanzar(60)          # paso TOTP nuevo (anti-reutilización)
        return r.usuario_id, d.secreto


class TestRegistro(BaseAuth):

    def test_registro_correcto(self):
        r = self.registrar()
        self.assertGreater(r.usuario_id, 0)
        self.assertTrue(r.uri.startswith("otpauth://"))

    def test_datos_invalidos(self):
        with self.assertRaises(DatosInvalidos) as ctx:
            self.auth.registrar("A", "mal", "x", "y")
        self.assertTrue(ctx.exception.errores)

    def test_bloquea_cuenta_duplicada_sin_importar_mayusculas(self):
        self.registrar()
        with self.assertRaises(CuentaDuplicada):
            self.registrar(email="  ANA@Ejemplo.com ")

    def test_la_contrasena_no_se_guarda_en_claro(self):
        self.registrar()
        fila = self.repo._conn.execute("SELECT pw_hash, pw_sal FROM usuarios").fetchone()
        self.assertNotIn(PASSWORD.encode(), bytes(fila["pw_hash"]) + bytes(fila["pw_sal"]))
        self.assertEqual(len(fila["pw_hash"]), 32)


class TestLoginYMfa(BaseAuth):

    def test_flujo_completo(self):
        r = self.registrar()
        d = self.auth.iniciar_sesion(EMAIL, PASSWORD)
        self.assertTrue(d.requiere_activacion)           # MFA aún sin activar
        sesion = self.auth.verificar_mfa(self.codigo(d.secreto))
        self.assertEqual(sesion.usuario_id, r.usuario_id)
        self.assertEqual(self.auth.requerir_sesion(), sesion)

        self.auth.cerrar_sesion()
        self.reloj.avanzar(60)
        d2 = self.auth.iniciar_sesion(EMAIL.upper(), PASSWORD)
        self.assertFalse(d2.requiere_activacion)         # ya activado
        self.assertIsNone(d2.secreto)

    def test_credenciales_incorrectas_mismo_mensaje(self):
        self.registrar()
        with self.assertRaises(CredencialesInvalidas) as a:
            self.auth.iniciar_sesion(EMAIL, "otra-clave-999")
        with self.assertRaises(CredencialesInvalidas) as b:
            self.auth.iniciar_sesion("nadie@ejemplo.com", PASSWORD)
        self.assertEqual(str(a.exception), str(b.exception))

    def test_sin_mfa_no_hay_sesion(self):
        self.registrar()
        self.auth.iniciar_sesion(EMAIL, PASSWORD)
        self.assertIsNone(self.auth.sesion_actual)
        with self.assertRaises(SesionNoIniciada):
            self.auth.requerir_sesion()
        with self.assertRaises(CodigoMfaInvalido):
            self.auth.verificar_mfa("000000")
        self.assertIsNone(self.auth.sesion_actual)

    def test_verificar_sin_paso_uno(self):
        with self.assertRaises(DesafioCaducado):
            self.auth.verificar_mfa("123456")

    def test_desafio_caduca(self):
        r = self.registrar()
        self.auth.iniciar_sesion(EMAIL, PASSWORD)
        self.reloj.avanzar(301)
        with self.assertRaises(DesafioCaducado):
            self.auth.verificar_mfa(self.codigo(r.secreto))

    def test_codigo_no_se_puede_reutilizar(self):
        _, secreto = self.cuenta_activa()
        self.login_completo(secreto)
        self.auth.cerrar_sesion()
        self.auth.iniciar_sesion(EMAIL, PASSWORD)
        with self.assertRaises(CodigoMfaInvalido):       # mismo código, mismo paso
            self.auth.verificar_mfa(self.codigo(secreto))
        self.reloj.avanzar(30)
        self.auth.verificar_mfa(self.codigo(secreto))    # código del paso siguiente

    def test_alta_mfa_sin_terminar_emite_secreto_nuevo(self):
        r = self.registrar()
        d = self.auth.iniciar_sesion(EMAIL, PASSWORD)
        self.assertNotEqual(d.secreto, r.secreto)
        with self.assertRaises(CodigoMfaInvalido):       # el secreto viejo ya no vale
            self.auth.verificar_mfa(self.codigo(r.secreto))
        self.auth.verificar_mfa(self.codigo(d.secreto))


class TestCierreDeSesion(BaseAuth):

    def test_tras_cerrar_sesion_no_hay_acceso(self):
        _, secreto = self.cuenta_activa()
        self.login_completo(secreto)
        self.assertIsNotNone(self.auth.sesion_actual)
        self.auth.cerrar_sesion()
        self.assertIsNone(self.auth.sesion_actual)
        with self.assertRaises(SesionNoIniciada):
            self.auth.requerir_sesion()
        # y el desafío tampoco queda abierto
        self.reloj.avanzar(30)
        with self.assertRaises(DesafioCaducado):
            self.auth.verificar_mfa(self.codigo(secreto))

    def test_iniciar_sesion_destruye_la_anterior(self):
        _, secreto = self.cuenta_activa()
        self.login_completo(secreto)
        with self.assertRaises(CredencialesInvalidas):
            self.auth.iniciar_sesion(EMAIL, "otra-clave-999")
        self.assertIsNone(self.auth.sesion_actual)


class TestBloqueo(BaseAuth):

    def test_bloqueo_tras_intentos_fallidos_y_desbloqueo(self):
        r = self.registrar()
        for _ in range(3):
            with self.assertRaises(CredencialesInvalidas):
                self.auth.iniciar_sesion(EMAIL, "otra-clave-999")
        with self.assertRaises(CuentaBloqueada) as ctx:   # incluso con la clave buena
            self.auth.iniciar_sesion(EMAIL, PASSWORD)
        self.assertGreater(ctx.exception.segundos, 0)

        self.reloj.avanzar(301)
        d = self.auth.iniciar_sesion(EMAIL, PASSWORD)
        self.auth.verificar_mfa(self.codigo(d.secreto))

    def test_codigos_mfa_erroneos_tambien_bloquean(self):
        self.registrar()
        self.auth.iniciar_sesion(EMAIL, PASSWORD)
        for _ in range(3):
            with self.assertRaises(CodigoMfaInvalido):
                self.auth.verificar_mfa("000000")
        with self.assertRaises(CuentaBloqueada):
            self.auth.verificar_mfa("000000")


if __name__ == "__main__":
    unittest.main()
