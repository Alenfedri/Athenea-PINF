import os
import sqlite3
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

    def test_guardar_y_contar(self):
        self.assertEqual(self.repo.contar_mediciones(), 0)
        self.repo.guardar_media_bpm(70.0)
        self.repo.guardar_media_bpm(72.5)
        self.assertEqual(self.repo.contar_mediciones(), 2)

    def test_uid_repetido_no_duplica(self):
        ts = datetime(2026, 11, 13, 9, 0, 0)
        self.assertIsNotNone(self.repo.guardar_medicion(70.0, ts, uid="a-1"))
        self.assertIsNone(self.repo.guardar_medicion(70.0, ts, uid="a-1"))
        self.assertEqual(self.repo.contar_mediciones(), 1)

    def test_etiqueta_valida(self):
        self.repo.guardar_medicion(70.0, etiqueta="AMBOS")
        with self.assertRaises(ValueError):
            self.repo.guardar_medicion(70.0, etiqueta="OTRA")

    def test_todas_las_mediciones_en_orden(self):
        self.repo.guardar_media_bpm(80.0, datetime(2026, 11, 14, 8, 0, 0))
        self.repo.guardar_media_bpm(60.0, datetime(2026, 11, 13, 9, 0, 0))
        self.assertEqual([r.media_bpm for r in self.repo.todas_las_mediciones()], [60.0, 80.0])


class TestAislamientoYPersistencia(unittest.TestCase):

    def test_un_usuario_no_ve_ni_exporta_los_datos_de_otro(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "t.db")
            a = RepositorioHistorial(ruta, usuario_id=1)
            b = RepositorioHistorial(ruta, usuario_id=2)
            try:
                dia = datetime(2026, 11, 13, 9, 0, 0)
                a.guardar_medicion(60.0, dia, uid="x")
                b.guardar_medicion(99.0, dia, uid="x")   # mismo uid, otro usuario: válido

                desde, hasta = int(dia.timestamp()) - 1, int(dia.timestamp()) + 1
                self.assertEqual([r.bpm for r in a.mediciones_rango(desde, hasta)], [60.0])
                self.assertEqual([r.bpm for r in b.mediciones_rango(desde, hasta)], [99.0])
                self.assertEqual([r.media_bpm for r in a.todas_las_mediciones()], [60.0])
                self.assertEqual(b.contar_mediciones(), 1)
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
                self.assertEqual(r2.contar_mediciones(), 1)
            finally:
                r2.cerrar()

    def test_base_de_datos_de_la_version_anterior_sigue_funcionando(self):
        """Una BD creada con la columna estado_sync (NOT NULL con DEFAULT) debe seguir sirviendo."""
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "vieja.db")
            con = sqlite3.connect(ruta)
            con.executescript("""
                CREATE TABLE mediciones (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario_id INTEGER NOT NULL, uid TEXT NOT NULL, ts INTEGER NOT NULL,
                    bpm REAL NOT NULL, rpm REAL, temp_c REAL,
                    etiqueta TEXT NOT NULL DEFAULT 'PERIODICO'
                        CHECK (etiqueta IN ('PERIODICO','ACTIVIDAD','AMBOS')),
                    actividad_id INTEGER,
                    estado_sync TEXT NOT NULL DEFAULT 'PENDIENTE'
                        CHECK (estado_sync IN ('PENDIENTE','SINCRONIZADO','ERROR')),
                    UNIQUE (usuario_id, uid)
                );
                INSERT INTO mediciones (usuario_id, uid, ts, bpm, estado_sync)
                VALUES (1, 'viejo', 1763000000, 65.0, 'SINCRONIZADO');
            """)
            con.commit()
            con.close()

            repo = RepositorioHistorial(ruta, usuario_id=1)
            try:
                self.assertEqual(repo.contar_mediciones(), 1)
                self.assertIsNotNone(repo.guardar_media_bpm(70.0))
                self.assertEqual(len(repo.todas_las_mediciones()), 2)
            finally:
                repo.cerrar()


if __name__ == "__main__":
    unittest.main()
