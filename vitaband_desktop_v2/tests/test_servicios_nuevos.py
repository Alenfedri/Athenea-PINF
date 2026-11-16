"""Tests de los servicios de #26: sincronización por archivos, observaciones y consultas."""

import json
import os
import tempfile
import unittest
from datetime import datetime

from domain import ecg_historico as ecg
from services.consultas_historial import ConsultasHistorial
from services.repositorio_historial import RepositorioHistorial
from services.servicio_observaciones import ServicioObservaciones
from services.servicio_sync import ERROR, PENDIENTE, SINCRONIZADO, ServicioSync


def T(dia, h=0, m=0, s=0):
    return int(datetime(2026, 11, dia, h, m, s).timestamp())


def dt(ts):
    return datetime.fromtimestamp(ts)


AHORA = T(15, 12)
EMAIL = "ana@correo.com"


def paquete(usuario=EMAIL, **cambios):
    base = {
        "version": 1, "usuario": usuario,
        "actividades": [{"uid": "a1", "inicio": T(10, 9), "fin": T(10, 10), "tipo": "carrera"}],
        "mediciones": [
            {"uid": "m1", "ts": T(10, 8), "bpm": 62, "rpm": 14, "temp": 36.4, "actividad": 0},
            {"uid": "m2", "ts": T(10, 9, 5), "bpm": 140, "etiqueta": "ACTIVIDAD", "actividad_uid": "a1"},
        ],
        "ecg": [{"ts_inicio": T(10, 9), "minimos": [1000, 1010], "maximos": [2000, 2100]}],
    }
    base.update(cambios)
    return base


class BaseServicios(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.carpeta = os.path.join(self.dir.name, "intercambio")
        os.mkdir(self.carpeta)
        self.repo = RepositorioHistorial(os.path.join(self.dir.name, "t.db"), 1)

    def tearDown(self):
        self.repo.cerrar()
        self.dir.cleanup()

    def escribir(self, nombre, contenido):
        ruta = os.path.join(self.carpeta, nombre)
        modo, datos = ("wb", contenido) if isinstance(contenido, bytes) else ("w", json.dumps(contenido))
        with open(ruta, modo) as f:
            f.write(datos)
        return ruta


class TestServicioSync(BaseServicios):
    def setUp(self):
        super().setUp()
        self.sync = ServicioSync(self.repo, self.carpeta, "  ANA@correo.com ", reloj=lambda: AHORA)

    def test_carpeta_inexistente(self):
        s = ServicioSync(self.repo, os.path.join(self.dir.name, "nada"), EMAIL)
        self.assertFalse(s.estado().carpeta_disponible)
        self.assertFalse(s.sincronizar().carpeta_disponible)

    def test_carpeta_vacia(self):
        e = self.sync.estado()
        self.assertTrue(e.carpeta_disponible)
        self.assertEqual((e.pendientes, e.sincronizados, e.errores, e.ultima_sync_ts), (0, 0, 0, None))
        r = self.sync.sincronizar()
        self.assertEqual((r.importados, r.rechazados, r.sin_cambios), (0, 0, 0))

    def test_pendiente_luego_sincronizado(self):
        self.escribir("a.json", paquete())
        self.assertEqual([(a.nombre, a.estado) for a in self.sync.estado().archivos], [("a.json", PENDIENTE)])
        r = self.sync.sincronizar()
        self.assertEqual((r.importados, r.mediciones_nuevas, r.actividades_nuevas, r.segundos_ecg_nuevos), (1, 2, 1, 2))
        self.assertTrue(r.hubo_datos_nuevos)
        e = self.sync.estado()
        self.assertEqual((e.pendientes, e.sincronizados, e.errores, e.ultima_sync_ts), (0, 1, 0, AHORA))
        self.assertEqual(e.archivos[0].estado, SINCRONIZADO)
        self.assertEqual(self.repo.contar_mediciones(), 2)

    def test_segunda_sincronizacion_no_duplica(self):
        self.escribir("a.json", paquete())
        self.sync.sincronizar()
        r = self.sync.sincronizar()
        self.assertEqual((r.importados, r.sin_cambios, r.mediciones_nuevas), (0, 1, 0))
        self.assertFalse(r.hubo_datos_nuevos)
        self.assertEqual(self.repo.contar_mediciones(), 2)

    def test_mismo_contenido_con_otro_nombre_no_se_reimporta(self):
        self.escribir("a.json", paquete())
        self.sync.sincronizar()
        self.escribir("copia_de_a.json", paquete())
        r = self.sync.sincronizar()
        self.assertEqual((r.importados, r.sin_cambios), (0, 2))
        self.assertEqual(self.repo.contar_mediciones(), 2)

    def test_paquete_distinto_con_uids_repetidos_no_duplica(self):
        self.escribir("a.json", paquete())
        self.sync.sincronizar()
        nuevo = paquete(mediciones=[
            {"uid": "m1", "ts": T(10, 8), "bpm": 62},
            {"uid": "m3", "ts": T(10, 8, 30), "bpm": 64}], actividades=[], ecg=[])
        self.escribir("b.json", nuevo)
        r = self.sync.sincronizar()
        self.assertEqual((r.importados, r.mediciones_nuevas, r.mediciones_duplicadas), (1, 1, 1))
        self.assertEqual(self.repo.contar_mediciones(), 3)

    def test_archivo_invalido_queda_en_error_sin_importar_nada(self):
        malo = paquete(mediciones=[{"uid": "x", "ts": T(10), "bpm": 999}])
        self.escribir("malo.json", malo)
        r = self.sync.sincronizar()
        self.assertEqual((r.importados, r.rechazados), (0, 1))
        self.assertIn("malo.json", r.errores[0])
        self.assertEqual(self.repo.contar_mediciones(), 0)
        self.assertEqual(self.repo.actividades_rango(0, T(30)), [])
        a = self.sync.estado().archivos[0]
        self.assertEqual(a.estado, ERROR)
        self.assertIn("bpm", a.detalle)

    def test_corregir_el_archivo_lo_importa(self):
        self.escribir("x.json", paquete(mediciones=[{"uid": "x", "ts": T(10), "bpm": 999}]))
        self.sync.sincronizar()
        self.escribir("x.json", paquete())              # mismo nombre, contenido corregido
        os.utime(os.path.join(self.carpeta, "x.json"), (AHORA + 5, AHORA + 5))
        r = self.sync.sincronizar()
        self.assertEqual((r.importados, r.rechazados), (1, 0))
        self.assertEqual(self.sync.estado().errores, 0)

    def test_basura_y_vacio_son_errores(self):
        self.escribir("basura.json", b"esto no es json")
        self.escribir("vacio.json", b"")
        e = self.sync.estado()
        self.assertEqual((e.pendientes, e.errores), (2, 0))      # aún sin intentar
        r = self.sync.sincronizar()
        self.assertEqual((r.importados, r.rechazados), (0, 2))
        self.assertEqual(self.sync.estado().errores, 2)

    def test_error_se_reintenta_en_cada_sincronizacion(self):
        self.escribir("x.json", b"basura")
        self.assertEqual(self.sync.sincronizar().rechazados, 1)
        self.assertEqual(self.sync.sincronizar().rechazados, 1)   # sigue contando, no se pierde

    def test_dependencia_entre_archivos_se_resuelve_en_una_pasada(self):
        solo_med = paquete(actividades=[], ecg=[], mediciones=[
            {"uid": "m9", "ts": T(10, 9, 30), "bpm": 150, "etiqueta": "ACTIVIDAD", "actividad_uid": "a1"}])
        self.escribir("a_primero.json", solo_med)           # depende de la actividad del siguiente
        self.escribir("b_segundo.json", paquete())
        r = self.sync.sincronizar()
        self.assertEqual((r.importados, r.rechazados), (2, 0))
        a = self.repo.actividades_rango(0, T(30))[0]
        self.assertEqual(len(self.repo.mediciones_de_actividad(a.id)), 2)

    def test_ignora_paquetes_de_otro_usuario_y_archivos_no_json(self):
        self.escribir("ajeno.json", paquete(usuario="otro@correo.com"))
        self.escribir("notas.txt", b"hola")
        os.mkdir(os.path.join(self.carpeta, "subcarpeta.json"))
        self.assertEqual(self.sync.estado().archivos, ())
        r = self.sync.sincronizar()
        self.assertEqual((r.importados, r.rechazados, r.sin_cambios), (0, 0, 0))
        self.assertEqual(self.repo.contar_mediciones(), 0)

    def test_mayusculas_en_correo_y_extension(self):
        self.escribir("A.JSON", paquete(usuario="ANA@Correo.COM"))
        self.assertEqual(self.sync.sincronizar().importados, 1)

    def test_dos_usuarios_comparten_carpeta(self):
        otro = RepositorioHistorial(os.path.join(self.dir.name, "t.db"), 2)
        try:
            sync_b = ServicioSync(otro, self.carpeta, "otro@correo.com", reloj=lambda: AHORA)
            self.escribir("ana.json", paquete())
            self.escribir("otro.json", paquete(usuario="otro@correo.com"))
            self.sync.sincronizar()
            sync_b.sincronizar()
            self.assertEqual(self.repo.contar_mediciones(), 2)
            self.assertEqual(otro.contar_mediciones(), 2)
            self.assertEqual(self.sync.estado().sincronizados, 1)
            self.assertEqual(sync_b.estado().sincronizados, 1)
        finally:
            otro.cerrar()


class TestServicioObservaciones(BaseServicios):
    def setUp(self):
        super().setUp()
        self.servicio = ServicioObservaciones(self.repo, intervalo_registro_s=300, reloj=lambda: AHORA)

    def cargar_dia(self, dia, bpm, n=8):
        for i in range(n):
            self.repo.guardar_medicion(bpm, dt(T(dia, 8, i * 5)), rpm=14, temp_c=36.5,
                                       nivel_actividad=0, uid=f"d{dia}-{i}")

    def test_sin_datos_no_hace_nada(self):
        self.assertEqual(self.servicio.actualizar_todo().total, 0)

    def test_genera_diarias_y_no_reescribe_si_no_cambia(self):
        self.cargar_dia(13, 60)
        self.cargar_dia(14, 66)
        r = self.servicio.actualizar_todo()
        self.assertEqual((r.diarias, r.actividades), (2, 0))
        self.assertEqual(self.servicio.actualizar_todo().total, 0)
        obs = self.repo.observaciones_rango(T(13), T(15), "DIARIA")
        self.assertEqual([o.clave for o in obs], ["2026-11-14", "2026-11-13"])
        self.assertIn("+6,0 BPM", obs[0].texto)                    # evolución respecto al día anterior
        self.assertIn("no constituye un diagnóstico", obs[0].texto)

    def test_nuevos_datos_actualizan_la_observacion(self):
        self.cargar_dia(14, 60)
        self.servicio.actualizar_todo()
        self.cargar_dia(14, 130, n=0)
        for i in range(8, 16):
            self.repo.guardar_medicion(120, dt(T(14, 9, (i - 8) * 5)), nivel_actividad=0, uid=f"n{i}")
        self.assertEqual(self.servicio.actualizar_todo().diarias, 1)

    def test_solo_cuenta_el_historial_periodico(self):
        a = self.repo.guardar_actividad("a", T(14, 9), T(14, 10))
        for i in range(8):
            self.repo.guardar_medicion(150, dt(T(14, 9, i)), etiqueta="ACTIVIDAD", actividad_id=a, uid=f"x{i}")
        self.assertEqual(self.servicio.actualizar_todo().diarias, 0)

    def test_observacion_de_actividad_con_referencia_de_reposo(self):
        self.cargar_dia(13, 60)
        a = self.repo.guardar_actividad("a", T(14, 9), T(14, 9, 30), "carrera")
        for i in range(0, 30, 5):
            self.repo.guardar_medicion(110, dt(T(14, 9, i)), etiqueta="ACTIVIDAD", actividad_id=a,
                                       nivel_actividad=1, uid=f"x{i}")
        r = self.servicio.actualizar_todo()
        self.assertEqual(r.actividades, 1)
        texto = self.repo.observacion_actividad(a).texto
        self.assertIn("carrera", texto)
        self.assertIn("Esfuerzo estimado: alto", texto)           # 110 vs 60 en reposo
        self.assertEqual(self.servicio.actualizar_todo().actividades, 0)

    def test_actividad_se_actualiza_si_llegan_mediciones_despues(self):
        a = self.repo.guardar_actividad("a", T(14, 9), T(14, 9, 30))
        self.servicio.actualizar_todo()
        self.assertIn("No hay mediciones", self.repo.observacion_actividad(a).texto)
        self.repo.guardar_medicion(120, dt(T(14, 9, 5)), etiqueta="ACTIVIDAD", actividad_id=a, uid="x")
        self.assertEqual(self.servicio.actualizar_todo().actividades, 1)
        self.assertNotIn("No hay mediciones", self.repo.observacion_actividad(a).texto)

    def test_actividad_en_curso_se_deja_para_despues(self):
        self.repo.guardar_actividad("a", AHORA - 60, AHORA + 3600)
        self.assertEqual(self.servicio.actualizar_todo().actividades, 0)


class TestConsultasHistorial(BaseServicios):
    def setUp(self):
        super().setUp()
        self.c = ConsultasHistorial(self.repo, intervalo_registro_s=10, reloj=lambda: AHORA)

    def sembrar(self):
        # 3 h de datos cada 10 min con un corte de 2 h en medio
        for h, m in [(8, 0), (8, 10), (8, 20), (8, 30), (10, 30), (10, 40), (10, 50), (11, 0)]:
            self.repo.guardar_medicion(60 + m, dt(T(10, h, m)), rpm=14, temp_c=36.5, nivel_actividad=0,
                                       uid=f"s{h}{m}")

    def test_serie_basica_y_estadisticas(self):
        self.sembrar()
        s = self.c.serie("bpm", T(10, 8), T(10, 12))
        self.assertEqual(len(s.pares), 8)
        self.assertEqual(s.resolucion, "sin_agrupar")
        self.assertFalse(s.agrupada)
        self.assertEqual((s.estadisticas.cantidad, s.estadisticas.minimo, s.estadisticas.maximo), (8, 60, 110))

    def test_detecta_interrupcion_entre_registros(self):
        self.sembrar()
        s = self.c.serie("bpm", T(10, 8), T(10, 11, 0, 1))
        self.assertEqual([(i.inicio, i.fin) for i in s.interrupciones], [(T(10, 8, 30), T(10, 10, 30))])
        self.assertEqual(s.tiempo_sin_datos_s, 7200)

    def test_no_marca_interrupcion_antes_del_primer_registro(self):
        self.sembrar()
        s = self.c.serie("bpm", T(1), T(10, 11, 0, 1))        # rango empieza semanas antes de medir
        self.assertEqual(len(s.interrupciones), 1)             # solo el corte real de 2 h

    def test_marca_el_final_si_dejo_de_registrar(self):
        self.sembrar()
        s = self.c.serie("bpm", T(10, 8), T(11))
        self.assertEqual(s.interrupciones[-1].inicio, T(10, 11))
        self.assertEqual(s.interrupciones[-1].fin, T(11))

    def test_no_marca_futuro_como_interrupcion(self):
        self.sembrar()
        s = self.c.serie("bpm", T(10, 8), T(30))
        self.assertEqual(s.interrupciones[-1].fin, AHORA)

    def test_sin_datos_no_hay_interrupciones_ni_estadisticas(self):
        s = self.c.serie("bpm", T(10), T(11))
        self.assertEqual((s.pares, s.interrupciones), ((), ()))
        self.assertIsNone(s.estadisticas)

    def test_agrupacion_automatica_y_explicita(self):
        self.sembrar()
        s = self.c.serie("bpm", T(10), T(10) + 10 * 86400)
        self.assertEqual(s.resolucion, "hora")
        self.assertTrue(s.agrupada)
        con_datos = [x for x in s.cubos if not x.vacio]
        self.assertEqual([x.cantidad for x in con_datos], [4, 3, 1])   # horas 8, 10, 11
        self.assertEqual(self.c.serie("bpm", T(10), T(11), "dia").resolucion, "dia")
        self.assertEqual(self.c.serie("bpm", T(10), T(11), "sin_agrupar").cubos, ())

    def test_variables_y_validaciones(self):
        self.sembrar()
        self.assertEqual(len(self.c.serie("rpm", T(10), T(11)).pares), 8)
        self.assertEqual(self.c.serie("temp", T(10), T(11)).estadisticas.media, 36.5)
        for args in (("xyz", T(10), T(11)), ("bpm", T(11), T(10)), ("bpm", T(10), T(11), "semana")):
            with self.assertRaises(ValueError):
                self.c.serie(*args)

    def test_ambito_periodico_excluye_actividad(self):
        a = self.repo.guardar_actividad("a", T(10, 9), T(10, 10))
        self.repo.guardar_medicion(70, dt(T(10, 8)), uid="p")
        self.repo.guardar_medicion(150, dt(T(10, 9)), uid="a", etiqueta="ACTIVIDAD", actividad_id=a)
        self.assertEqual(len(self.c.serie("bpm", T(10), T(11)).pares), 1)
        self.assertEqual(self.c.rango_disponible(), (T(10, 8), T(10, 8)))
        self.assertEqual(len(self.c.mediciones(T(10), T(11), None)), 2)

    def test_actividades_y_detalle(self):
        a = self.repo.guardar_actividad("a", T(10, 9), T(10, 9, 10), "carrera")
        for i, bpm in enumerate((100, 120, 140)):
            self.repo.guardar_medicion(bpm, dt(T(10, 9, i)), uid=f"x{i}", etiqueta="ACTIVIDAD",
                                       actividad_id=a, rpm=20, nivel_actividad=1)
        self.repo.guardar_ecg_segundos([ecg.SegundoEcg(T(10, 9, 1), 1, 2), ecg.SegundoEcg(T(10, 9, 2), 3, 4)])
        self.repo.guardar_observacion("ACTIVIDAD", str(a), "texto", T(10, 9), T(10, 9, 10), AHORA, actividad_id=a)

        res = self.c.actividades(T(10), T(11))
        self.assertEqual((len(res), res[0].mediciones, res[0].fc.media, res[0].fc.maximo), (1, 3, 120.0, 140.0))
        self.assertEqual(self.c.actividades(T(11), T(12)), [])

        d = self.c.detalle_actividad(a)
        self.assertEqual(d.actividad.tipo, "carrera")
        self.assertEqual(len(d.mediciones), 3)
        self.assertEqual(d.estadisticas["rpm"].media, 20.0)
        self.assertIsNone(d.estadisticas["temp"])
        self.assertEqual(d.observacion.texto, "texto")
        self.assertEqual(len(d.ecg), 2)
        self.assertGreaterEqual(len(d.interrupciones), 1)           # 3 s de datos en 10 s: hay hueco final
        self.assertIsNone(self.c.detalle_actividad(999))

    def test_ecg_reducido_y_limite(self):
        self.repo.guardar_ecg_segundos([ecg.SegundoEcg(T(10, 9) + i, 100 + i, 200 + i) for i in range(30)])
        r = self.c.ecg(T(10, 9), T(10, 9) + 60, 6)
        self.assertEqual((len(r.x), r.segundos_con_dato), (6, 30))
        self.assertTrue(r.tiene_datos)
        self.assertFalse(self.c.ecg(T(12), T(12, 1), 10).tiene_datos)
        with self.assertRaises(ValueError):
            self.c.ecg(T(1), T(1) + 8 * 86400)

    def test_observaciones_passthrough(self):
        self.repo.guardar_observacion("DIARIA", "k", "t", T(10), T(11), AHORA)
        self.assertEqual(len(self.c.observaciones(T(10), T(11))), 1)
        self.assertEqual(self.c.observaciones(T(10), T(11), "ACTIVIDAD"), [])


if __name__ == "__main__":
    unittest.main()
