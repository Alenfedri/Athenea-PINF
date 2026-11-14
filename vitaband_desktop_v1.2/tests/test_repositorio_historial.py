import os
import tempfile
import unittest
from datetime import date, datetime

from services.repositorio_historial import RepositorioHistorial


class TestRepositorioHistorial(unittest.TestCase):

    def setUp(self):
        self.repo = RepositorioHistorial(":memory:", usuario_id=1)

    def tearDown(self):
        self.repo.cerrar()

    def test_usuario_obligatorio(self):
        with self.assertRaises(ValueError):
            RepositorioHistorial(":memory:", usuario_id=None)

    def test_guardar_y_contar_pendientes(self):
        self.assertEqual(self.repo.contar_pendientes(), 0)
        self.repo.guardar_media_bpm(70.0)
        self.repo.guardar_media_bpm(72.5)
        self.assertEqual(self.repo.contar_pendientes(), 2)

    def test_estados_de_sincronizacion(self):
        id1 = self.repo.guardar_media_bpm(70.0)
        id2 = self.repo.guardar_media_bpm(72.0)
        id3 = self.repo.guardar_media_bpm(74.0)
        self.repo.marcar_sincronizados([id1])
        self.repo.marcar_error([id2])
        self.assertEqual(
            self.repo.contar_por_estado(),
            {"PENDIENTE": 1, "SINCRONIZADO": 1, "ERROR": 1},
        )
        self.assertEqual([r.id for r in self.repo.obtener_pendientes()], [id3])
        self.repo.marcar_sincronizados([])  # no falla

    def test_uid_repetido_no_duplica(self):
        ts = datetime(2026, 11, 13, 9, 0, 0)
        self.assertIsNotNone(self.repo.guardar_medicion(70.0, ts, uid="movil-1"))
        self.assertIsNone(self.repo.guardar_medicion(70.0, ts, uid="movil-1"))
        self.assertEqual(self.repo.contar_pendientes(), 1)

    def test_etiquetas_y_estado_validos(self):
        self.repo.guardar_medicion(70.0, etiqueta="AMBOS", estado_sync="SINCRONIZADO")
        with self.assertRaises(ValueError):
            self.repo.guardar_medicion(70.0, etiqueta="OTRA")
        with self.assertRaises(ValueError):
            self.repo.guardar_medicion(70.0, estado_sync="RARO")

    def test_historial_y_media_por_fecha(self):
        self.repo.guardar_media_bpm(60.0, datetime(2026, 11, 13, 9, 0, 0))
        self.repo.guardar_media_bpm(80.0, datetime(2026, 11, 13, 9, 0, 10))
        self.repo.guardar_media_bpm(100.0, datetime(2026, 11, 14, 8, 0, 0))

        dia = date(2026, 11, 13)
        registros = self.repo.historial_por_fecha(dia)
        self.assertEqual([r.media_bpm for r in registros], [60.0, 80.0])
        self.assertEqual(registros[0].instante, datetime(2026, 11, 13, 9, 0, 0))
        self.assertEqual(registros[0].etiqueta, "PERIODICO")
        self.assertEqual(self.repo.media_diaria(dia), 70.0)
        self.assertIsNone(self.repo.media_diaria(date(2020, 1, 1)))


class TestAislamientoPorUsuario(unittest.TestCase):

    def test_un_usuario_no_ve_ni_toca_los_datos_de_otro(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "t.db")
            a = RepositorioHistorial(ruta, usuario_id=1)
            b = RepositorioHistorial(ruta, usuario_id=2)
            try:
                dia = datetime(2026, 11, 13, 9, 0, 0)
                id_a = a.guardar_medicion(60.0, dia, uid="x")
                # mismo uid en otro usuario: NO es duplicado
                id_b = b.guardar_medicion(99.0, dia, uid="x")
                self.assertIsNotNone(id_a)
                self.assertIsNotNone(id_b)

                self.assertEqual([r.media_bpm for r in a.historial_por_fecha(dia.date())], [60.0])
                self.assertEqual([r.media_bpm for r in b.historial_por_fecha(dia.date())], [99.0])
                self.assertEqual(a.contar_pendientes(), 1)

                b.marcar_sincronizados([id_a])   # id ajeno: no debe afectar a A
                self.assertEqual(a.contar_pendientes(), 1)
            finally:
                a.cerrar()
                b.cerrar()

    def test_persisten_al_cerrar_y_reabrir(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "t.db")
            r1 = RepositorioHistorial(ruta, usuario_id=7)
            r1.guardar_media_bpm(71.0)
            r1.cerrar()
            r2 = RepositorioHistorial(ruta, usuario_id=7)
            try:
                self.assertEqual(r2.contar_pendientes(), 1)
            finally:
                r2.cerrar()


if __name__ == "__main__":
    unittest.main()
