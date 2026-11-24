import unittest

from services import totp

# Secreto de prueba del RFC 6238 (SHA-1): ASCII "12345678901234567890"
SECRETO_RFC = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


class TestTotp(unittest.TestCase):

    def test_vectores_rfc6238(self):
        # Valores de 8 dígitos del RFC; aquí se comparan sus 6 últimos dígitos
        casos = {
            59: "287082",
            1111111109: "081804",
            1111111111: "050471",
            1234567890: "005924",
            2000000000: "279037",
            20000000000: "353130",
        }
        for t, esperado in casos.items():
            self.assertEqual(totp.codigo_actual(SECRETO_RFC, t), esperado, t)

    def test_verificar_acepta_ventana_y_rechaza_fuera(self):
        t = 1_700_000_000
        cod = totp.codigo_actual(SECRETO_RFC, t)
        self.assertIsNotNone(totp.verificar(SECRETO_RFC, cod, t))
        self.assertIsNotNone(totp.verificar(SECRETO_RFC, cod, t + 30))   # un paso de desfase
        self.assertIsNone(totp.verificar(SECRETO_RFC, cod, t + 120))     # demasiado tarde

    def test_no_se_puede_reutilizar_un_paso(self):
        t = 1_700_000_000
        cod = totp.codigo_actual(SECRETO_RFC, t)
        paso = totp.verificar(SECRETO_RFC, cod, t)
        self.assertIsNone(totp.verificar(SECRETO_RFC, cod, t, ultimo_paso_usado=paso))

    def test_formato_invalido(self):
        for malo in ("", "12345", "1234567", "abcdef", None):
            self.assertIsNone(totp.verificar(SECRETO_RFC, malo, 59))

    def test_espacios_en_el_codigo(self):
        cod = totp.codigo_actual(SECRETO_RFC, 59)
        self.assertIsNotNone(totp.verificar(SECRETO_RFC, f"{cod[:3]} {cod[3:]}", 59))

    def test_secreto_generado_y_uri(self):
        s = totp.generar_secreto()
        self.assertEqual(len(s), 32)
        self.assertNotEqual(s, totp.generar_secreto())
        self.assertEqual(len(totp.codigo_actual(s, 0)), 6)
        uri = totp.uri_aprovisionamiento(s, "ana@ejemplo.com")
        self.assertTrue(uri.startswith("otpauth://totp/VitaBand%3Aana%40ejemplo.com?"))
        self.assertIn(f"secret={s}", uri)

    def test_secreto_legible_acepta_espacios(self):
        legible = totp.secreto_legible(SECRETO_RFC)
        self.assertEqual(totp.codigo_actual(legible, 59), "287082")


if __name__ == "__main__":
    unittest.main()
