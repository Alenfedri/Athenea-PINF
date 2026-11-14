import unittest

from domain.interprete_biometrico import (
    EstadoPasarela,
    conexion_desde_estado,
    describir_actividad,
    describir_aviso,
    formatear_metrica,
    formatear_temperatura,
    interpretar_estado_pasarela,
    parsear_telemetria,
    validar_media_bpm,
)
from domain.ui_state import ConexionEstado


class TestMapeos(unittest.TestCase):

    def test_actividad_conocida_y_desconocida(self):
        self.assertEqual(describir_actividad(0), "Baja / Reposo")
        self.assertEqual(describir_actividad(2), "Intensa")
        self.assertEqual(describir_actividad(255), "En transición / Sin clasificar")
        self.assertEqual(describir_actividad(77), "En transición / Sin clasificar")

    def test_avisos_conocidos_y_desconocidos(self):
        self.assertEqual(describir_aviso(1), "Aviso experimental: FC elevada en reposo")
        self.assertEqual(describir_aviso(255), "Sin avisos")
        self.assertEqual(describir_aviso(-3), "Sin avisos")


class TestFormateo(unittest.TestCase):

    def test_metrica_valida(self):
        self.assertEqual(formatear_metrica(72.46, "BPM"), "72.5 BPM")

    def test_metrica_invalida(self):
        for valor in (0.0, -1.0, float("nan"), float("inf")):
            self.assertEqual(formatear_metrica(valor, "BPM"), "Calculando...")

    def test_temperatura(self):
        self.assertEqual(formatear_temperatura(36.5), "36.50 °C")
        self.assertEqual(formatear_temperatura(float("nan")), "-- °C")


class TestMediaBpm(unittest.TestCase):

    def test_rango(self):
        self.assertTrue(validar_media_bpm(72.0))
        self.assertFalse(validar_media_bpm(0.0))
        self.assertFalse(validar_media_bpm(300.0))
        self.assertFalse(validar_media_bpm(float("nan")))
        self.assertFalse(validar_media_bpm(None))


class TestTelemetria(unittest.TestCase):

    BASE = {"ecg": 1600, "bpm": 70, "rpm": 14, "temp": 36.4, "activity": 1, "alert": 255}

    def test_sin_media(self):
        p = parsear_telemetria(self.BASE)
        self.assertEqual(p.ecg, 1600.0)
        self.assertEqual(p.cod_actividad, 1)
        self.assertIsNone(p.media_bpm)

    def test_con_media(self):
        p = parsear_telemetria({**self.BASE, "media_bpm": 71.5})
        self.assertEqual(p.media_bpm, 71.5)

    def test_malformada(self):
        with self.assertRaises(KeyError):
            parsear_telemetria({"ecg": 1})
        with self.assertRaises(ValueError):
            parsear_telemetria({**self.BASE, "bpm": "abc"})
        with self.assertRaises(TypeError):
            parsear_telemetria({**self.BASE, "rpm": None})


class TestEstadoPasarela(unittest.TestCase):

    def test_json(self):
        for nombre in ("CALIBRATING", "READY", "OFFLINE"):
            payload = ('{"state": "%s"}' % nombre).encode()
            self.assertEqual(interpretar_estado_pasarela(payload), EstadoPasarela(nombre))

    def test_texto_plano_y_minusculas(self):
        self.assertEqual(interpretar_estado_pasarela(b"OFFLINE"), EstadoPasarela.OFFLINE)
        self.assertEqual(interpretar_estado_pasarela(b' {"state": "ready"} '), EstadoPasarela.READY)
        self.assertEqual(interpretar_estado_pasarela('"READY"'), EstadoPasarela.READY)

    def test_invalidos(self):
        for payload in (b"", b"{}", b'{"state": 3}', b'{"state": "FOO"}', b"\xff\xfe", b"[1]"):
            self.assertIsNone(interpretar_estado_pasarela(payload), payload)

    def test_conversion_a_conexion(self):
        self.assertEqual(conexion_desde_estado(EstadoPasarela.CALIBRATING), ConexionEstado.CALIBRANDO)
        self.assertEqual(conexion_desde_estado(EstadoPasarela.READY), ConexionEstado.CONECTADO)
        self.assertEqual(conexion_desde_estado(EstadoPasarela.OFFLINE), ConexionEstado.ERROR_COMUNICACION)


if __name__ == "__main__":
    unittest.main()
