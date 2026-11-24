"""HRV (RMSSD): picos R a 100 Hz, rechazo de ruido, guardado y observación de recuperación."""

import math
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

from domain import hrv
from domain.ui_state import ConexionEstado
from services.repositorio_cuentas import RepositorioCuentas
from services.repositorio_historial import RepositorioHistorial
from services.servicio_observaciones import ServicioObservaciones
from viewmodel.vitaband_vm import VitaBandViewModel

HOY = date.today() - timedelta(days=1)
DESCARGO = "no constituye un diagnóstico médico"


def ecg_sintetico(rr_muestras, dur_s=60, ruido=5.0, deriva=0.0, semilla=1, offset=0.0):
    """ECG a 100 Hz: línea base 1600, R gaussiana de 20 ms, R-R dados en muestras (cíclicos)."""
    n = dur_s * 100
    t = np.arange(n)
    x = np.full(n, 1600.0)
    pos, k = 10 + offset, 0
    while pos < n - 10:
        x += 800 * np.exp(-0.5 * ((t - pos) / 2.0) ** 2)
        pos += rr_muestras[k % len(rr_muestras)]
        k += 1
    x += np.random.default_rng(semilla).normal(0, ruido, n)
    if deriva:
        x += deriva * np.sin(2 * np.pi * 0.3 * t / 100)
    return x


def ts(h, m=0, dia=HOY):
    return int(datetime(dia.year, dia.month, dia.day, h, m).timestamp())


class TestRmssd(unittest.TestCase):

    def test_formula_exacta(self):
        # diferencias 40,-40,40,-40 → sqrt((4·1600)/4) = 40
        self.assertAlmostEqual(hrv.rmssd([800, 840, 800, 840, 800]), 40.0)
        self.assertAlmostEqual(hrv.rmssd([1000, 1000, 1000]), 0.0)
        self.assertAlmostEqual(hrv.rmssd([800, 860, 830]), math.sqrt((60 ** 2 + 30 ** 2) / 2))
        self.assertIsNone(hrv.rmssd([800]))

    def test_rmssd_sobre_onda_sintetica_conocida(self):
        r = hrv.evaluar_ventana(ecg_sintetico([80, 84], ruido=0), ts=100)    # R-R 800/840 ms
        self.assertAlmostEqual(r.rmssd_ms, 40.0, places=3)
        self.assertAlmostEqual(r.fc_media, 60000 / 820, delta=0.1)
        self.assertEqual(r.ts, 100)
        self.assertGreaterEqual(r.latidos, 60)

    def test_con_ruido_y_deriva_de_linea_base(self):
        r = hrv.evaluar_ventana(ecg_sintetico([80, 84], ruido=8, deriva=150))
        self.assertAlmostEqual(r.rmssd_ms, 40.0, delta=2.0)

    def test_variabilidad_distinta_da_valor_distinto(self):
        baja = hrv.evaluar_ventana(ecg_sintetico([80, 82]))                  # ≈ 20 ms
        alta = hrv.evaluar_ventana(ecg_sintetico([75, 85, 70, 90]))
        self.assertAlmostEqual(baja.rmssd_ms, 20.0, delta=2.0)
        self.assertGreater(alta.rmssd_ms, baja.rmssd_ms * 2)

    def test_polaridad_invertida(self):
        x = 3200 - ecg_sintetico([80, 84], ruido=2)
        self.assertAlmostEqual(hrv.evaluar_ventana(x).rmssd_ms, 40.0, delta=2.0)


class TestPicosR(unittest.TestCase):

    def test_detecta_cada_latido_a_100_hz(self):
        picos = hrv.detectar_picos_r(ecg_sintetico([80, 84], dur_s=20, ruido=3))
        esperados, pos, k = [], 10, 0
        while pos < 1990:                       # misma construcción que ecg_sintetico
            esperados.append(pos)
            pos += (80, 84)[k % 2]
            k += 1
        self.assertEqual(len(picos), len(esperados))
        np.testing.assert_allclose(picos, esperados, atol=0.5)

    def test_intervalos_en_ms(self):
        rr = hrv.intervalos_rr_ms(hrv.detectar_picos_r(ecg_sintetico([80, 84], dur_s=20, ruido=0)))
        self.assertEqual(set(np.round(rr).astype(int)), {800, 840})

    def test_periodo_refractario(self):
        # Un pico secundario 150 ms tras la R (< 300 ms) no cuenta como latido
        x = ecg_sintetico([80], dur_s=20, ruido=0)
        for p in range(10, 1990, 80):
            x[p + 15] += 500
        picos = hrv.detectar_picos_r(x)
        self.assertTrue(np.all(np.diff(picos) > 70))

    def test_precision_subdivision_de_muestra(self):
        # R-R de 812,5 ms (81,25 muestras): la interpolación evita el error de ±10 ms
        r = hrv.evaluar_ventana(ecg_sintetico([81.25, 84.25], ruido=0))
        self.assertAlmostEqual(r.rmssd_ms, 30.0, delta=1.5)


class TestRechazo(unittest.TestCase):

    def test_ruido_blanco(self):
        x = np.random.default_rng(2).normal(1600, 300, 6000)
        self.assertIsNone(hrv.evaluar_ventana(x))

    def test_ruido_con_artefactos_de_movimiento(self):
        x = ecg_sintetico([80, 84], ruido=5)
        x[2000:3800] = np.random.default_rng(3).normal(1600, 600, 1800)
        self.assertIsNone(hrv.evaluar_ventana(x))

    def test_pocos_latidos(self):
        self.assertIsNone(hrv.evaluar_ventana(ecg_sintetico([300], ruido=2)))      # 20 lpm

    def test_senal_plana_o_no_finita(self):
        self.assertIsNone(hrv.evaluar_ventana(np.full(6000, 1600.0)))
        x = ecg_sintetico([80, 84])
        x[100] = np.nan
        self.assertIsNone(hrv.evaluar_ventana(x))
        self.assertIsNone(hrv.evaluar_ventana(ecg_sintetico([80], dur_s=5)))      # ventana demasiado corta

    def test_intervalos_imposibles_se_descartan(self):
        # 250 ms (240 lpm) y 2100 ms no son fisiológicos: nada válido → None
        self.assertIsNone(hrv.evaluar_ventana(ecg_sintetico([25, 31], ruido=2)))
        self.assertIsNone(hrv.evaluar_ventana(ecg_sintetico([210, 215], ruido=2)))

    def test_saltos_bruscos_no_inflan_el_rmssd(self):
        # Un latido no detectado cada ~10 duplicaría un R-R; esas parejas se excluyen
        x = ecg_sintetico([80, 84], ruido=2)
        for p in (170, 590, 1010, 1430, 1850, 2270):
            x[p - 6:p + 7] = 1600
        r = hrv.evaluar_ventana(x)
        self.assertTrue(r is None or r.rmssd_ms < 60)


class TestAcumulador(unittest.TestCase):

    def alimentar(self, acum, x, t0=1000.0, dt=0.01):
        salida = None
        for i, v in enumerate(x):
            salida = acum.agregar(t0 + i * dt, float(v)) or salida
        return salida

    def test_ventana_completa_da_resultado(self):
        r = self.alimentar(hrv.AcumuladorHrv(), ecg_sintetico([80, 84], ruido=0))
        self.assertAlmostEqual(r.rmssd_ms, 40.0, places=3)
        self.assertEqual(r.ts, 1000)

    def test_ventana_incompleta_no_da_nada(self):
        self.assertIsNone(self.alimentar(hrv.AcumuladorHrv(), ecg_sintetico([80, 84], ruido=0)[:5000]))

    def test_reiniciar_descarta_lo_acumulado(self):
        a = hrv.AcumuladorHrv()
        self.alimentar(a, ecg_sintetico([80, 84])[:3000])
        a.reiniciar()
        self.assertIsNone(self.alimentar(a, ecg_sintetico([80, 84])[:3000], t0=2000))

    def test_tasa_de_llegada_distinta_de_100_hz_descarta(self):
        # Llegan a 50 Hz: los R-R en ms no serían fiables
        self.assertIsNone(self.alimentar(hrv.AcumuladorHrv(), ecg_sintetico([80, 84]), dt=0.02))

    def test_muestra_no_finita_reinicia(self):
        a = hrv.AcumuladorHrv()
        self.alimentar(a, ecg_sintetico([80, 84])[:3000])
        a.agregar(1031.0, float("nan"))
        self.assertIsNone(self.alimentar(a, ecg_sintetico([80, 84])[:3000], t0=2000))


class TestIndicador(unittest.TestCase):

    def test_clasificacion(self):
        self.assertEqual(hrv.clasificar(65), hrv.ESTADO_OPTIMO)
        self.assertEqual(hrv.clasificar(50), hrv.ESTADO_OPTIMO)
        self.assertEqual(hrv.clasificar(35), hrv.ESTADO_EQUILIBRADO)
        self.assertEqual(hrv.clasificar(20), hrv.ESTADO_EQUILIBRADO)
        self.assertEqual(hrv.clasificar(12), hrv.ESTADO_ESTRES)

    def ventanas(self, valores, t0=1000):
        return [hrv.ResultadoHrv(t0 + 60 * i, v, 65.0, 60) for i, v in enumerate(valores)]

    def test_lineas_con_valor_y_estado(self):
        lineas = hrv.lineas_recuperacion(self.ventanas([30, 32, 34, 36, 38, 99]))
        self.assertIn("Estado equilibrado", lineas[0])
        self.assertIn("34,0 ms", lineas[0])                       # mediana de las 5 primeras
        self.assertIn("5 min", lineas[0])

    def test_comparacion_con_dias_anteriores(self):
        lineas = hrv.lineas_recuperacion(self.ventanas([40, 40, 40]), base_ms=50.0)
        self.assertTrue(any("-10,0 ms respecto a tu media" in l for l in lineas))

    def test_pocas_ventanas_o_ninguna(self):
        self.assertEqual(hrv.lineas_recuperacion([]), [])
        self.assertIn("aún no hay", hrv.lineas_recuperacion(self.ventanas([40, 40]))[0])


class BaseRepo(unittest.TestCase):
    def setUp(self):
        self.repo = RepositorioHistorial(":memory:", usuario_id=1)

    def tearDown(self):
        self.repo.cerrar()

    def hrv(self, h, m, valor, dia=HOY):
        self.repo.guardar_hrv(hrv.ResultadoHrv(ts(h, m, dia), valor, 62.0, 55))


class TestGuardado(BaseRepo):

    def test_guardar_y_consultar_por_rango(self):
        self.hrv(8, 0, 41.5)
        self.hrv(8, 1, 43.0)
        self.hrv(9, 0, 50.0)
        r = self.repo.hrv_rango(ts(8), ts(9))
        self.assertEqual([x.rmssd_ms for x in r], [41.5, 43.0])
        self.assertEqual(r[0].latidos, 55)

    def test_misma_ventana_se_reemplaza(self):
        self.hrv(8, 0, 41.0)
        self.hrv(8, 0, 44.0)
        self.assertEqual([x.rmssd_ms for x in self.repo.hrv_rango(0, 2 ** 31)], [44.0])

    def test_borrar_todo_la_limpia(self):
        self.hrv(8, 0, 41.0)
        self.repo.borrar_todo()
        self.assertEqual(self.repo.hrv_rango(0, 2 ** 31), [])

    def test_purga_elimina_la_vencida(self):
        vieja, nueva = HOY - timedelta(days=40), HOY
        self.hrv(8, 0, 40.0, vieja)
        self.hrv(8, 0, 45.0, nueva)
        self.repo.purgar(ts(12, 0, date.today()), dias_periodico=30, dias_actividades=365)
        self.assertEqual([x.rmssd_ms for x in self.repo.hrv_rango(0, 2 ** 31)], [45.0])

    def test_borrar_mediciones_del_periodo_limpia_su_hrv(self):
        ids = [self.repo.guardar_medicion(65, datetime.fromtimestamp(ts(8, 0) + 10 * i), uid=f"m{i}")
               for i in range(6)]
        self.hrv(8, 0, 41.0)
        self.hrv(10, 0, 44.0)                                      # sin mediciones propias
        self.repo.quitar_del_periodico(ids)
        self.assertEqual(self.repo.hrv_rango(0, 2 ** 31), [])

    def test_borrar_algunas_mediciones_conserva_la_hrv(self):
        ids = [self.repo.guardar_medicion(65, datetime.fromtimestamp(ts(8, 0) + 10 * i), uid=f"m{i}")
               for i in range(6)]
        self.hrv(8, 0, 41.0)
        self.repo.quitar_del_periodico(ids[:2])
        self.assertEqual(len(self.repo.hrv_rango(0, 2 ** 31)), 1)

    def test_eliminar_cuenta_borra_la_hrv_y_no_la_de_otro(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "t.db")
            cuentas = RepositorioCuentas(ruta)
            u1 = cuentas.crear("a@x.com", "A", "Clave-Segura-123", "AAAA", 1.0)
            u2 = cuentas.crear("b@x.com", "B", "Clave-Segura-123", "BBBB", 1.0)
            h1, h2 = RepositorioHistorial(ruta, u1), RepositorioHistorial(ruta, u2)
            for h in (h1, h2):
                h.guardar_hrv(hrv.ResultadoHrv(ts(8), 42.0, 70.0, 60))
            self.assertTrue(cuentas.eliminar(u1))
            self.assertEqual(h1.hrv_rango(0, 2 ** 31), [])
            self.assertEqual(len(h2.hrv_rango(0, 2 ** 31)), 1)
            h1.cerrar()
            h2.cerrar()
            cuentas.cerrar()


class TestObservacionRecuperacion(BaseRepo):

    def sembrar_dia(self, dia, valores):
        for i in range(30):
            self.repo.guardar_medicion(62, datetime.fromtimestamp(ts(8, 0, dia) + 10 * i), uid=f"{dia}-{i}",
                                       nivel_actividad=0)
        for i, v in enumerate(valores):
            self.hrv(8, i, v, dia)

    def texto(self, dia=HOY):
        ServicioObservaciones(self.repo, reloj=lambda: ts(23, 0, date.today())).actualizar_todo()
        o = self.repo.observaciones_rango(ts(0, 0, dia), ts(0, 0, dia + timedelta(days=1)), "DIARIA")
        return o[0].texto if o else ""

    def test_dia_con_hrv_genera_la_linea_de_recuperacion_antes_del_descargo(self):
        self.sembrar_dia(HOY, [55, 57, 59])
        t = self.texto()
        self.assertIn("Recuperación óptima", t)
        self.assertIn("57,0 ms", t)
        self.assertLess(t.index("Recuperación"), t.index(DESCARGO))
        self.assertTrue(t.rstrip().endswith("diagnóstico médico."))

    def test_estres_fisiologico(self):
        self.sembrar_dia(HOY, [12, 14, 16])
        self.assertIn("Estrés fisiológico / Fatiga", self.texto())

    def test_compara_con_los_dias_anteriores(self):
        self.sembrar_dia(HOY - timedelta(days=1), [50, 50, 50])
        self.sembrar_dia(HOY, [40, 40, 40])
        self.assertIn("-10,0 ms respecto a tu media", self.texto())

    def test_sin_hrv_la_observacion_no_cambia(self):
        self.sembrar_dia(HOY, [])
        t = self.texto()
        self.assertNotIn("Recuperación", t)
        self.assertIn(DESCARGO, t)

    def test_se_actualiza_cuando_llegan_nuevas_ventanas(self):
        self.sembrar_dia(HOY, [40, 40])
        self.assertIn("aún no hay", self.texto())
        self.hrv(8, 2, 40.0)
        self.assertIn("Estado equilibrado", self.texto())


class TestViewModel(unittest.TestCase):

    def setUp(self):
        self.t = [1_700_000_000.0]
        self.repo = RepositorioHistorial(":memory:", usuario_id=1)
        self.vm = VitaBandViewModel(MagicMock(), repositorio=self.repo, reloj=lambda: self.t[0])
        self.vm._state = self.vm._state.__class__(**{**self.vm._state.__dict__,
                                                     "conexionEstado": ConexionEstado.CONECTADO})

    def tearDown(self):
        self.vm.cerrar()

    def alimentar(self, x, nivel=0):
        for v in x:
            self.t[0] += 0.01
            self.vm._acumular_hrv(float(v), nivel)

    def test_en_reposo_guarda_el_rmssd(self):
        self.alimentar(ecg_sintetico([80, 84], ruido=0))
        guardado = self.repo.hrv_rango(0, 2 ** 31)
        self.assertEqual(len(guardado), 1)
        self.assertAlmostEqual(guardado[0].rmssd_ms, 40.0, places=2)

    def test_en_actividad_no_guarda_y_reinicia(self):
        x = ecg_sintetico([80, 84], ruido=0)
        self.alimentar(x[:3000])
        self.alimentar(x[3000:3100], nivel=1)                       # un instante de movimiento
        self.alimentar(x[:3000])                                    # solo 30 s tras el reinicio
        self.assertEqual(self.repo.hrv_rango(0, 2 ** 31), [])

    def test_en_ecg_crudo_o_sin_conexion_no_guarda(self):
        e = self.vm._state
        self.vm._state = e.__class__(**{**e.__dict__, "modoEcgCrudo": True})
        self.alimentar(ecg_sintetico([80, 84], ruido=0))
        self.vm._state = e.__class__(**{**e.__dict__, "conexionEstado": ConexionEstado.CALIBRANDO})
        self.alimentar(ecg_sintetico([80, 84], ruido=0))
        self.assertEqual(self.repo.hrv_rango(0, 2 ** 31), [])

    def test_senal_ruidosa_no_guarda(self):
        self.alimentar(np.random.default_rng(4).normal(1600, 300, 6000))
        self.assertEqual(self.repo.hrv_rango(0, 2 ** 31), [])

    def test_sin_repositorio_no_falla(self):
        vm = VitaBandViewModel(MagicMock())
        vm._acumular_hrv(1600.0, 0)


if __name__ == "__main__":
    unittest.main()
