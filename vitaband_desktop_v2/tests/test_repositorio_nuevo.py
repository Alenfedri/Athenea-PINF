"""Tests del repositorio de historial reescrito (SQLite): consultas, importación, migración, purga, borrado."""

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime

from domain import ecg_historico as ecg
from domain.paquete_sync import PaqueteInvalido, parsear_paquete
from services.repositorio_historial import RepositorioHistorial

DIA = 86400


def T(dia, h=0, m=0, s=0):
    return int(datetime(2026, 11, dia, h, m, s).timestamp())


def dt(ts):
    return datetime.fromtimestamp(ts)


AHORA = T(15, 12)


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.ruta = os.path.join(self.dir.name, "t.db")
        self.repo = RepositorioHistorial(self.ruta, 1)
        self.abiertos = [self.repo]

    def tearDown(self):
        for r in self.abiertos:
            r.cerrar()
        self.dir.cleanup()

    def otro(self, usuario_id):
        r = RepositorioHistorial(self.ruta, usuario_id)
        self.abiertos.append(r)
        return r


class TestMedicionesYConsultas(Base):
    def test_guardar_y_leer_con_todos_los_campos(self):
        i = self.repo.guardar_medicion(72.5, dt(T(10, 9)), uid="x", rpm=15, temp_c=36.6, nivel_actividad=0)
        m = self.repo.mediciones_rango(T(10), T(11))[0]
        self.assertEqual((m.id, m.uid, m.ts, m.bpm, m.rpm, m.temp_c, m.nivel_actividad, m.etiqueta),
                         (i, "x", T(10, 9), 72.5, 15.0, 36.6, 0, "PERIODICO"))
        self.assertIsNone(m.actividad_id)

    def test_uid_repetido_no_duplica(self):
        self.assertIsNotNone(self.repo.guardar_medicion(70, dt(T(10)), uid="x"))
        self.assertIsNone(self.repo.guardar_medicion(99, dt(T(10)), uid="x"))
        self.assertEqual(self.repo.contar_mediciones(), 1)
        self.assertEqual(self.repo.todas_las_mediciones()[0].bpm, 70.0)

    def test_etiqueta_invalida(self):
        with self.assertRaises(ValueError):
            self.repo.guardar_medicion(70, etiqueta="OTRA")

    def test_usuario_obligatorio(self):
        with self.assertRaises(ValueError):
            RepositorioHistorial(self.ruta, None)

    def test_rango_semiabierto_y_orden(self):
        for h in (12, 9, 10):
            self.repo.guardar_medicion(60 + h, dt(T(10, h)))
        self.assertEqual([m.ts for m in self.repo.mediciones_rango(T(10, 9), T(10, 12))], [T(10, 9), T(10, 10)])
        self.assertEqual(self.repo.mediciones_rango(T(11), T(10)), [])

    def test_ambitos(self):
        aid = self.repo.guardar_actividad("a", T(10, 9), T(10, 10))
        self.repo.guardar_medicion(1 + 60, dt(T(10, 8)), etiqueta="PERIODICO")
        self.repo.guardar_medicion(2 + 60, dt(T(10, 9)), etiqueta="ACTIVIDAD", actividad_id=aid)
        self.repo.guardar_medicion(3 + 60, dt(T(10, 9, 1)), etiqueta="AMBOS", actividad_id=aid)
        r = lambda amb: sorted(m.bpm for m in self.repo.mediciones_rango(T(10), T(11), amb))
        self.assertEqual(r("periodico"), [61, 63])
        self.assertEqual(r("actividad"), [62, 63])
        self.assertEqual(r(None), [61, 62, 63])
        with self.assertRaises(ValueError):
            r("otro")

    def test_rango_periodico(self):
        self.assertIsNone(self.repo.rango_periodico())
        self.repo.guardar_medicion(70, dt(T(10, 8)))
        self.repo.guardar_medicion(70, dt(T(12, 8)))
        self.assertEqual(self.repo.rango_periodico(), (T(10, 8), T(12, 8)))

    def test_aislamiento_entre_usuarios(self):
        b = self.otro(2)
        self.repo.guardar_medicion(60, dt(T(10)), uid="mismo")
        b.guardar_medicion(99, dt(T(10)), uid="mismo")       # mismo uid, otro usuario: permitido
        self.repo.guardar_actividad("a", T(10), T(10, 1))
        self.assertEqual([m.bpm for m in self.repo.todas_las_mediciones()], [60.0])
        self.assertEqual([m.bpm for m in b.todas_las_mediciones()], [99.0])
        self.assertEqual(b.actividades_rango(0, T(30)), [])

    def test_persistencia_al_reabrir(self):
        self.repo.guardar_medicion(70, dt(T(10)))
        self.repo.cerrar()
        r2 = RepositorioHistorial(self.ruta, 1)
        self.abiertos.append(r2)
        self.assertEqual(r2.contar_mediciones(), 1)


class TestActividadesEcgObservaciones(Base):
    def test_actividades(self):
        a = self.repo.guardar_actividad("a", T(10, 9), T(10, 10), "carrera")
        self.assertIsNone(self.repo.guardar_actividad("a", T(10, 9), T(10, 10)))
        self.repo.guardar_actividad("b", T(12, 9), T(12, 10))
        self.assertEqual(self.repo.obtener_actividad(a).tipo, "carrera")
        self.assertIsNone(self.repo.obtener_actividad(999))
        self.assertEqual([x.uid for x in self.repo.actividades_rango(0, T(30))], ["b", "a"])  # recientes primero
        self.assertEqual([x.uid for x in self.repo.actividades_rango(T(10), T(11))], ["a"])
        with self.assertRaises(ValueError):
            self.repo.guardar_actividad("c", 100, 50)

    def test_mediciones_de_actividad(self):
        a = self.repo.guardar_actividad("a", T(10, 9), T(10, 10))
        self.repo.guardar_medicion(130, dt(T(10, 9)), etiqueta="ACTIVIDAD", actividad_id=a)
        self.repo.guardar_medicion(70, dt(T(10, 8)))
        self.assertEqual([m.bpm for m in self.repo.mediciones_de_actividad(a)], [130.0])

    def test_ecg_guardar_leer_y_no_sobrescribir(self):
        base = T(10, 9)
        self.assertEqual(self.repo.guardar_ecg_segundos([ecg.SegundoEcg(base + i, 1000 + i, 2000 + i) for i in range(5)]), 5)
        self.assertEqual(self.repo.guardar_ecg_segundos([ecg.SegundoEcg(base, 5, 6), ecg.SegundoEcg(base + 5, 7, 8)]), 1)
        segs = self.repo.ecg_rango(base, base + 10)
        self.assertEqual(len(segs), 6)
        self.assertEqual((segs[0].minimo, segs[0].maximo), (1000, 2000))     # no se sobrescribió
        self.assertEqual(self.repo.contar_segundos_ecg(), 6)
        self.assertEqual(self.repo.ecg_rango(base + 1, base + 3)[0].ts, base + 1)
        self.assertEqual(self.repo.ecg_rango(base, base), [])

    def test_ecg_cruza_minutos(self):
        t0 = (T(10, 9) // 60) * 60 + 58
        self.repo.guardar_ecg_segundos([ecg.SegundoEcg(t0 + i, i, i + 1) for i in range(4)])
        self.assertEqual([s.ts for s in self.repo.ecg_rango(t0, t0 + 10)], [t0, t0 + 1, t0 + 2, t0 + 3])

    def test_observaciones_upsert(self):
        g = lambda txt: self.repo.guardar_observacion("DIARIA", "2026-11-10", txt, T(10), T(11), AHORA)
        self.assertTrue(g("uno"))
        self.assertFalse(g("uno"))           # sin cambios: no se reescribe
        self.assertTrue(g("dos"))
        o = self.repo.observaciones_rango(T(10), T(11))
        self.assertEqual([x.texto for x in o], ["dos"])
        self.assertEqual(o[0].lineas, ["dos"])

    def test_observaciones_rango_y_tipo(self):
        a = self.repo.guardar_actividad("a", T(10, 9), T(10, 10))
        self.repo.guardar_observacion("DIARIA", "d", "dia", T(10), T(11), AHORA)
        self.repo.guardar_observacion("ACTIVIDAD", str(a), "act", T(10, 9), T(10, 10), AHORA, actividad_id=a)
        self.assertEqual(len(self.repo.observaciones_rango(T(10), T(11))), 2)
        self.assertEqual([o.texto for o in self.repo.observaciones_rango(T(10), T(11), "ACTIVIDAD")], ["act"])
        self.assertEqual(self.repo.observaciones_rango(T(12), T(13)), [])
        self.assertEqual(self.repo.observacion_actividad(a).texto, "act")
        self.assertIsNone(self.repo.observacion_actividad(999))


def _json(**cambios):
    base = {
        "version": 1, "usuario": "a@b.com",
        "actividades": [{"uid": "a1", "inicio": T(10, 9), "fin": T(10, 10), "tipo": "carrera"}],
        "mediciones": [
            {"uid": "m1", "ts": T(10, 8), "bpm": 62, "rpm": 14, "temp": 36.4, "actividad": 0},
            {"uid": "m2", "ts": T(10, 9, 5), "bpm": 140, "etiqueta": "ACTIVIDAD", "actividad_uid": "a1"},
            {"uid": "m3", "ts": T(10, 9, 6), "bpm": 141, "etiqueta": "AMBOS", "actividad_uid": "a1"},
        ],
        "ecg": [{"ts_inicio": T(10, 9), "minimos": [1000, 1010], "maximos": [2000, 2100]}],
    }
    base.update(cambios)
    return parsear_paquete(json.dumps(base).encode(), AHORA)


class TestImportacion(Base):
    def test_importa_y_enlaza_actividad(self):
        r = self.repo.importar_paquete(_json())
        self.assertEqual((r.mediciones_nuevas, r.actividades_nuevas, r.segundos_ecg_nuevos), (3, 1, 2))
        a = self.repo.actividades_rango(0, T(30))[0]
        self.assertEqual(sorted(m.uid for m in self.repo.mediciones_de_actividad(a.id)), ["m2", "m3"])
        self.assertEqual(self.repo.mediciones_rango(T(10), T(11), "periodico")[0].nivel_actividad, 0)
        self.assertEqual(len(self.repo.ecg_rango(T(10, 9), T(10, 10))), 2)

    def test_reimportar_no_duplica(self):
        self.repo.importar_paquete(_json())
        r = self.repo.importar_paquete(_json())
        self.assertEqual((r.mediciones_nuevas, r.mediciones_duplicadas, r.actividades_nuevas,
                          r.actividades_duplicadas, r.segundos_ecg_nuevos), (0, 3, 0, 1, 0))
        self.assertEqual(self.repo.contar_mediciones(), 3)
        self.assertEqual(self.repo.contar_segundos_ecg(), 2)

    def test_paquete_parcialmente_nuevo(self):
        self.repo.importar_paquete(_json())
        extra = _json(mediciones=[{"uid": "m1", "ts": T(10, 8), "bpm": 62},
                                  {"uid": "m9", "ts": T(10, 8, 30), "bpm": 64}])
        r = self.repo.importar_paquete(extra)
        self.assertEqual((r.mediciones_nuevas, r.mediciones_duplicadas), (1, 1))

    def test_actividad_ya_importada_antes_sirve_a_paquete_posterior(self):
        self.repo.importar_paquete(_json())
        p2 = _json(actividades=[], ecg=[], mediciones=[
            {"uid": "m7", "ts": T(10, 9, 20), "bpm": 150, "etiqueta": "ACTIVIDAD", "actividad_uid": "a1"}])
        self.assertEqual(self.repo.importar_paquete(p2).mediciones_nuevas, 1)
        a = self.repo.actividades_rango(0, T(30))[0]
        self.assertEqual(len(self.repo.mediciones_de_actividad(a.id)), 3)

    def test_todo_o_nada_si_la_actividad_no_existe(self):
        malo = _json(actividades=[{"uid": "nueva", "inicio": T(11, 9), "fin": T(11, 10)}], mediciones=[
            {"uid": "ok", "ts": T(11, 9), "bpm": 70},
            {"uid": "huerfana", "ts": T(11, 9, 5), "bpm": 80, "etiqueta": "ACTIVIDAD", "actividad_uid": "no-existe"}])
        with self.assertRaises(PaqueteInvalido):
            self.repo.importar_paquete(malo)
        self.assertEqual(self.repo.contar_mediciones(), 0)
        self.assertEqual(self.repo.actividades_rango(0, T(30)), [])
        self.assertEqual(self.repo.contar_segundos_ecg(), 0)

    def test_importacion_va_al_usuario_del_repositorio(self):
        b = self.otro(2)
        self.repo.importar_paquete(_json())
        self.assertEqual(b.contar_mediciones(), 0)
        b.importar_paquete(_json())              # mismos uids en otro usuario: se importan
        self.assertEqual(b.contar_mediciones(), 3)


class TestSyncArchivos(Base):
    def test_registro_y_estado(self):
        self.assertIsNone(self.repo.sync_estado("h"))
        self.assertIsNone(self.repo.sync_ultimo())
        self.repo.sync_registrar("a.json", "h", "ERROR", "mal", T(10))
        self.assertEqual(self.repo.sync_estado("h"), "ERROR")
        self.assertEqual(self.repo.sync_contar_importados(), 0)
        self.repo.sync_registrar("a.json", "h", "IMPORTADO", "3 nuevas", T(11))     # reintento correcto
        self.assertEqual(self.repo.sync_estado("h"), "IMPORTADO")
        self.assertEqual(self.repo.sync_ultimo(), (T(11), "3 nuevas"))
        self.assertEqual(self.repo.sync_contar_importados(), 1)

    def test_estado_invalido_y_aislamiento(self):
        with self.assertRaises(ValueError):
            self.repo.sync_registrar("a", "h", "PENDIENTE", "", 1)
        self.repo.sync_registrar("a", "h", "IMPORTADO", "", 1)
        self.assertIsNone(self.otro(2).sync_estado("h"))


class TestMigracion(unittest.TestCase):
    def test_bd_antigua_se_actualiza_y_conserva_datos(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "vieja.db")
            c = sqlite3.connect(ruta)
            c.executescript("""
                CREATE TABLE mediciones (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, usuario_id INTEGER NOT NULL, uid TEXT NOT NULL,
                    ts INTEGER NOT NULL, bpm REAL NOT NULL, rpm REAL, temp_c REAL,
                    etiqueta TEXT NOT NULL DEFAULT 'PERIODICO', actividad_id INTEGER,
                    estado_sync TEXT NOT NULL DEFAULT 'PENDIENTE',
                    UNIQUE (usuario_id, uid));
                INSERT INTO mediciones (usuario_id, uid, ts, bpm) VALUES (1, 'viejo', %d, 66);
            """ % T(10, 8))
            c.commit()
            c.close()

            r = RepositorioHistorial(ruta, 1)
            try:
                m = r.todas_las_mediciones()[0]
                self.assertEqual((m.uid, m.bpm, m.nivel_actividad), ("viejo", 66.0, None))
                self.assertIsNotNone(r.guardar_medicion(70, dt(T(10, 9)), nivel_actividad=1))
                self.assertEqual(r.contar_mediciones(), 2)
                r.guardar_actividad("a", 1, 2)       # tablas nuevas disponibles
            finally:
                r.cerrar()

            r2 = RepositorioHistorial(ruta, 1)       # reabrir no rompe la migración
            self.assertEqual(r2.contar_mediciones(), 2)
            r2.cerrar()


class TestPurga(Base):
    def test_purga_completa(self):
        u = self.repo
        viejo, reciente = AHORA - 40 * DIA, AHORA - 2 * DIA
        # actividad conservada (40 días) y actividad vencida (400 días)
        a_cons = u.guardar_actividad("cons", viejo, viejo + 600)
        a_venc = u.guardar_actividad("venc", AHORA - 400 * DIA, AHORA - 400 * DIA + 600)

        u.guardar_medicion(60, dt(viejo - 5 * DIA), uid="per_vieja")
        u.guardar_medicion(61, dt(reciente), uid="per_reciente")
        u.guardar_medicion(150, dt(viejo + 10), uid="ambos_viejo", etiqueta="AMBOS", actividad_id=a_cons)
        u.guardar_medicion(151, dt(viejo + 20), uid="act_vieja", etiqueta="ACTIVIDAD", actividad_id=a_cons)
        u.guardar_medicion(152, dt(AHORA - 400 * DIA + 10), uid="act_vencida", etiqueta="ACTIVIDAD", actividad_id=a_venc)

        u.guardar_ecg_segundos([ecg.SegundoEcg(viejo - 5 * DIA, 1, 2)])        # ECG vencido, sin actividad
        u.guardar_ecg_segundos([ecg.SegundoEcg(viejo + 30, 3, 4)])             # ECG vencido dentro de actividad conservada
        u.guardar_ecg_segundos([ecg.SegundoEcg(reciente, 5, 6)])               # ECG reciente

        u.guardar_observacion("DIARIA", "viejo", "x", viejo - 5 * DIA, viejo - 5 * DIA + DIA, AHORA)
        u.guardar_observacion("DIARIA", "nuevo", "y", reciente, reciente + DIA, AHORA)
        u.guardar_observacion("ACTIVIDAD", str(a_venc), "z", AHORA - 400 * DIA, AHORA - 400 * DIA + 600, AHORA, actividad_id=a_venc)
        u.guardar_observacion("ACTIVIDAD", str(a_cons), "w", viejo, viejo + 600, AHORA, actividad_id=a_cons)

        res = u.purgar(AHORA, dias_periodico=30, dias_actividades=365)

        quedan = {m.uid: m for m in u.todas_las_mediciones()}
        self.assertEqual(set(quedan), {"per_reciente", "ambos_viejo", "act_vieja"})
        self.assertEqual(quedan["ambos_viejo"].etiqueta, "ACTIVIDAD")          # AMBOS pasa a solo actividad
        self.assertEqual([a.uid for a in u.actividades_rango(0, AHORA + DIA)], ["cons"])
        self.assertEqual(sorted(s.minimo for s in u.ecg_rango(0, AHORA + DIA)), [3, 5])
        self.assertEqual(sorted(o.texto for o in u.observaciones_rango(0, AHORA + DIA)), ["w", "y"])
        self.assertEqual((res.mediciones, res.actividades), (2, 1))
        self.assertEqual(res.bloques_ecg, 1)
        self.assertEqual(res.observaciones, 1)

    def test_purga_es_idempotente_y_no_toca_otro_usuario(self):
        b = self.otro(2)
        self.repo.guardar_medicion(60, dt(AHORA - 100 * DIA))
        b.guardar_medicion(60, dt(AHORA - 100 * DIA))
        self.repo.purgar(AHORA, 30, 365)
        res = self.repo.purgar(AHORA, 30, 365)
        self.assertEqual((res.mediciones, res.actividades, res.bloques_ecg, res.observaciones), (0, 0, 0, 0))
        self.assertEqual(self.repo.contar_mediciones(), 0)
        self.assertEqual(b.contar_mediciones(), 1)

    def test_purga_en_el_limite(self):
        self.repo.guardar_medicion(60, dt(AHORA - 30 * DIA), uid="justo")          # == corte: se conserva
        self.repo.guardar_medicion(60, dt(AHORA - 30 * DIA - 1), uid="pasado")
        self.repo.purgar(AHORA, 30, 365)
        self.assertEqual([m.uid for m in self.repo.todas_las_mediciones()], ["justo"])


class TestBorrado(Base):
    def test_borrar_mediciones(self):
        b = self.otro(2)
        i1 = self.repo.guardar_medicion(60, dt(T(10, 8)))
        i2 = self.repo.guardar_medicion(61, dt(T(10, 9)))
        ib = b.guardar_medicion(99, dt(T(10, 8)))
        self.assertEqual(self.repo.borrar_mediciones([i1, ib]), 1)        # el id ajeno no se borra
        self.assertEqual([m.id for m in self.repo.todas_las_mediciones()], [i2])
        self.assertEqual(b.contar_mediciones(), 1)
        self.assertEqual(self.repo.borrar_mediciones([]), 0)

    def test_borrar_actividad_conserva_lo_periodico(self):
        a = self.repo.guardar_actividad("a", T(10, 9), T(10, 10))
        self.repo.guardar_medicion(130, dt(T(10, 9)), uid="solo", etiqueta="ACTIVIDAD", actividad_id=a)
        self.repo.guardar_medicion(131, dt(T(10, 9, 5)), uid="ambos", etiqueta="AMBOS", actividad_id=a)
        self.repo.guardar_observacion("ACTIVIDAD", str(a), "t", T(10, 9), T(10, 10), AHORA, actividad_id=a)
        self.assertTrue(self.repo.borrar_actividad(a))
        resto = self.repo.todas_las_mediciones()
        self.assertEqual([(m.uid, m.etiqueta, m.actividad_id) for m in resto], [("ambos", "PERIODICO", None)])
        self.assertIsNone(self.repo.obtener_actividad(a))
        self.assertIsNone(self.repo.observacion_actividad(a))
        self.assertFalse(self.repo.borrar_actividad(a))

    def test_borrar_todo_solo_del_usuario(self):
        b = self.otro(2)
        for r in (self.repo, b):
            r.guardar_medicion(60, dt(T(10)))
            r.guardar_actividad("a", 1, 2)
            r.guardar_ecg_segundos([ecg.SegundoEcg(T(10), 1, 2)])
            r.guardar_observacion("DIARIA", "k", "t", 1, 2, AHORA)
            r.sync_registrar("f", "h", "IMPORTADO", "", 1)
        self.repo.borrar_todo()
        self.assertEqual(self.repo.contar_mediciones(), 0)
        self.assertEqual(self.repo.actividades_rango(0, T(30)), [])
        self.assertEqual(self.repo.contar_segundos_ecg(), 0)
        self.assertEqual(self.repo.observaciones_rango(0, T(30)), [])
        self.assertEqual(self.repo.sync_contar_importados(), 0)
        self.assertEqual(b.contar_mediciones(), 1)
        self.assertEqual(len(b.actividades_rango(0, T(30))), 1)
        self.assertEqual(b.contar_segundos_ecg(), 1)


if __name__ == "__main__":
    unittest.main()
