import unittest
from datetime import date, datetime

from services.repositorio_historial import RepositorioHistorial


class TestRepositorioHistorial(unittest.TestCase):

    def setUp(self):
        self.repo = RepositorioHistorial(":memory:")

    def tearDown(self):
        self.repo.cerrar()

    def test_guardar_y_contar_pendientes(self):
        self.assertEqual(self.repo.contar_pendientes(), 0)
        self.repo.guardar_media_bpm(70.0)
        self.repo.guardar_media_bpm(72.5)
        self.assertEqual(self.repo.contar_pendientes(), 2)

    def test_marcar_sincronizados(self):
        id1 = self.repo.guardar_media_bpm(70.0)
        self.repo.guardar_media_bpm(72.0)
        self.repo.marcar_sincronizados([id1])
        self.assertEqual(self.repo.contar_pendientes(), 1)
        self.assertNotIn(id1, [r.id for r in self.repo.obtener_pendientes()])
        self.repo.marcar_sincronizados([])  # no falla

    def test_historial_y_media_por_fecha(self):
        self.repo.guardar_media_bpm(60.0, datetime(2026, 11, 13, 9, 0, 0))
        self.repo.guardar_media_bpm(80.0, datetime(2026, 11, 13, 9, 0, 10))
        self.repo.guardar_media_bpm(100.0, datetime(2026, 11, 14, 8, 0, 0))

        dia = date(2026, 11, 13)
        registros = self.repo.historial_por_fecha(dia)
        self.assertEqual([r.media_bpm for r in registros], [60.0, 80.0])
        self.assertEqual(registros[0].instante, datetime(2026, 11, 13, 9, 0, 0))
        self.assertEqual(self.repo.media_diaria(dia), 70.0)
        self.assertIsNone(self.repo.media_diaria(date(2020, 1, 1)))


if __name__ == "__main__":
    unittest.main()
