import unittest

from domain.validacion_cuentas import (
    normalizar_email,
    validar_email,
    validar_nombre,
    validar_password,
    validar_registro,
)


class TestValidacion(unittest.TestCase):

    def test_email(self):
        self.assertEqual(validar_email("ana@ejemplo.com"), [])
        for malo in ("", "   ", "ana", "ana@", "@x.com", "a b@x.com", "ana@x"):
            self.assertTrue(validar_email(malo), malo)

    def test_normalizar_email(self):
        self.assertEqual(normalizar_email("  Ana@Ejemplo.COM "), "ana@ejemplo.com")

    def test_nombre(self):
        self.assertEqual(validar_nombre("Ana"), [])
        self.assertTrue(validar_nombre("A"))
        self.assertTrue(validar_nombre(" " * 5))
        self.assertTrue(validar_nombre("x" * 61))

    def test_password(self):
        self.assertEqual(validar_password("clave12345", "a@b.com"), [])
        self.assertTrue(validar_password("corta1"))
        self.assertTrue(validar_password("sinnumeroslargo"))
        self.assertTrue(validar_password("1234567890123"))
        self.assertTrue(validar_password("ana@ejemplo.com", "ana@ejemplo.com"))

    def test_registro_completo(self):
        self.assertEqual(validar_registro("Ana", "ana@x.com", "clave12345", "clave12345"), [])
        errores = validar_registro("A", "mal", "x", "y")
        self.assertGreaterEqual(len(errores), 4)
        self.assertIn("Las contraseñas no coinciden.", errores)


if __name__ == "__main__":
    unittest.main()
