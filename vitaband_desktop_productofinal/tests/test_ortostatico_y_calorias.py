"""Test ortostático de 3 min y gasto calórico (Keytel)."""

import os
import sys
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from domain.modelos import Medicion
from domain.ui_state import VitaBandUiState
from services import calculos_fisiologicos as calc
from services.repositorio_historial import RepositorioHistorial
from tests.test_hrv_rmssd import ecg_sintetico
from ui.dialogo_ortostatico import DialogoOrtostatico
from ui.dialogo_perfil import DialogoPerfil
from ui.main_window import MainWindow
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])
DIA = date.today() - timedelta(days=1)
T0 = int(datetime(DIA.year, DIA.month, DIA.day, 8, 0).timestamp())


def serie_bpm(basal=60, pico=90, estable=70):
    """(t, bpm) cada segundo durante 3 min con la forma típica de un test ortostático."""
    return [(t, basal if t < 120 else pico if t < 135 else estable) for t in range(180)]


class TestFases(unittest.TestCase):

    def test_limites(self):
        self.assertEqual([calc.fase_ortostatica(t) for t in (0, 119.9, 120, 179.9, 180, 400)], [0, 0, 1, 1, 2, 2])


class TestEvaluacion(unittest.TestCase):

    def test_delta_y_valoracion(self):
        r = calc.evaluar_ortostatico(serie_bpm(60, 90, 70), [])
        self.assertAlmostEqual(r.fc_basal, 60)
        self.assertEqual(r.fc_pico, 90)
        self.assertEqual(r.delta_fc, 30)
        self.assertAlmostEqual(r.fc_estable, 70)
        self.assertIsNone(r.rmssd_basal)
        self.assertIn("marcada", r.valoracion)
        self.assertIn("no es un diagnóstico", r.valoracion)

    def test_normal_y_debil(self):
        self.assertIn("normal", calc.evaluar_ortostatico(serie_bpm(60, 75, 68), []).valoracion)
        self.assertIn("débil", calc.evaluar_ortostatico(serie_bpm(60, 65, 62), []).valoracion)

    def test_bordes_de_la_valoracion(self):
        self.assertIn("marcada", calc.valorar_ortostatico(30.0, None))
        self.assertIn("normal", calc.valorar_ortostatico(29.9, None))
        self.assertIn("normal", calc.valorar_ortostatico(10.0, None))
        self.assertIn("débil", calc.valorar_ortostatico(9.9, None))

    def test_basal_es_el_ultimo_minuto_de_la_fase_1(self):
        bpm = [(t, 100 if t < 60 else 60) for t in range(120)] + [(t, 80) for t in range(120, 150)]
        self.assertAlmostEqual(calc.evaluar_ortostatico(bpm, []).fc_basal, 60)

    def test_sin_datos_suficientes(self):
        self.assertIsNone(calc.evaluar_ortostatico([], []))
        self.assertIsNone(calc.evaluar_ortostatico([(t, 60) for t in range(120)], []))        # nunca se puso de pie
        self.assertIsNone(calc.evaluar_ortostatico([(t, 80) for t in range(120, 180)], []))   # sin basal
        self.assertIsNone(calc.evaluar_ortostatico([(t, 0.0) for t in range(180)], []))       # FC inválida

    def test_rmssd_con_ecg_sintetico(self):
        rr_reposo = [80, 76, 84, 78, 82]                 # R-R variables en reposo
        rr_pie = [60, 61, 60, 59]                        # de pie casi sin variabilidad
        ecg = [(60 + i / 100, v) for i, v in enumerate(ecg_sintetico(rr_reposo, dur_s=60))]
        ecg += [(150 + i / 100, v) for i, v in enumerate(ecg_sintetico(rr_pie, dur_s=30, semilla=2))]
        r = calc.evaluar_ortostatico(serie_bpm(), ecg)
        self.assertIsNotNone(r.rmssd_basal)
        self.assertIsNotNone(r.rmssd_pie)
        self.assertGreater(r.rmssd_basal, r.rmssd_pie)
        self.assertIn("HRV basal", r.valoracion)


class Reloj:
    t = 5_000.0

    def __call__(self):
        return self.t


class TestDialogo(unittest.TestCase):

    def setUp(self):
        self.repo = RepositorioHistorial(":memory:", usuario_id=1)
        self.vm = VitaBandViewModel(MagicMock(), repositorio=self.repo)
        self.reloj = Reloj()
        self.reloj.t = 5_000.0
        self.d = DialogoOrtostatico(self.vm, reloj=self.reloj)

    def tearDown(self):
        self.d.close()
        self.vm.cerrar()

    def correr(self, desde, hasta, bpm=lambda t: 60 if t < 120 else 90 if t < 135 else 70):
        for t in range(desde, hasta):
            self.reloj.t = 5_000.0 + t
            if bpm(t) is not None:
                self.vm.state_changed.emit(replace(VitaBandUiState.inicial(), bpmTexto=f"{bpm(t)}.0 BPM"))
            self.d.tick()

    def test_flujo_completo_con_avisos_y_guardado(self):
        with patch("ui.dialogo_ortostatico.QApplication.beep") as beep:
            self.d.iniciar()
            self.assertIn("Fase 1", self.d.lbl_fase.text())
            self.correr(0, 119)
            self.assertIn("Fase 1", self.d.lbl_fase.text())
            self.assertEqual(beep.call_count, 0)
            self.correr(119, 121)
            self.assertIn("Fase 2", self.d.lbl_fase.text())
            self.assertEqual(beep.call_count, 1)                       # cambio de fase a los 2:00
            self.correr(121, 181)
            self.assertEqual(beep.call_count, 2)                       # fin a los 3:00
        self.assertFalse(self.d.en_curso)
        self.assertEqual(self.d.lbl_fase.text(), "Test terminado")
        self.assertIsNotNone(self.d.resultado)
        self.assertEqual(self.d.resultado.delta_fc, 30)
        self.assertIn("ΔFC +30", self.d.lbl_resultado.text())
        self.assertIn("marcada", self.d.lbl_resultado.text())
        (fila,) = self.repo.tests_ortostaticos()
        self.assertEqual((fila["fc_basal"], fila["fc_pico"], fila["delta_fc"]), (60.0, 90.0, 30.0))
        self.assertIn("marcada", fila["valoracion"])
        self.assertTrue(self.d.btn_iniciar.isEnabled())

    def test_temporizador_en_vivo(self):
        self.d.iniciar()
        self.reloj.t = 5_075.0
        self.d.tick()
        self.assertEqual(self.d.lbl_tiempo.text(), "1:15 / 3:00")

    def test_sin_fc_no_se_guarda_y_avisa(self):
        with patch("ui.dialogo_ortostatico.QApplication.beep"):
            self.d.iniciar()
            self.correr(0, 181, bpm=lambda t: None)
        self.assertIsNone(self.d.resultado)
        self.assertEqual(self.repo.tests_ortostaticos(), [])
        self.assertIn("sin datos suficientes", self.d.lbl_fase.text())

    def test_cerrar_a_mitad_detiene_la_captura_y_no_guarda(self):
        self.d.iniciar()
        self.correr(0, 50)
        self.assertIsNotNone(self.vm._captura_ecg)
        self.d.close()
        self.assertIsNone(self.vm._captura_ecg)
        self.assertEqual(self.repo.tests_ortostaticos(), [])

    def test_no_se_puede_iniciar_dos_veces(self):
        self.d.iniciar()
        self.reloj.t = 5_030.0
        self.d.iniciar()                                              # ignorado: no reinicia el cronómetro
        self.d.tick()
        self.assertEqual(self.d.lbl_tiempo.text(), "0:30 / 3:00")

    def test_boton_en_tiempo_real(self):
        v = MainWindow(self.vm, "Ana")
        self.assertEqual(v.btn_ortostatico.text(), "Test Ortostático (3 min)")
        v.btn_ortostatico.click()
        self.assertTrue(v.dialogo_ortostatico.isVisible())
        v.dialogo_ortostatico.close(); v.close()


class TestKeytel(unittest.TestCase):

    def test_hombre_y_mujer(self):
        h = calc.PerfilFisiologico(30, "Hombre", 70.0)
        m = calc.PerfilFisiologico(30, "Mujer", 60.0)
        self.assertAlmostEqual(calc.kcal_keytel(140, 10, h), 127.14, places=1)
        self.assertAlmostEqual(calc.kcal_keytel(140, 10, m), 88.07, places=1)

    def test_peso_de_referencia_si_no_hay_peso(self):
        self.assertAlmostEqual(calc.kcal_keytel(140, 10, calc.PerfilFisiologico(30, "Hombre", None)),
                               calc.kcal_keytel(140, 10, calc.PerfilFisiologico(30, "Hombre", 70.0)))
        self.assertAlmostEqual(calc.kcal_keytel(140, 10, calc.PerfilFisiologico(30, "Mujer", 0)),
                               calc.kcal_keytel(140, 10, calc.PerfilFisiologico(30, "Mujer", 60.0)))

    def test_nunca_negativo(self):
        self.assertEqual(calc.kcal_keytel(40, 30, calc.PerfilFisiologico(30, "Mujer", 60.0)), 0.0)
        self.assertEqual(calc.kcal_keytel(40, 30, calc.PerfilFisiologico(30, "Hombre", 70.0)), 0.0)

    def test_sin_perfil_completo_o_datos_no_hay_valor(self):
        for p in (None, calc.PerfilFisiologico(), calc.PerfilFisiologico(30, None, 70), calc.PerfilFisiologico(None, "Hombre", 70),
                  calc.PerfilFisiologico(30, "Otro", 70)):
            self.assertIsNone(calc.kcal_keytel(140, 10, p))
        h = calc.PerfilFisiologico(30, "Hombre")
        self.assertIsNone(calc.kcal_keytel(None, 10, h))
        self.assertIsNone(calc.kcal_keytel(float("nan"), 10, h))
        self.assertIsNone(calc.kcal_keytel(140, 0, h))

    def test_mas_pulso_o_mas_tiempo_mas_kcal(self):
        h = calc.PerfilFisiologico(30, "Hombre", 70.0)
        self.assertGreater(calc.kcal_keytel(150, 10, h), calc.kcal_keytel(130, 10, h))
        self.assertAlmostEqual(calc.kcal_keytel(140, 20, h), 2 * calc.kcal_keytel(140, 10, h))

    def test_kcal_de_actividad_usa_la_duracion_activa(self):
        h = calc.PerfilFisiologico(30, "Hombre", 70.0)
        ms = [Medicion(t, f"m{t}", T0 + t, 140.0, 18.0, None, 1, "ACTIVIDAD", 1) for t in range(0, 1800, 10)]
        self.assertAlmostEqual(calc.kcal_actividad(ms, h), 30 * 12.7144, places=0)
        con_hueco = ms[:90] + [Medicion(900 + t, f"h{t}", T0 + 7200 + t * 10, 140.0, 18.0, None, 1, "ACTIVIDAD", 1)
                               for t in range(90)]
        self.assertAlmostEqual(calc.kcal_actividad(con_hueco, h), 30 * 12.7144, delta=15)        # el hueco de 2 h no cuenta
        self.assertIsNone(calc.kcal_actividad([], h))
        self.assertIsNone(calc.kcal_actividad(ms, None))


class TestPerfilYUi(unittest.TestCase):

    def setUp(self):
        self.repo = RepositorioHistorial(":memory:", usuario_id=1)
        aid = self.repo.guardar_actividad("a1", T0, T0 + 1800, "carrera")
        for t in range(0, 1800, 10):
            self.repo.guardar_medicion(140, datetime.fromtimestamp(T0 + t), uid=f"u{t}", rpm=18,
                                       etiqueta="ACTIVIDAD", actividad_id=aid, nivel_actividad=1)
        self.vm = VitaBandViewModel(MagicMock(), repositorio=self.repo)
        self.v = MainWindow(self.vm, "Ana")
        self.a = self.v.vista_actividades
        self.a.selector.establecer_rango(DIA, DIA)
        self.a.actualizar()

    def tearDown(self):
        self.v.close()
        self.vm.cerrar()

    def test_ficha_sin_perfil_dice_n_d(self):
        self.assertIn("Keytel): N/D", self.a.lbl_estadisticas.text())
        self.v.vista_historial.actualizar()
        self.assertIn("N/D", self.v.vista_historial.lbl_kcal.text())

    def test_perfil_se_guarda_y_la_ficha_muestra_kcal(self):
        señales = []
        self.vm.historial_actualizado.connect(lambda: señales.append(1))
        self.vm.guardar_perfil(calc.PerfilFisiologico(30, "Hombre", 70.0))
        self.assertTrue(señales)
        self.assertEqual(self.vm.perfil(), calc.PerfilFisiologico(30, "Hombre", 70.0, 150))
        self.a.actualizar()
        self.assertIn("Keytel): 381 kcal", self.a.lbl_estadisticas.text())

    def test_acumulado_semanal_en_historial(self):
        ayer_en_semana = self.vm.constancia()
        self.assertEqual(ayer_en_semana["kcal_semana"], 0.0)
        self.vm.guardar_perfil(calc.PerfilFisiologico(30, "Mujer", 60.0))
        c = self.vm.constancia()
        self.assertAlmostEqual(c["kcal_semana"], 30 * 8.8069, delta=1)
        self.v.vista_historial.actualizar()
        self.assertIn("Calorías esta semana (7 días): 264", self.v.vista_historial.lbl_kcal.text())

    def test_boton_y_dialogo_de_perfil(self):
        d = DialogoPerfil(calc.PerfilFisiologico())
        self.assertEqual(d.perfil(), calc.PerfilFisiologico(None, None, None, 150))
        d.spin_edad.setValue(41); d.combo_sexo.setCurrentText("Mujer"); d.spin_peso.setValue(58.5)
        self.assertEqual(d.perfil(), calc.PerfilFisiologico(41, "Mujer", 58.5, 150))
        with patch("ui.main_window.DialogoPerfil") as Dlg:
            Dlg.return_value.exec.return_value = True
            Dlg.return_value.perfil.return_value = calc.PerfilFisiologico(35, "Hombre", 80.0)
            self.v.btn_perfil.click()
        self.assertEqual(self.vm.perfil().edad, 35)

    def test_borrar_todo_limpia_el_perfil(self):
        self.vm.guardar_perfil(calc.PerfilFisiologico(30, "Hombre", 70.0))
        self.repo.borrar_todo()
        self.assertEqual(self.vm.perfil(), calc.PerfilFisiologico())


if __name__ == "__main__":
    unittest.main()
