"""Coherencia cardíaca (onda guiada, índice, diálogo) y diagrama de Poincaré (R-R, SD1/SD2, atípicos)."""

import math
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication

from domain.ui_state import ConexionEstado
from services import coherencia as co
from services import poincare as po
from services.repositorio_historial import RepositorioHistorial
from ui.dialogo_coherencia import DialogoCoherencia
from ui.main_window import MainWindow
from ui.panel_poincare import PanelPoincare
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])


def ecg_sintetico(rr_ms, fs=100, ruido=0.02, semilla=1):
    """ECG con un pico R gaussiano en cada latido; devuelve (muestras, instantes de los picos en ms)."""
    rng = np.random.default_rng(semilla)
    t_picos = np.cumsum([500.0] + list(rr_ms))
    n = int(t_picos[-1] / 1000 * fs) + 100
    x = rng.normal(0, ruido, n)
    k = np.arange(n) * 1000.0 / fs
    for tp in t_picos:
        x += np.exp(-((k - tp) ** 2) / (2 * 15.0 ** 2))
    return x, t_picos


class TestOndaGuiada(unittest.TestCase):

    def test_seis_rpm_son_5s_inhalar_y_5s_exhalar(self):
        self.assertEqual(co.RPM_GUIA, 6.0)
        self.assertAlmostEqual(co.periodo_s(), 10.0)
        self.assertAlmostEqual(co.onda_objetivo(0), 0.0)
        self.assertAlmostEqual(co.onda_objetivo(5), 1.0)
        self.assertAlmostEqual(co.onda_objetivo(10), 0.0)
        self.assertEqual([co.fase(t) for t in (0, 4.9, 5, 9.9, 10)], ["Inhala", "Inhala", "Exhala", "Exhala", "Inhala"])
        self.assertEqual(co.DURACIONES_MIN, (2, 3, 5))

    def test_otro_ritmo(self):
        self.assertAlmostEqual(co.periodo_s(12), 5.0)


class TestIndice(unittest.TestCase):

    def serie(self, f_hz, seg=120, amp=5.0):
        return [(t, 70 + amp * math.sin(2 * math.pi * f_hz * t)) for t in range(seg)]

    def test_oscilacion_a_la_frecuencia_guiada_da_indice_alto(self):
        self.assertGreater(co.indice_coherencia(self.serie(0.1)), 80)

    def test_oscilacion_a_otra_frecuencia_da_indice_bajo(self):
        self.assertLess(co.indice_coherencia(self.serie(0.25)), 15)

    def test_pulso_constante_da_cero(self):
        self.assertEqual(co.indice_coherencia([(t, 70.0) for t in range(60)]), 0.0)

    def test_pocos_datos_o_poca_duracion_no_dan_indice(self):
        self.assertIsNone(co.indice_coherencia([]))
        self.assertIsNone(co.indice_coherencia(self.serie(0.1, seg=20)))
        self.assertIsNone(co.indice_coherencia([(t, 70.0) for t in (0, 10, 40)]))

    def test_se_ignoran_valores_invalidos_y_se_acota(self):
        s = self.serie(0.1) + [(130, 0.0), (131, float("nan"))]
        self.assertTrue(0 <= co.indice_coherencia(s) <= 100)

    def test_resultado_resume_la_sesion(self):
        r = co.resultado(self.serie(0.1), [5.8, 6.2], 120)
        self.assertAlmostEqual(r.rpm_medio, 6.0)
        self.assertAlmostEqual(r.bpm_medio, 70, delta=0.5)
        self.assertAlmostEqual(r.amplitud_bpm, 10, delta=0.5)
        self.assertIn("Coherencia", r.texto())
        vacio = co.resultado([], [], 10)
        self.assertIsNone(vacio.indice)
        self.assertIn("insuficientes", vacio.texto())


class Reloj:
    t = 1_000.0

    def __call__(self):
        return self.t


class Base(unittest.TestCase):
    def setUp(self):
        self.reloj = Reloj()
        self.repo = RepositorioHistorial(":memory:", usuario_id=1)
        self.vm = VitaBandViewModel(MagicMock(), repositorio=self.repo, reloj=self.reloj)

    def tearDown(self):
        self.vm.cerrar()

    def estado(self, **kw):
        self.vm._emitir_nuevo_estado(conexionEstado=ConexionEstado.CONECTADO, **kw)


class TestSesionCoherenciaVm(Base):

    def test_captura_y_resultado(self):
        self.estado()
        self.vm.iniciar_coherencia()
        for i in range(120):
            self.reloj.t += 1
            self.estado(bpmTexto=f"{70 + 5 * math.sin(2 * math.pi * 0.1 * i):.1f} BPM", rpmTexto="6.0 RPM")
        r = self.vm.detener_coherencia()
        self.assertGreater(r.indice, 60)
        self.assertAlmostEqual(r.rpm_medio, 6.0)
        self.assertIsNone(self.vm._captura_coh)
        self.assertIsNone(self.vm.detener_coherencia().indice)          # sin sesión: vacío, sin error

    def test_sin_banda_no_captura(self):
        self.vm.iniciar_coherencia()
        self.reloj.t += 60
        self.vm._emitir_nuevo_estado(conexionEstado=ConexionEstado.DESCONECTADO, bpmTexto="70.0 BPM")
        self.assertEqual(self.vm.detener_coherencia().bpm_medio, None)


class TestDialogoCoherencia(Base):

    def setUp(self):
        super().setUp()
        self.d = DialogoCoherencia(self.vm, reloj=self.reloj)

    def tearDown(self):
        self.d.close()
        super().tearDown()

    def test_selector_de_duracion(self):
        self.assertEqual([self.d.combo_duracion.itemData(i) for i in range(3)], [2, 3, 5])
        self.assertEqual(self.d.combo_duracion.currentData(), 2)

    def test_sesion_completa_con_guia_y_resultado(self):
        self.d.combo_duracion.setCurrentIndex(0)
        self.d.iniciar()
        self.assertTrue(self.d.en_curso)
        self.assertFalse(self.d.btn_iniciar.isEnabled())
        self.assertEqual(self.d.lbl_fase.text(), "Inhala")
        for i in range(1, 125):
            self.reloj.t = 1_000.0 + i
            bpm = 70 + 5 * math.sin(2 * math.pi * 0.1 * i)
            self.vm.state_changed.emit(SimpleNamespace(bpmTexto=f"{bpm:.1f} BPM", rpmTexto="6.0 RPM"))
            self.estado(bpmTexto=f"{bpm:.1f} BPM", rpmTexto="6.0 RPM")
            self.d.tick()
            if i == 7:
                self.assertEqual(self.d.lbl_fase.text(), "Exhala")
                self.assertIn("Quedan", self.d.lbl_tiempo.text())
                self.assertGreater(len(self.d.curva_objetivo.getData()[0]), 0)
                self.assertGreater(len(self.d.curva_rpm.getData()[0]), 0)
        self.assertFalse(self.d.en_curso)
        self.assertTrue(self.d.btn_iniciar.isEnabled())
        self.assertEqual(self.d.lbl_fase.text(), "Sesión terminada")
        self.assertIsNotNone(self.d.resultado.indice)
        self.assertGreater(self.d.resultado.indice, 60)
        self.assertIn("Coherencia", self.d.lbl_resultado.text())

    def test_cerrar_a_medias_libera_la_captura(self):
        self.d.iniciar()
        self.d.close()
        self.assertFalse(self.d.en_curso)
        self.assertIsNone(self.vm._captura_coh)

    def test_boton_en_tiempo_real(self):
        v = MainWindow(self.vm, "Ana")
        self.assertEqual(v.btn_coherencia.text(), "Coherencia Cardíaca")
        v.btn_coherencia.click()
        self.assertIsInstance(v.dialogo_coherencia, DialogoCoherencia)
        v.dialogo_coherencia.close()
        v.close()


class TestPoincare(unittest.TestCase):

    def test_coordenadas_de_pares_consecutivos(self):
        p = po.calcular_poincare([[800, 810, 790, 805, 795, 800, 810, 790, 805, 795, 800, 810]])
        pares = list(zip(p.x, p.y))
        self.assertEqual(pares[0], (800, 810))
        self.assertEqual(pares[1], (810, 790))
        self.assertEqual(p.n, 11)
        self.assertEqual(p.n_atipicos, 0)

    def test_sd1_sd2_de_una_serie_conocida(self):
        rr = [800.0 + (20 if i % 2 else -20) for i in range(40)]           # alterna ±20 ms
        p = po.calcular_poincare([rr])
        # |dif| = 40 siempre: SD1 = 40/√2 · (≈1), SD2 ≈ pequeña
        self.assertAlmostEqual(p.sd1, 40 / math.sqrt(2), delta=1.0)
        self.assertLess(p.sd2, p.sd1)
        self.assertEqual(p.cociente, p.sd1 / p.sd2)

    def test_sd2_domina_con_deriva_lenta(self):
        rr = [700 + 5 * i for i in range(40)]                              # tendencia suave
        p = po.calcular_poincare([rr])
        self.assertGreater(p.sd2, 10 * p.sd1)

    def test_formula_directa(self):
        rng = np.random.default_rng(3)
        rr = list(800 + rng.normal(0, 25, 200))
        p = po.calcular_poincare([rr])
        x, y = np.array(rr[:-1]), np.array(rr[1:])
        self.assertAlmostEqual(p.sd1, np.std(y - x, ddof=1) / math.sqrt(2), places=6)
        self.assertAlmostEqual(p.sd2, np.std(y + x, ddof=1) / math.sqrt(2), places=6)

    def test_atipicos_fuera_de_rango_o_salto_brusco(self):
        base = [800.0, 805.0, 795.0] * 6
        rr = base + [1300.0] + base                  # salto brusco ectópico: pares (795,1300) y (1300,800)
        p = po.calcular_poincare([rr])
        self.assertEqual(p.n_atipicos, 2)
        self.assertIn((795.0, 1300.0), list(zip(p.atipicos_x, p.atipicos_y)))
        fuera = po.calcular_poincare([[250.0, 260.0, 255.0]])
        self.assertEqual((fuera.n, fuera.n_atipicos), (0, 2))
        self.assertTrue(po.par_atipico(800, 2500))
        self.assertFalse(po.par_atipico(800, 820))

    def test_los_atipicos_no_ensucian_sd(self):
        base = [800.0, 810.0, 790.0, 805.0] * 6
        limpio = po.calcular_poincare([base])
        sucio = po.calcular_poincare([base + [1400.0] + base])
        self.assertEqual(sucio.n_atipicos, 2)
        self.assertAlmostEqual(sucio.sd1, limpio.sd1, delta=limpio.sd1 * 0.15)

    def test_no_se_forman_pares_entre_ventanas(self):
        p = po.calcular_poincare([[800.0] * 6, [1000.0] * 6])
        self.assertEqual(p.n, 10)
        self.assertEqual(p.n_atipicos, 0)

    def test_pocos_pares_no_dan_sd(self):
        p = po.calcular_poincare([[800, 810, 790]])
        self.assertIsNone(p.sd1)
        self.assertIn("insuficientes", p.texto())
        self.assertEqual(po.calcular_poincare([]).n, 0)


class TestRrDesdeEcg(unittest.TestCase):

    def test_detecta_los_intervalos_del_ecg_a_100_hz(self):
        rr_real = [800.0 + (30 if i % 2 else -30) for i in range(70)]
        x, _ = ecg_sintetico(rr_real)
        rr = po.rr_de_ventana(x[:6000])
        self.assertIsNotNone(rr)
        self.assertGreater(len(rr), 50)
        self.assertAlmostEqual(float(np.mean(rr)), 800.0, delta=15)
        self.assertAlmostEqual(float(np.std(rr)), 30.0, delta=8)

    def test_ruido_o_senal_plana_no_dan_rr(self):
        self.assertIsNone(po.rr_de_ventana(np.zeros(6000)))
        self.assertIsNone(po.rr_de_ventana(np.random.default_rng(0).normal(0, 1, 6000)))
        self.assertIsNone(po.rr_de_ventana([1.0] * 100))

    def test_acumulador_devuelve_una_ventana_por_minuto(self):
        x, _ = ecg_sintetico([800.0] * 80)
        a = po.AcumuladorRr()
        salida = [a.agregar(i * 0.01, float(v)) for i, v in enumerate(x[:6000])]
        res = [s for s in salida if s]
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0][0], 0)
        self.assertGreater(len(res[0][1]), 50)

    def test_acumulador_descarta_si_la_tasa_no_es_100_hz(self):
        x, _ = ecg_sintetico([800.0] * 80)
        a = po.AcumuladorRr()
        salida = [a.agregar(i * 0.02, float(v)) for i, v in enumerate(x[:6000])]       # llegan a 50 Hz
        self.assertFalse(any(salida))
        self.assertIsNone(a.agregar(0.0, float("nan")))


class TestRrEnRepositorioYVm(Base):

    def test_repositorio_guarda_y_filtra_por_rango(self):
        self.repo.guardar_rr(1000, [800.0, 810.5])
        self.repo.guardar_rr(5000, [700.0])
        self.repo.guardar_rr(6000, [])
        self.assertEqual(self.repo.rr_rango(0, 2000), [[800.0, 810.5]])
        self.assertEqual(len(self.repo.rr_rango(0, 10_000)), 2)
        self.assertEqual(self.repo.rr_rango(2000, 4000), [])

    def test_el_vm_guarda_los_rr_con_la_banda_conectada(self):
        x, _ = ecg_sintetico([800.0] * 80)
        self.estado()
        for v in x[:6000]:
            self.reloj.t += 0.01
            self.vm._acumular_rr(float(v))
        ventanas = self.repo.rr_rango(0, 2 ** 31)
        self.assertEqual(len(ventanas), 1)
        p = self.vm.poincare(0, 2 ** 31)
        self.assertGreater(p.n, 50)

    def test_sin_conexion_no_se_guarda_nada(self):
        x, _ = ecg_sintetico([800.0] * 80)
        self.vm._emitir_nuevo_estado(conexionEstado=ConexionEstado.DESCONECTADO)
        for v in x[:6000]:
            self.reloj.t += 0.01
            self.vm._acumular_rr(float(v))
        self.assertEqual(self.repo.rr_rango(0, 2 ** 31), [])

    def test_borrar_todo_elimina_los_rr(self):
        self.repo.guardar_rr(1000, [800.0, 810.0])
        self.repo.borrar_todo()
        self.assertEqual(self.repo.rr_rango(0, 2 ** 31), [])


class TestPanelPoincare(unittest.TestCase):

    def test_dibuja_puntos_ejes_y_atipicos(self):
        p = po.calcular_poincare([[800.0, 810.0, 790.0, 805.0] * 6 + [1400.0] + [800.0, 810.0, 790.0, 805.0] * 3])
        w = PanelPoincare()
        w.mostrar(p)
        self.assertEqual(len(w.puntos.getData()[0]), p.n)
        self.assertEqual(len(w.atipicos.getData()[0]), 2)
        self.assertEqual(len(w.eje_sd1.getData()[0]), 2)
        self.assertEqual(len(w.eje_sd2.getData()[0]), 2)
        self.assertIn("SD1", w.lbl.text())
        self.assertIn("SD2", w.lbl.text())

    def test_sin_datos(self):
        w = PanelPoincare()
        w.mostrar(None)
        self.assertIn("Sin intervalos", w.lbl.text())
        w.mostrar(po.calcular_poincare([]))
        self.assertEqual(len(w.puntos.getData()[0] if w.puntos.getData()[0] is not None else []), 0)

    def test_pestana_poincare_en_actividades(self):
        v = MainWindow(self.vm if hasattr(self, "vm") else VitaBandViewModel(MagicMock()), "Ana")
        pestanas = v.vista_actividades.pestanas_grafica
        self.assertIn("Poincaré", [pestanas.tabText(i) for i in range(pestanas.count())])
        v.close()


if __name__ == "__main__":
    unittest.main()
