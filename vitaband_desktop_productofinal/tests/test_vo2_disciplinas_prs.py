"""VO2máx (Uth) y edad cardiovascular; disciplinas, récords personales (PRs) y aviso del comparador."""

import os
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from domain.modelos import Medicion
from services import calculos_fisiologicos as calc
from services import disciplinas as dc
from services import vo2max as vo
from services.repositorio_historial import RepositorioHistorial
from ui.main_window import MainWindow
from ui.panel_vo2 import PanelVo2
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])
HOY = date(2026, 11, 18)
AHORA = int(datetime(2026, 11, 18, 12).timestamp())


class Reloj:
    t = float(AHORA)

    def __call__(self):
        return self.t


def ts(dia, h=8):
    return int(datetime(dia.year, dia.month, dia.day, h).timestamp())


def med(bpm, nivel=0, t=0):
    return Medicion(0, "u", t, bpm, 15.0, None, nivel, "PERIODICO", None)


class TestUth(unittest.TestCase):

    def test_formula(self):
        self.assertAlmostEqual(vo.vo2max_uth(190, 60), 15.3 * 190 / 60)
        self.assertAlmostEqual(vo.vo2max_uth(180, 45), 61.2)

    def test_entradas_invalidas(self):
        for fm, fr in ((None, 60), (190, None), (190, 0), (0, 60), (60, 60), (50, 60), (190, -5)):
            self.assertIsNone(vo.vo2max_uth(fm, fr), (fm, fr))

    def test_tanaka(self):
        self.assertAlmostEqual(vo.fc_max_tanaka(30), 187.0)


class TestClasificacionYEdadCv(unittest.TestCase):

    def test_categorias_por_edad_y_sexo(self):
        ref = vo.vo2_referencia(30, "Hombre")                         # 43,5
        self.assertAlmostEqual(ref, 43.5)
        self.assertEqual([vo.clasificar(ref * r, 30, "Hombre") for r in (0.6, 0.8, 1.0, 1.2, 1.4)],
                         ["Muy baja", "Baja", "Media", "Buena", "Excelente"])
        # el mismo VO2 es peor para un hombre joven que para una mujer mayor
        self.assertEqual(vo.clasificar(35, 25, "Hombre"), "Baja")
        self.assertEqual(vo.clasificar(35, 60, "Mujer"), "Excelente")
        self.assertIsNone(vo.clasificar(40, 30, "Otro"))

    def test_edad_cardiovascular(self):
        self.assertEqual(vo.edad_cardiovascular(48.0, "Hombre"), 20)
        self.assertEqual(vo.edad_cardiovascular(43.5, "Hombre"), 30)
        self.assertEqual(vo.edad_cardiovascular(40.0, "Mujer"), 20)
        self.assertEqual(vo.edad_cardiovascular(100, "Hombre"), 18)           # acotada
        self.assertEqual(vo.edad_cardiovascular(5, "Mujer"), 90)
        self.assertIsNone(vo.edad_cardiovascular(40, "Otro"))

    def test_mas_forma_fisica_menos_edad(self):
        self.assertLess(vo.edad_cardiovascular(55, "Hombre"), vo.edad_cardiovascular(35, "Hombre"))


class TestEstimar(unittest.TestCase):
    perfil = calc.PerfilFisiologico(30, "Hombre", 70.0)

    def test_fc_reposo_percentil_5_solo_en_reposo(self):
        ms = [med(60 + i % 5) for i in range(30)] + [med(150, nivel=2) for _ in range(30)]
        self.assertAlmostEqual(vo.fc_reposo(ms), 60.0, delta=1.0)
        self.assertIsNone(vo.fc_reposo(ms[:10]))                               # pocas muestras
        self.assertIsNone(vo.fc_reposo([med(150, nivel=2)] * 40))

    def test_fc_max_observada_ignora_artefactos(self):
        ms = [med(150 + i % 30, nivel=2) for i in range(60)] + [med(250, nivel=2)]
        self.assertLessEqual(vo.fc_max_observada(ms), 220)
        self.assertGreater(vo.fc_max_observada(ms), 170)
        self.assertIsNone(vo.fc_max_observada([med(180)] * 5))

    def test_con_fc_max_observada(self):
        e = vo.estimar(60.0, 190.0, self.perfil)
        self.assertAlmostEqual(e.vo2, 48.45)
        self.assertTrue(e.fc_max_observada)
        self.assertEqual(e.categoria, "Buena")
        self.assertEqual(e.edad_cv, vo.edad_cardiovascular(e.vo2, "Hombre"))
        self.assertLess(e.edad_cv, 30)
        self.assertIn("VO2máx ≈ 48.5", e.texto())
        self.assertIn("edad cardiovascular", e.texto())

    def test_sin_fc_max_usa_tanaka(self):
        e = vo.estimar(60.0, None, self.perfil)
        self.assertFalse(e.fc_max_observada)
        self.assertAlmostEqual(e.fc_max, 187.0)
        self.assertIn("Tanaka", e.texto())

    def test_sin_perfil_solo_vo2_sin_clasificar(self):
        e = vo.estimar(60.0, 190.0, calc.PerfilFisiologico())
        self.assertIsNotNone(e.vo2)
        self.assertIsNone(e.categoria)
        self.assertIsNone(e.edad_cv)
        self.assertIsNone(vo.estimar(60.0, None, calc.PerfilFisiologico()))     # sin FCmáx ni edad
        self.assertIsNone(vo.estimar(None, 190.0, self.perfil))


class Base(unittest.TestCase):
    def setUp(self):
        self.reloj = Reloj()
        self.repo = RepositorioHistorial(":memory:", usuario_id=1)
        self.vm = VitaBandViewModel(MagicMock(), repositorio=self.repo, reloj=self.reloj)
        self.v = MainWindow(self.vm, "Ana")

    def tearDown(self):
        self.v.close()
        self.vm.cerrar()

    def reposo(self, dia, bpm, n=30, uid="r"):
        for i in range(n):
            self.repo.guardar_medicion(bpm + (i % 3), datetime.fromtimestamp(ts(dia) + i * 60),
                                       uid=f"{uid}{dia}{i}", rpm=14, nivel_actividad=0)

    def esfuerzo(self, dia, bpm=185, n=30):
        for i in range(n):
            self.repo.guardar_medicion(bpm, datetime.fromtimestamp(ts(dia, 18) + i * 10),
                                       uid=f"e{dia}{i}", rpm=30, nivel_actividad=2)

    def sesion(self, dia, minutos=40, bpm=140, rpm=18.0, h=8):
        ini = ts(dia, h)
        aid = self.repo.guardar_actividad(f"a{ini}", ini, ini + minutos * 60, "carrera")
        for i in range(minutos * 6):
            self.repo.guardar_medicion(bpm, datetime.fromtimestamp(ini + i * 10), uid=f"{ini}-{i}", rpm=rpm,
                                       etiqueta="ACTIVIDAD", actividad_id=aid, nivel_actividad=1)
        return aid


class TestEvolucionVo2(Base):

    def setUp(self):
        super().setUp()
        self.vm.guardar_perfil(calc.PerfilFisiologico(30, "Hombre", 70.0))
        self.reposo(date(2026, 10, 10), 66)
        self.reposo(date(2026, 11, 10), 56)
        self.esfuerzo(date(2026, 10, 12))

    def test_evolucion_mensual_ordenada_y_mejora_con_menor_reposo(self):
        ev = self.vm.evolucion_vo2()
        self.assertEqual([m for m, _ in ev], ["2026-10", "2026-11"])
        self.assertGreater(ev[1][1].vo2, ev[0][1].vo2)
        self.assertLess(ev[1][1].edad_cv, ev[0][1].edad_cv)

    def test_estimacion_actual_y_meses_sin_datos_se_omiten(self):
        e = self.vm.estimacion_vo2()
        self.assertIsNotNone(e)
        self.assertAlmostEqual(e.fc_reposo, 56.0, delta=1.5)
        self.assertTrue(e.fc_max_observada)
        self.assertEqual(len(self.vm.evolucion_vo2(meses=1)), 1)

    def test_sin_datos_en_reposo(self):
        vm = VitaBandViewModel(MagicMock(), repositorio=RepositorioHistorial(":memory:", usuario_id=2),
                               reloj=Reloj())
        self.assertIsNone(vm.estimacion_vo2())
        self.assertEqual(vm.evolucion_vo2(), [])
        vm.cerrar()
        self.assertIsNone(VitaBandViewModel(MagicMock()).estimacion_vo2())

    def test_panel_en_historial(self):
        h = self.v.vista_historial
        h.actualizar()
        self.assertIn("VO2máx ≈", h.panel_vo2.lbl.text())
        self.assertIn("2026-10", h.panel_vo2.lbl_evolucion.text())
        self.assertIn("2026-11", h.panel_vo2.lbl_evolucion.text())
        self.assertFalse(h.panel_vo2.grafica.isHidden())

    def test_panel_sin_datos_dice_que_falta(self):
        p = PanelVo2()
        p.mostrar(None, [])
        self.assertIn("N/D", p.lbl.text())
        self.assertTrue(p.grafica.isHidden())


class TestDisciplinasRepoYVm(Base):

    def test_etiquetar_reetiquetar_y_quitar(self):
        aid = self.sesion(HOY - timedelta(days=1))
        self.assertEqual(self.repo.disciplinas(), {})
        self.repo.guardar_disciplina(aid, "Carrera")
        self.repo.guardar_disciplina(aid, "Fuerza")
        self.assertEqual(self.repo.disciplinas(), {aid: "Fuerza"})
        self.repo.guardar_disciplina(aid, None)
        self.assertEqual(self.repo.disciplinas(), {})

    def test_opciones_y_validacion(self):
        self.assertEqual(dc.DISCIPLINAS, ("Carrera", "Rodillo/Ciclismo", "Fuerza", "Caminata", "Otra"))
        aid = self.sesion(HOY - timedelta(days=1))
        avisos = []
        self.vm.historial_actualizado.connect(lambda: avisos.append(1))
        self.vm.guardar_disciplina(aid, "Rodillo/Ciclismo")
        self.assertTrue(avisos)
        self.assertEqual(self.vm.disciplinas()[aid], "Rodillo/Ciclismo")
        with self.assertRaises(ValueError):
            self.vm.guardar_disciplina(aid, "   ")                       # vacía: no válida
        self.vm.guardar_disciplina(aid, "Natación")                     # personalizada: ahora se admite
        self.assertEqual(self.vm.disciplinas()[aid], "Natación")

    def test_borrar_la_actividad_borra_su_etiqueta(self):
        aid = self.sesion(HOY - timedelta(days=1))
        self.repo.guardar_disciplina(aid, "Carrera")
        self.repo.borrar_actividad(aid)
        self.assertEqual(self.repo.disciplinas(), {})


class TestRecordsPersonales(unittest.TestCase):

    def r(self, i, disciplina, minutos, bpm, z2=0.0):
        return dc.ResumenSesion(i, disciplina, minutos, bpm, z2)

    def test_menor_bpm_a_esfuerzo_equivalente(self):
        prs = dc.records_personales([
            self.r(1, "Carrera", 40, 150), self.r(2, "Carrera", 45, 140), self.r(3, "Carrera", 50, 155)])
        self.assertEqual(list(prs), [2])
        self.assertIn("menor BPM medio", prs[2][0])
        self.assertIn("Carrera", prs[2][0])

    def test_no_se_comparan_franjas_de_duracion_distintas(self):
        prs = dc.records_personales([self.r(1, "Carrera", 15, 120), self.r(2, "Carrera", 90, 170)])
        self.assertEqual(prs, {})
        self.assertEqual([dc.franja(m) for m in (9, 10, 29.9, 30, 59, 60, 200)],
                         [None, "10–30 min", "10–30 min", "30–60 min", "30–60 min", "más de 60 min", "más de 60 min"])

    def test_no_se_comparan_disciplinas_distintas(self):
        prs = dc.records_personales([self.r(1, "Carrera", 40, 150), self.r(2, "Rodillo/Ciclismo", 40, 130)])
        self.assertEqual(prs, {})

    def test_una_sola_sesion_o_sin_disciplina_no_es_record(self):
        self.assertEqual(dc.records_personales([self.r(1, "Carrera", 40, 150)]), {})
        self.assertEqual(dc.records_personales([self.r(1, None, 40, 150), self.r(2, None, 40, 140)]), {})

    def test_sesiones_muy_cortas_no_optan(self):
        self.assertEqual(dc.records_personales([self.r(1, "Caminata", 5, 100), self.r(2, "Caminata", 6, 90)]), {})

    def test_mayor_tiempo_en_z2(self):
        prs = dc.records_personales([
            self.r(1, "Caminata", 20, 120, z2=900), self.r(2, "Caminata", 60, 125, z2=2400),
            self.r(3, "Caminata", 45, 128, z2=1800), self.r(4, "Fuerza", 60, 110, z2=3000)])
        self.assertTrue(any("Z2" in t for t in prs[2]))
        self.assertNotIn(4, prs)                                              # único de su disciplina
        self.assertNotIn(1, prs)

    def test_z2_exige_al_menos_5_minutos(self):
        prs = dc.records_personales([self.r(1, "Otra", 30, 120, z2=100), self.r(2, "Otra", 30, 120, z2=200)])
        self.assertFalse(any("Z2" in t for v in prs.values() for t in v))

    def test_un_empate_no_es_record(self):
        self.assertEqual(dc.records_personales([self.r(1, "Carrera", 40, 140), self.r(2, "Carrera", 40, 140)]), {})
        prs = dc.records_personales([self.r(1, "Otra", 40, 140, 900), self.r(2, "Otra", 40, 150, 900)])
        self.assertEqual(list(prs), [1])
        self.assertFalse(any("Z2" in t for t in prs[1]))

    def test_un_mismo_record_puede_ser_de_ambos_tipos(self):
        prs = dc.records_personales([self.r(1, "Carrera", 40, 150, 600), self.r(2, "Carrera", 40, 140, 1200)])
        self.assertEqual(len(prs[2]), 2)

    def test_aviso_de_comparacion(self):
        self.assertIn("distinta disciplina", dc.aviso_comparacion("Carrera", "Fuerza"))
        self.assertIsNone(dc.aviso_comparacion("Carrera", "Carrera"))
        self.assertIsNone(dc.aviso_comparacion("Carrera", None))
        self.assertIsNone(dc.aviso_comparacion(None, None))


class TestDisciplinasEnPantalla(Base):

    def setUp(self):
        super().setUp()
        d = lambda n: HOY - timedelta(days=n)
        self.a1 = self.sesion(d(5), 40, bpm=125)         # Z2 con FCmáx 190
        self.a2 = self.sesion(d(4), 40, bpm=118)         # mismo esfuerzo con menos pulso → PR
        self.a3 = self.sesion(d(3), 40, bpm=130)
        for aid, dn in ((self.a1, "Carrera"), (self.a2, "Carrera"), (self.a3, "Rodillo/Ciclismo")):
            self.repo.guardar_disciplina(aid, dn)
        self.act = self.v.vista_actividades
        self.act.selector.establecer_rango(d(30), HOY)
        self.act.actualizar()

    def filas(self):
        return [self.act.tabla.item(i, 1).text() for i in range(self.act.tabla.rowCount())]

    def test_prs_calculados_con_datos_reales(self):
        prs = self.vm.records_personales()
        self.assertEqual(set(prs), {self.a2})
        self.assertTrue(any("menor BPM" in t for t in prs[self.a2]))

    def test_la_tabla_muestra_disciplina_y_trofeo(self):
        filas = self.filas()
        self.assertEqual(sum("🏆" in f for f in filas), 1)
        self.assertTrue(any("Rodillo/Ciclismo" in f for f in filas))
        self.assertEqual(sum("Carrera" in f for f in filas), 2)

    def test_filtro_por_disciplina(self):
        c = self.act.combo_filtro_disciplina
        c.setCurrentIndex(c.findData("Carrera"))
        self.assertEqual(self.act.tabla.rowCount(), 2)
        c.setCurrentIndex(c.findData("Rodillo/Ciclismo"))
        self.assertEqual(self.act.tabla.rowCount(), 1)
        c.setCurrentIndex(c.findData("Fuerza"))
        self.assertEqual(self.act.tabla.rowCount(), 0)
        c.setCurrentIndex(c.findData(""))                      # sin disciplina
        self.assertEqual(self.act.tabla.rowCount(), 0)
        c.setCurrentIndex(0)
        self.assertEqual(self.act.tabla.rowCount(), 3)

    def test_etiquetar_desde_el_detalle(self):
        sin = self.sesion(HOY - timedelta(days=1), 30)
        self.act.actualizar()
        fila = next(i for i in range(self.act.tabla.rowCount())
                    if self.act.tabla.item(i, 0).data(0x0100) == sin)
        self.act.tabla.selectRow(fila)
        self.assertEqual(self.act.combo_disciplina.currentData(), "Otra")       # IA local: auto-etiqueta al abrir
        self.act.combo_disciplina.setCurrentIndex(self.act.combo_disciplina.findData("Caminata"))
        self.act.btn_disciplina.click()
        self.assertEqual(self.repo.disciplinas()[sin], "Caminata")
        self.assertIn("Caminata", self.filas()[fila])

    def test_detalle_muestra_el_record(self):
        fila = next(i for i in range(self.act.tabla.rowCount())
                    if self.act.tabla.item(i, 0).data(0x0100) == self.a2)
        self.act.tabla.selectRow(fila)
        self.assertIn("🏆", self.act.lbl_prs.text())
        self.assertEqual(self.act.combo_disciplina.currentData(), "Carrera")

    def comparar(self, i, j):
        self.act.chk_comparar.setChecked(True)
        self.act.tabla.clearSelection()
        self.act._seleccionar([i, j])
        self.act._on_seleccion()

    def test_aviso_en_antes_vs_ahora_con_disciplinas_distintas(self):
        self.comparar(self.a1, self.a3)
        self.assertFalse(self.act.comparador.lbl_aviso.isHidden())
        self.assertIn("distinta disciplina", self.act.comparador.lbl_aviso.text())

    def test_sin_aviso_con_la_misma_disciplina(self):
        self.comparar(self.a1, self.a2)
        self.assertTrue(self.act.comparador.lbl_aviso.isHidden())
        self.assertFalse(self.act.comparador.lbl_resumen.isHidden())

    def test_el_aviso_desaparece_al_dejar_de_comparar_dos(self):
        self.comparar(self.a1, self.a3)
        self.act.tabla.clearSelection()
        self.act._seleccionar([self.a1])
        self.act._on_seleccion()
        self.assertTrue(self.act.comparador.lbl_aviso.isHidden())

    def test_historial_filtra_records_por_disciplina(self):
        h = self.v.vista_historial
        h.actualizar()
        self.assertIn("🏆", h.lbl_records.text())
        h.combo_disciplina.setCurrentIndex(h.combo_disciplina.findData("Rodillo/Ciclismo"))
        self.assertNotIn("🏆", h.lbl_records.text())
        self.assertIn("Sin récords", h.lbl_records.text())
        h.combo_disciplina.setCurrentIndex(h.combo_disciplina.findData("Carrera"))
        self.assertIn("🏆", h.lbl_records.text())


if __name__ == "__main__":
    unittest.main()
