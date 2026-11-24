"""Tests de los módulos de dominio nuevos: modelos, análisis, ECG histórico, paquete y observaciones."""

import json
import unittest
from datetime import date, datetime, timedelta

from domain import analisis, ecg_historico as ecg, observaciones as obs
from domain.modelos import Actividad, Medicion
from domain.paquete_sync import PaqueteInvalido, parsear_paquete, propietario_de


def T(dia, h=0, m=0, s=0):
    """Segundos Unix de un instante local de noviembre de 2026."""
    return int(datetime(2026, 11, dia, h, m, s).timestamp())


def M(ts, bpm=70.0, rpm=None, temp=None, nivel=None, etiqueta="PERIODICO", act=None, i=0):
    return Medicion(i, f"u{ts}-{i}", ts, bpm, rpm, temp, nivel, etiqueta, act)


class TestModelos(unittest.TestCase):
    def test_medicion_propiedades(self):
        m = M(T(10, 9), etiqueta="AMBOS", act=1)
        self.assertTrue(m.es_periodica)
        self.assertTrue(m.es_de_actividad)
        self.assertEqual(m.instante, datetime(2026, 11, 10, 9))
        self.assertEqual(m.media_bpm, 70.0)
        self.assertFalse(M(T(10), etiqueta="ACTIVIDAD").es_periodica)
        self.assertFalse(M(T(10)).es_de_actividad)

    def test_actividad_duracion(self):
        a = Actividad(1, "a", T(10, 9), T(10, 10), "carrera")
        self.assertEqual(a.duracion_s, 3600)
        self.assertEqual(Actividad(1, "a", 100, 50, None).duracion_s, 0)


class TestAnalisis(unittest.TestCase):
    def test_estadisticas(self):
        e = analisis.estadisticas([60, 80, float("nan"), None, 100])
        self.assertEqual((e.cantidad, e.media, e.minimo, e.maximo), (3, 80, 60, 100))
        self.assertIsNone(analisis.estadisticas([]))
        self.assertIsNone(analisis.estadisticas([float("nan")]))

    def test_valor_de_y_pares(self):
        ms = [M(1, 70, 15, 36.5, 1), M(2, 71, None, None, 255), M(3, 72, 16, None, None)]
        self.assertEqual(analisis.valor_de(ms[0], "temp"), 36.5)
        self.assertIsNone(analisis.valor_de(ms[1], "actividad"))   # sin clasificar no cuenta
        self.assertIsNone(analisis.valor_de(ms[2], "actividad"))
        self.assertEqual(analisis.pares_de(ms, "rpm"), [(1, 15.0), (3, 16.0)])
        with self.assertRaises(ValueError):
            analisis.valor_de(ms[0], "xyz")

    def test_agrupar_por_hora_con_cubos_vacios(self):
        pares = [(T(10, 9, 5), 60.0), (T(10, 9, 50), 80.0), (T(10, 11, 0), 100.0)]
        cubos = analisis.agrupar(pares, T(10, 9), T(10, 12), "hora")
        self.assertEqual(len(cubos), 3)
        self.assertEqual((cubos[0].cantidad, cubos[0].media, cubos[0].minimo, cubos[0].maximo), (2, 70.0, 60.0, 80.0))
        self.assertTrue(cubos[1].vacio)
        self.assertIsNone(cubos[1].media)
        self.assertEqual(cubos[2].cantidad, 1)
        with self.assertRaises(ValueError):
            analisis.agrupar(pares, 0, 10, "semana")

    def test_agrupar_ignora_fuera_de_rango(self):
        cubos = analisis.agrupar([(T(10, 8), 1.0), (T(10, 12), 2.0)], T(10, 9), T(10, 11), "hora")
        self.assertTrue(all(c.vacio for c in cubos))

    def test_resolucion_automatica(self):
        self.assertEqual(analisis.resolucion_automatica(0, 86400 * 2), analisis.SIN_AGRUPAR)
        self.assertEqual(analisis.resolucion_automatica(0, 86400 * 10), "hora")
        self.assertEqual(analisis.resolucion_automatica(0, 86400 * 30), "dia")

    def test_interrupciones(self):
        ts = [100, 110, 120, 500, 510]
        u = analisis.umbral_interrupcion(ts, minimo_s=25)
        self.assertGreaterEqual(u, 25)
        huecos = analisis.detectar_interrupciones(ts, 100, 510, u)
        self.assertEqual([(h.inicio, h.fin) for h in huecos], [(120, 500)])
        self.assertEqual(huecos[0].duracion_s, 380)

    def test_interrupciones_extremos_y_vacio(self):
        huecos = analisis.detectar_interrupciones([200], 0, 1000, 50)
        self.assertEqual([(h.inicio, h.fin) for h in huecos], [(0, 200), (200, 1000)])
        self.assertEqual([(h.inicio, h.fin) for h in analisis.detectar_interrupciones([], 0, 10, 5)], [(0, 10)])
        self.assertEqual(analisis.detectar_interrupciones([1], 5, 5, 1), [])

    def test_serie_con_huecos_inserta_nan(self):
        xs, ys = analisis.serie_con_huecos([(0, 1.0), (10, 2.0), (500, 3.0)], 100)
        self.assertEqual(len(xs), 4)
        self.assertNotEqual(ys[2], ys[2])    # NaN
        self.assertEqual(ys[3], 3.0)

    def test_rango_de_dias(self):
        a, b = analisis.rango_de_dias(date(2026, 11, 10), date(2026, 11, 11))
        self.assertEqual(a, T(10))
        self.assertEqual(b, T(12))


class TestEcgHistorico(unittest.TestCase):
    def test_acumulador(self):
        ac = ecg.AcumuladorEcg()
        self.assertEqual(ac.agregar(100, 1000), [])
        self.assertEqual(ac.agregar(100, 2000), [])
        self.assertEqual(ac.agregar(100, float("nan")), [])
        cerrados = ac.agregar(101, 1500)
        self.assertEqual(cerrados, [ecg.SegundoEcg(100, 1000, 2000)])
        self.assertEqual(ac.vaciar(), [ecg.SegundoEcg(101, 1500, 1500)])
        self.assertEqual(ac.vaciar(), [])

    def test_acumulador_satura_a_int16(self):
        ac = ecg.AcumuladorEcg()
        ac.agregar(1, 1e9)
        self.assertEqual(ac.vaciar()[0].maximo, 32767)

    def test_empaquetar_ida_y_vuelta(self):
        b = ecg.bloque_vacio()
        b[0], b[1] = -5, 7
        self.assertEqual(ecg.desempaquetar(ecg.empaquetar(b)), b)
        with self.assertRaises(ValueError):
            ecg.desempaquetar(b"corrupto")
        with self.assertRaises(ValueError):
            ecg.empaquetar([1, 2])

    def test_fusionar_no_sobrescribe(self):
        ts = 6000   # segundo 0 de su minuto
        b = ecg.fusionar(ecg.bloque_vacio(), [ecg.SegundoEcg(ts, 1, 2)])
        b2 = ecg.fusionar(b, [ecg.SegundoEcg(ts, 99, 99), ecg.SegundoEcg(ts + 1, 3, 4)])
        self.assertEqual((b2[0], b2[1]), (1, 2))
        self.assertEqual((b2[2], b2[3]), (3, 4))
        segs = ecg.segundos_de_bloque(ecg.minuto_de(ts), b2)
        self.assertEqual([s.ts for s in segs], [ts, ts + 1])

    def test_reducir(self):
        segs = [ecg.SegundoEcg(10 + i, 100 + i, 200 + i) for i in range(10)]
        r = ecg.reducir(segs, 10, 30, 4)
        self.assertEqual(len(r.x), 4)
        self.assertEqual(r.segundos_con_dato, 10)
        self.assertTrue(r.tiene_datos)
        self.assertEqual(r.minimo[0], 100)
        self.assertEqual(r.maximo[1], 209)       # intervalo 1 = segundos 15..19
        self.assertTrue(r.minimo[3] != r.minimo[3])   # NaN: sin datos
        self.assertFalse(ecg.reducir([], 0, 10, 5).tiene_datos)

    def test_reducir_limita_bins_a_la_duracion(self):
        self.assertEqual(len(ecg.reducir([], 0, 3, 500).x), 3)


def _paquete(**cambios):
    base = {
        "version": 1, "usuario": "Ana@Correo.com",
        "actividades": [{"uid": "a1", "inicio": T(10, 9), "fin": T(10, 10), "tipo": "carrera"}],
        "mediciones": [
            {"uid": "m1", "ts": T(10, 8), "bpm": 62, "rpm": 14, "temp": 36.4, "actividad": 0},
            {"uid": "m2", "ts": T(10, 9, 5), "bpm": 140, "etiqueta": "ACTIVIDAD", "actividad_uid": "a1"},
        ],
        "ecg": [{"ts_inicio": T(10, 9), "paso_s": 1, "minimos": [1000, 1010], "maximos": [2000, 2100]}],
    }
    base.update(cambios)
    return json.dumps(base).encode()


AHORA = T(15, 12)


class TestPaqueteSync(unittest.TestCase):
    def test_paquete_valido(self):
        p = parsear_paquete(_paquete(), AHORA)
        self.assertEqual(p.usuario, "ana@correo.com")
        self.assertEqual(len(p.mediciones), 2)
        self.assertEqual(p.mediciones[0].etiqueta, "PERIODICO")     # por omisión
        self.assertEqual(p.mediciones[1].actividad_uid, "a1")
        self.assertEqual(p.actividades[0].tipo, "carrera")
        self.assertEqual(p.ecg[0].maximos, (2000, 2100))

    def test_rechazos_globales(self):
        for datos in (b"no es json", b"[]", _paquete(version=2), _paquete(usuario="sin-arroba"),
                      json.dumps({"version": 1}).encode()):
            with self.assertRaises(PaqueteInvalido, msg=datos[:30]):
                parsear_paquete(datos, AHORA)

    def test_todo_o_nada_con_un_error(self):
        malo = {"uid": "m3", "ts": T(10, 8), "bpm": 999}
        buenas = json.loads(_paquete())["mediciones"]
        with self.assertRaises(PaqueteInvalido) as cm:
            parsear_paquete(_paquete(mediciones=buenas + [malo]), AHORA)
        self.assertTrue(any("bpm" in e for e in cm.exception.errores))

    def test_validaciones_de_medicion(self):
        casos = {
            "uid repetido": [{"uid": "x", "ts": T(10), "bpm": 70}, {"uid": "x", "ts": T(10), "bpm": 70}],
            "ts futuro": [{"uid": "x", "ts": AHORA + 10 * 86400, "bpm": 70}],
            "ts antiguo": [{"uid": "x", "ts": 5, "bpm": 70}],
            "sin uid": [{"ts": T(10), "bpm": 70}],
            "bpm texto": [{"uid": "x", "ts": T(10), "bpm": "70"}],
            "bpm bool": [{"uid": "x", "ts": T(10), "bpm": True}],
            "rpm fuera": [{"uid": "x", "ts": T(10), "bpm": 70, "rpm": 500}],
            "temp fuera": [{"uid": "x", "ts": T(10), "bpm": 70, "temp": 10}],
            "nivel raro": [{"uid": "x", "ts": T(10), "bpm": 70, "actividad": 7}],
            "etiqueta rara": [{"uid": "x", "ts": T(10), "bpm": 70, "etiqueta": "OTRA"}],
            "ACTIVIDAD sin uid": [{"uid": "x", "ts": T(10), "bpm": 70, "etiqueta": "ACTIVIDAD"}],
            "PERIODICO con uid": [{"uid": "x", "ts": T(10), "bpm": 70, "etiqueta": "PERIODICO", "actividad_uid": "a1"}],
        }
        for nombre, meds in casos.items():
            with self.subTest(nombre), self.assertRaises(PaqueteInvalido):
                parsear_paquete(_paquete(mediciones=meds), AHORA)

    def test_validaciones_de_actividad_y_ecg(self):
        malos = [
            {"actividades": [{"uid": "a", "inicio": T(10, 10), "fin": T(10, 9)}]},
            {"actividades": [{"uid": "a", "inicio": T(10), "fin": T(10, 1)}] * 2},
            {"ecg": [{"ts_inicio": T(10), "minimos": [5], "maximos": [1]}]},
            {"ecg": [{"ts_inicio": T(10), "minimos": [1, 2], "maximos": [3]}]},
            {"ecg": [{"ts_inicio": T(10), "paso_s": 2, "minimos": [1], "maximos": [2]}]},
            {"ecg": [{"ts_inicio": T(10), "minimos": [99999], "maximos": [99999]}]},
            {"mediciones": "no lista"},
        ]
        for i, c in enumerate(malos):
            with self.subTest(i), self.assertRaises(PaqueteInvalido):
                parsear_paquete(_paquete(**c), AHORA)

    def test_tolera_bom_y_floats_enteros(self):
        datos = b"\xef\xbb\xbf" + _paquete(mediciones=[{"uid": "x", "ts": float(T(10)), "bpm": 70.5}])
        self.assertEqual(parsear_paquete(datos, AHORA).mediciones[0].bpm, 70.5)

    def test_propietario_de(self):
        self.assertEqual(propietario_de(_paquete()), "ana@correo.com")
        self.assertIsNone(propietario_de(b"basura"))
        self.assertIsNone(propietario_de(b"[]"))


class TestObservaciones(unittest.TestCase):
    def _dia(self, dia, bpm_reposo, n=8, hora0=8):
        return [M(T(dia, hora0, i * 5), bpm_reposo, rpm=14, temp=36.5, nivel=0, i=i) for i in range(n)]

    def test_formatear_duracion(self):
        self.assertEqual(obs.formatear_duracion(45), "45 s")
        self.assertEqual(obs.formatear_duracion(125), "2 min 05 s")
        self.assertEqual(obs.formatear_duracion(3700), "1 h 01 min")
        self.assertEqual(obs.formatear_duracion(-5), "0 s")

    def test_fc_reposo_exige_minimo(self):
        self.assertIsNone(obs.fc_reposo(self._dia(10, 60, n=3)))
        self.assertEqual(obs.fc_reposo(self._dia(10, 60, n=8)), 60.0)

    def test_diaria_sin_datos(self):
        self.assertIsNone(obs.observacion_diaria(date(2026, 11, 10), [], {}, 10, AHORA))

    def test_diaria_normal_lleva_descargo_y_no_diagnostica(self):
        l = obs.observacion_diaria(date(2026, 11, 10), self._dia(10, 62), {}, 600, AHORA)
        texto = "\n".join(l)
        self.assertEqual(l[-1], obs.DESCARGO)
        self.assertIn("dentro de los rangos de referencia", texto)
        self.assertIn("En reposo (8 registros)", texto)

    def test_diaria_fc_alta_en_reposo(self):
        texto = "\n".join(obs.observacion_diaria(date(2026, 11, 10), self._dia(10, 110), {}, 600, AHORA))
        self.assertIn("FC en reposo elevada", texto)

    def test_alta_en_actividad_no_genera_aviso(self):
        ms = [M(T(10, 8, i * 5), 150, nivel=2, i=i) for i in range(8)]
        texto = "\n".join(obs.observacion_diaria(date(2026, 11, 10), ms, {}, 600, AHORA))
        self.assertNotIn("elevada", texto)
        self.assertIn("En actividad física", texto)
        self.assertIn("pocos registros", texto)      # sin reposo no se valora el reposo

    def test_evolucion_respecto_al_dia_anterior(self):
        previos = {date(2026, 11, 9): self._dia(9, 60)}
        texto = "\n".join(obs.observacion_diaria(date(2026, 11, 10), self._dia(10, 65), previos, 600, AHORA))
        self.assertIn("+5,0 BPM", texto)

    def test_interrupciones_se_reportan(self):
        ms = self._dia(10, 62, n=3) + self._dia(10, 62, n=3, hora0=18)
        texto = "\n".join(obs.observacion_diaria(date(2026, 11, 10), ms, {}, 60, T(10, 23)))
        self.assertIn("Interrupciones", texto)

    def test_patron_recurrente(self):
        dias = {}
        for d in (8, 9, 10):
            dias[date(2026, 11, d)] = (
                [M(T(d, 8, i), 60, nivel=0, i=i) for i in range(4)]
                + [M(T(d, 20, i), 80, nivel=0, i=10 + i) for i in range(4)]
            )
        pats = obs.detectar_patrones(dias)
        self.assertEqual(len(pats), 1)
        self.assertIn("noche", pats[0])
        self.assertEqual(obs.detectar_patrones({date(2026, 11, 8): dias[date(2026, 11, 8)]}), [])

    def test_resumen_actividad(self):
        a = Actividad(1, "a", T(10, 9), T(10, 9, 30), "carrera")
        ms = [M(T(10, 9, i), 120 + i, rpm=25, temp=36.0 + i / 10, nivel=1, etiqueta="ACTIVIDAD", act=1, i=i)
              for i in range(0, 30, 5)]
        texto = "\n".join(obs.resumen_actividad(a, ms, 60.0))
        self.assertIn("carrera", texto)
        self.assertIn("30 min", texto)
        self.assertIn("Esfuerzo estimado: alto", texto)
        self.assertIn(obs.DESCARGO, texto)

    def test_resumen_actividad_sin_datos_ni_referencia(self):
        a = Actividad(1, "a", T(10, 9), T(10, 9, 5), None)
        self.assertIn("No hay mediciones", "\n".join(obs.resumen_actividad(a, [], None)))
        ms = [M(T(10, 9), 120, etiqueta="ACTIVIDAD", act=1)]
        self.assertIn("no hay FC en reposo", "\n".join(obs.resumen_actividad(a, ms, None)))


if __name__ == "__main__":
    unittest.main()
