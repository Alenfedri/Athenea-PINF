"""PMC, DFA α1 / umbrales ventilatorios y curva de pulso máximo sostenido."""
import unittest
from datetime import date, datetime, timedelta

import numpy as np

from services import fisiologia_avanzada as fa
from services.repositorio_historial import RepositorioHistorial


class TestPmc(unittest.TestCase):
    def test_ctl_atl_tsb(self):
        hoy = date(2026, 11, 20)
        pmc = fa.calcular_pmc({hoy - timedelta(days=i): 100.0 for i in range(200)}, hoy, 42)
        self.assertEqual(len(pmc), 42)
        self.assertAlmostEqual(pmc[-1].ctl, 100.0, delta=1.5)        # carga constante → CTL y ATL → 100
        self.assertAlmostEqual(pmc[-1].atl, 100.0, delta=0.1)
        self.assertAlmostEqual(pmc[-1].tsb, pmc[-1].ctl - pmc[-1].atl)

    def test_pico_y_descanso_dan_forma(self):
        hoy = date(2026, 11, 20)
        carga = {hoy - timedelta(days=i): 120.0 for i in range(10, 40)}      # 30 días de carga, 10 de descanso
        p = fa.calcular_pmc(carga, hoy, 42)[-1]
        self.assertGreater(p.tsb, 0)                                         # fresco: ATL cae antes que CTL
        self.assertGreater(p.ctl, p.atl)
        # impulso unitario: primer día CTL = 1-exp(-1/42), ATL = 1-exp(-1/7)
        u = fa.calcular_pmc({hoy: 100.0}, hoy, 42)[-1]
        self.assertAlmostEqual(u.ctl, 100 * (1 - np.exp(-1 / 42)), places=6)
        self.assertAlmostEqual(u.atl, 100 * (1 - np.exp(-1 / 7)), places=6)
        self.assertLess(u.tsb, 0)

    def test_ventana_y_dias_sin_datos(self):
        hoy = date(2026, 11, 20)
        pmc = fa.calcular_pmc({}, hoy, 90)
        self.assertEqual((len(pmc), pmc[0].fecha, pmc[-1].fecha), (90, hoy - timedelta(days=89), hoy))
        self.assertEqual(pmc[-1].ctl, 0)
        with self.assertRaises(ValueError):
            fa.calcular_pmc({}, hoy, 0)

    def test_trimp_diario_de_la_bd(self):
        repo = RepositorioHistorial(":memory:", usuario_id=1)
        ini = int(datetime(2026, 11, 19, 9).timestamp())
        a = repo.guardar_actividad("a", ini, ini + 1800, "carrera")
        for s in range(0, 1800, 10):
            repo.guardar_medicion(150, datetime.fromtimestamp(ini + s), uid=f"m{s}", actividad_id=a)
        t = fa.trimp_diario(repo, date(2026, 11, 20))
        self.assertGreater(t[date(2026, 11, 19)], 0)


class TestUmbrales(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(1)

    def test_alfa1_ruido_blanco_vs_correlado(self):
        blanco = 700 + self.rng.normal(0, 30, 400)
        correlado = 700 + np.cumsum(self.rng.normal(0, 8, 400))
        a_b, a_c = fa.dfa_alfa1(blanco), fa.dfa_alfa1(correlado)
        self.assertLess(a_b, 0.75)
        self.assertGreater(a_c, 1.2)
        self.assertIsNone(fa.dfa_alfa1([800.0] * 20))

    def test_vt1_cruce_075_en_serie_sintetica(self):
        # Fase 1 (RR ~ 780 ms, correlados → α1 alto) y fase 2 (RR ~ 550 ms, ruido blanco → α1 bajo)
        n1 = 400
        f1 = 780 + np.cumsum(self.rng.normal(0, 4, n1)) - 0.5 * np.arange(n1)
        f1 = np.clip(f1, 650, 900)
        f2 = 520 + self.rng.normal(0, 25, 500)
        rr = np.concatenate([f1, f2])
        puntos = fa.alfa1_deslizante(rr)
        self.assertGreater(len(puntos), 5)
        vt1 = fa.cruce_alfa1(puntos)
        self.assertIsNotNone(vt1)
        self.assertEqual(vt1.nombre, "VT1")
        self.assertTrue(55 < vt1.bpm < 130, vt1.bpm)
        self.assertEqual(vt1.valor, 0.75)

    def test_cruce_interpola(self):
        pts = [fa.PuntoAlfa(0, 1.0, 100), fa.PuntoAlfa(10, 0.5, 140)]
        v = fa.cruce_alfa1(pts)
        self.assertAlmostEqual(v.bpm, 120.0)
        self.assertAlmostEqual(v.t_s, 5.0)
        self.assertIsNone(fa.cruce_alfa1([fa.PuntoAlfa(0, 0.6, 100), fa.PuntoAlfa(10, 0.5, 140)]))

    def test_vt2_por_inflexion_de_rpm(self):
        t = np.arange(0, 600, 10.0)
        rpm = np.where(t < 300, 15 + 0.01 * t, 18 + 0.12 * (t - 300))
        infl = fa.inflexion_rpm(t, rpm)
        self.assertIsNotNone(infl)
        self.assertAlmostEqual(infl[0], 300, delta=30)
        self.assertIsNone(fa.inflexion_rpm(t, 15 + 0.01 * t))            # sin cambio de pendiente
        self.assertIsNone(fa.inflexion_rpm([1, 2, 3], [1, 2, 3]))

    def test_detectar_conjunto(self):
        rr = np.concatenate([np.clip(780 + np.cumsum(self.rng.normal(0, 4, 400)) - 0.5 * np.arange(400), 650, 900),
                             520 + self.rng.normal(0, 25, 700)])
        total_s = rr.sum() / 1000
        t = np.arange(0, total_s, 10.0)
        rpm = np.where(t < total_s * 0.7, 16.0 + 0.005 * t, 17 + 0.1 * (t - total_s * 0.7))
        r = fa.detectar_umbrales_ventilatorios(rr, t, rpm)
        self.assertIn("VT1", r)
        self.assertIn("VT2", r)
        if r["VT1"] and r["VT2"]:
            self.assertGreater(r["VT2"].bpm, r["VT1"].bpm)


class TestCurvaPico(unittest.TestCase):
    def sesion(self, tramos, t0=1_700_000_000):
        pts, t = [], t0
        for dur, bpm in tramos:
            for _ in range(dur):
                pts.append((t, bpm))
                t += 1
        return pts

    def test_picos_por_duracion(self):
        s = self.sesion([(600, 120), (300, 170), (600, 130)])
        c = fa.calcular_curva_pico_hr([s])
        self.assertAlmostEqual(c[5], 170, delta=0.01)
        self.assertAlmostEqual(c[60], 170, delta=0.01)
        self.assertAlmostEqual(c[300], 170, delta=0.5)
        self.assertAlmostEqual(c[1200], (300 * 170 + 600 * 130 + 300 * 120) / 1200, delta=3)
        self.assertIsNone(c[3600])                                    # sesión de 25 min < 60 min

    def test_un_hueco_rompe_la_ventana(self):
        a = self.sesion([(60, 150)])
        b = self.sesion([(60, 150)], t0=1_700_000_000 + 300)          # 4 min de hueco
        self.assertIsNone(fa.calcular_curva_pico_hr([a + b], (120,))[120])

    def test_temporadas(self):
        repo = RepositorioHistorial(":memory:", usuario_id=1)
        hoy = date(2026, 11, 20)
        for dias, bpm in ((30, 160), (400, 150)):
            ini = int(datetime.combine(hoy - timedelta(days=dias), datetime.min.time()).timestamp()) + 36000
            a = repo.guardar_actividad(f"a{dias}", ini, ini + 400, "carrera")
            for s in range(400):
                repo.guardar_medicion(bpm, datetime.fromtimestamp(ini + s), uid=f"m{dias}-{s}", actividad_id=a)
        actual, anterior = fa.curvas_por_temporada(repo, hoy)
        self.assertAlmostEqual(actual[60], 160, delta=0.01)
        self.assertAlmostEqual(anterior[60], 150, delta=0.01)
        self.assertIsNone(actual[1200])


if __name__ == "__main__":
    unittest.main()
