"""IA local: auto-etiquetado de disciplina y veredicto ejecutivo de sesión."""
import os
import time
import unittest
from datetime import datetime
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication

from services import ia_local_sesion as ia
from services.repositorio_historial import RepositorioHistorial

_app = QApplication.instance() or QApplication([])
T0 = 1_800_000_000
rng = np.random.default_rng(3)


def serie(n, f):
    return [float(f(i)) for i in range(n)]


class TestClasificador(unittest.TestCase):
    def test_fuerza_dientes_de_sierra(self):
        n = 1200
        bpm = serie(n, lambda i: 100 + 40 * ((i // 60) % 2) + rng.normal(0, 1.5))        # series de 1 min / valles de 1 min
        self.assertEqual(ia.clasificar_disciplina_automatica(bpm, duracion_s=n), "Fuerza")

    def test_carrera_pulso_alto_y_rpm_estables(self):
        n = 1800
        bpm = serie(n, lambda i: min(160, 110 + i / 6) + rng.normal(0, 1.5))
        rpm = serie(n, lambda i: 28 + rng.normal(0, 1))
        self.assertEqual(ia.clasificar_disciplina_automatica(bpm, rpm, duracion_s=n), "Carrera")

    def test_rodillo_progresion_y_deriva_termica(self):
        n = 2400
        bpm = serie(n, lambda i: 120 + 25 * i / n + rng.normal(0, 1))
        rpm = serie(n, lambda i: 20 + rng.normal(0, 1))
        temp = serie(n, lambda i: 33.0 + 1.5 * i / n + rng.normal(0, 0.05))
        self.assertEqual(ia.clasificar_disciplina_automatica(bpm, rpm, temp, n), "Rodillo/Ciclismo")

    def test_caminata_pulso_bajo_estable(self):
        n = 1800
        bpm = serie(n, lambda i: 100 + rng.normal(0, 2))
        rpm = serie(n, lambda i: 14 + rng.normal(0, 0.5))
        self.assertEqual(ia.clasificar_disciplina_automatica(bpm, rpm, duracion_s=n), "Caminata")

    def test_otra_si_es_corta_o_ambigua(self):
        self.assertEqual(ia.clasificar_disciplina_automatica([150.0] * 100, duracion_s=100), "Otra")
        n = 1200
        bpm = serie(n, lambda i: 140 + rng.normal(0, 14))                                 # ruidosa y sin patrón
        self.assertEqual(ia.clasificar_disciplina_automatica(bpm, [8.0] * n, duracion_s=n), "Otra")

    def test_es_rapido(self):
        bpm = serie(3600, lambda i: 120 + 40 * ((i // 60) % 2))
        t = time.perf_counter()
        ia.clasificar_disciplina_automatica(bpm, [20.0] * 3600, [34.0] * 3600, 3600)
        self.assertLess(time.perf_counter() - t, 0.05)


class TestVeredicto(unittest.TestCase):
    def test_tres_lineas(self):
        v = ia.generar_veredicto_sesion({"trimp": 90, "rpe": 5, "ratio": 4.1, "desacoplamiento_pct": 2.0, "duracion_s": 3000})
        self.assertEqual(len(v.splitlines()), 3)
        self.assertIn("calidad", v)
        self.assertIn("base sólida", v)

    def test_fatiga_oculta(self):
        v = ia.generar_veredicto_sesion({"trimp": 40, "rpe": 9, "ratio": 4.0, "desacoplamiento_pct": 1, "duracion_s": 3000})
        self.assertIn("fatiga oculta", v)
        self.assertIn("Coherencia Cardíaca", v)

    def test_buena_asimilacion(self):
        v = ia.generar_veredicto_sesion({"trimp": 220, "rpe": 5, "ratio": 4.0, "desacoplamiento_pct": 3, "duracion_s": 3600})
        self.assertIn("buena asimilación", v)
        self.assertIn("disponible", v)

    def test_ratio_bajo_y_deriva(self):
        v = ia.generar_veredicto_sesion({"trimp": 120, "rpe": 6, "ratio": 2.6, "desacoplamiento_pct": 7.5,
                                         "deriva_termica_c": 1.2, "duracion_s": 3600})
        self.assertIn("< 3:1", v)
        self.assertIn("deriva ≥ 5 %", v)
        self.assertIn("+1.2 °C", v)
        self.assertIn("recuperación activa", v)

    def test_sin_datos(self):
        self.assertEqual(len(ia.generar_veredicto_sesion({}).splitlines()), 3)

    def test_desacoplamiento(self):
        self.assertAlmostEqual(ia.desacoplamiento_pct([100.0] * 50 + [110.0] * 50), 10.0, delta=3)
        self.assertGreater(ia.desacoplamiento_pct([100.0] * 50 + [110.0] * 50), 5)
        self.assertIsNone(ia.desacoplamiento_pct([100.0] * 5))


def _crear(repo, uid, n, bpm_f, rpm=20.0):
    aid = repo.guardar_actividad(uid, T0, T0 + n, "x")
    for i in range(n):
        repo.guardar_medicion(bpm_f(i), datetime.fromtimestamp(T0 + i), rpm=rpm, uid=f"{uid}{i}", actividad_id=aid)
    return aid


class TestPersistencia(unittest.TestCase):
    def setUp(self):
        self.repo = RepositorioHistorial(":memory:", usuario_id=1)
        self.ia = ia.IaLocalSesion(self.repo)

    def test_etiqueta_y_cachea_veredicto(self):
        a = _crear(self.repo, "s", 600, lambda i: 100 + 40 * ((i // 60) % 2))
        self.assertIsNone(self.ia.veredicto_guardado(a))
        v = self.ia.procesar(a)
        self.assertEqual(self.repo.disciplinas()[a], "Fuerza")
        self.assertEqual(self.ia.veredicto_guardado(a), v)
        self.assertEqual(self.ia.procesar(a), v)

    def test_la_eleccion_manual_manda(self):
        a = _crear(self.repo, "m", 600, lambda i: 100 + 40 * ((i // 60) % 2))
        self.repo.guardar_disciplina(a, "Carrera")
        self.ia.procesar(a)
        self.assertEqual(self.repo.disciplinas()[a], "Carrera")
        self.repo.guardar_disciplina(a, "Caminata")                      # cambio posterior: se respeta
        self.ia.procesar(a, regenerar=True)
        self.assertEqual(self.repo.disciplinas()[a], "Caminata")
        self.repo.guardar_disciplina(a, None)                            # el usuario la quita: no reaparece
        self.ia.procesar(a, regenerar=True)
        self.assertNotIn(a, self.repo.disciplinas())

    def test_pendientes_y_rpe_regenera(self):
        a = _crear(self.repo, "p", 400, lambda i: 120)
        self.assertEqual(self.ia.procesar_pendientes(), 1)
        self.assertEqual(self.ia.procesar_pendientes(), 0)
        self.repo.guardar_nota_sesion(a, 9, "")
        self.assertIn("fatiga oculta", self.ia.procesar(a, regenerar=True))

    def test_aislado_por_usuario(self):
        a = _crear(self.repo, "u", 400, lambda i: 120)
        self.ia.procesar(a)
        otra = ia.IaLocalSesion(RepositorioHistorial(":memory:", usuario_id=2))
        self.assertIsNone(otra.veredicto_guardado(a))


class TestIntegracion(unittest.TestCase):
    def test_vm_y_vista_muestran_el_veredicto(self):
        from ui.vista_actividades import VistaActividades
        from viewmodel.vitaband_vm import VitaBandViewModel
        repo = RepositorioHistorial(":memory:", usuario_id=1)
        a = _crear(repo, "v", 900, lambda i: 150 + rng.normal(0, 1), rpm=30.0)
        vm = VitaBandViewModel(MagicMock(), repositorio=repo)
        vista = VistaActividades(vm)
        vista._mostrar_detalle(vm.detalle_actividad(a))
        self.assertEqual(vista.caja_veredicto.property("card"), "elevated")
        self.assertTrue(vista.caja_veredicto.isVisibleTo(vista))
        self.assertEqual(len(vista.lbl_veredicto.text().splitlines()), 3)
        self.assertEqual(vista.combo_disciplina.currentData(), "Carrera")
        vista.combo_disciplina.setCurrentIndex(vista.combo_disciplina.findData("Caminata"))
        vista.btn_disciplina.click()
        vista._mostrar_detalle(vm.detalle_actividad(a))
        self.assertEqual(vista.combo_disciplina.currentData(), "Caminata")      # la elección manual se respeta
        vista._mostrar_detalle(None)
        self.assertFalse(vista.caja_veredicto.isVisibleTo(vista))


if __name__ == "__main__":
    unittest.main()
