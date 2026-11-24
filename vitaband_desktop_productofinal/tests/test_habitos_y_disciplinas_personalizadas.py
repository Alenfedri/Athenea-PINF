"""Hábitos libres (SQLite + Coach IA) y disciplinas deportivas personalizadas en Actividades."""
import os
import unittest
from datetime import date, datetime
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from domain import marcadores_contexto as mc
from services import coach_ia as c
from services import disciplinas as disc
from services.repositorio_historial import RepositorioHistorial
from ui.vista_actividades import VistaActividades
from ui.vista_historial import VistaHistorialPeriodico as VistaHistorial
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])
AHORA = int(__import__("time").time())


class Reloj:
    def __call__(self):
        return float(AHORA)


def _vm():
    import tempfile
    repo = RepositorioHistorial(os.path.join(tempfile.mkdtemp(), "t.db"), usuario_id=1)
    return VitaBandViewModel(MagicMock(), repositorio=repo, reloj=Reloj()), repo


class TestHabitos(unittest.TestCase):
    def test_normalizar(self):
        self.assertEqual(mc.normalizar_etiqueta("  Siesta \n 30   min "), "Siesta 30 min")
        self.assertEqual(len(mc.normalizar_etiqueta("x" * 100)), 40)
        with self.assertRaises(ValueError):
            mc.normalizar_etiqueta("  \t ")

    def test_guardado_y_lectura_en_sqlite_junto_a_los_predefinidos(self):
        vm, repo = _vm()
        vm.poner_marcador(AHORA - 3600, "Café")                            # predefinido sigue igual
        self.assertEqual(vm.poner_habito("Siesta 30 min"), "Siesta 30 min")
        self.assertEqual(vm.poner_habito("Ayuno"), "Ayuno")
        etiquetas = [e for _, e in repo.marcadores_rango(AHORA - 7200, AHORA + 60)]
        self.assertEqual(sorted(etiquetas), ["Ayuno", "Café", "Siesta 30 min"])
        self.assertEqual(vm.habitos_recientes()[:2], ["Ayuno", "Siesta 30 min"])
        with self.assertRaises(ValueError):
            vm.poner_habito("   ")

    def test_la_interfaz_anade_con_boton_y_enter(self):
        vm, _ = _vm()
        h = VistaHistorial(vm)
        self.assertIn("Otro hábito", h.edit_habito.placeholderText())
        self.assertEqual(h.edit_habito.maxLength(), 40)
        h.edit_habito.setText("Fisioterapia")
        h.btn_anadir_habito.click()
        self.assertEqual(h.edit_habito.text(), "")
        self.assertIn("Fisioterapia", h.lbl_habitos.text())
        h.edit_habito.setText("Altitud")
        h.edit_habito.returnPressed.emit()
        self.assertIn("Altitud", h.lbl_habitos.text())


def _ctx(etiquetas, habitos=()):
    return c.ContextoCoach(etiquetas=list(etiquetas), habitos=list(habitos))


class TestCoachHabitos(unittest.TestCase):
    def test_system_prompt_incluye_la_regla(self):
        p = c.construir_prompt("hola", "", [])
        for frase in ("Si el usuario ha escrito un hábito real", "siesta", "fisioterapia", "asdf", "teletransportación",
                      "ignórala por completo sin mencionarla ni inventar efectos"):
            self.assertIn(frase, p)

    def test_reconocimiento(self):
        for t, k in (("Siesta 30 min", "siesta"), ("Ayuno", "ayuno"), ("Hidratación", "hidratacion"),
                     ("Viaje largo", "viaje"), ("Dolor de rodilla", "dolor"), ("Suplemento", "suplemento"),
                     ("Fisioterapia", "fisioterapia"), ("Altitud", "altitud"), ("Café", "cafe"),
                     ("Mal descanso", "descanso"), ("Estrés", "estres")):
            self.assertEqual(c.reconocer_habito(t), k, t)
        for t in ("asdf", "volar", "teletransportación", "qwerty", "zzz"):
            self.assertIsNone(c.reconocer_habito(t), t)

    def test_offline_interpreta_lo_real_e_ignora_lo_absurdo(self):
        r = c.respuesta_offline("¿Cómo me están afectando mis hábitos?",
                                _ctx([("Siesta 30 min", 3), ("asdf", 5), ("volar", 2), ("Ayuno", 1)]))
        self.assertIn("Siesta 30 min", r)
        self.assertIn("Ayuno", r)
        self.assertNotIn("asdf", r)
        self.assertNotIn("volar", r)
        self.assertIn("siesta corta", r)

    def test_offline_solo_absurdos_no_los_menciona(self):
        r = c.respuesta_offline("¿Cómo me están afectando mis hábitos?", _ctx([("asdf", 4), ("teletransportación", 2)]))
        self.assertNotIn("asdf", r)
        self.assertNotIn("teletransportación", r)
        self.assertIn("Todavía no hay hábitos reconocibles", r)

    def test_efecto_hrv_filtra_absurdos(self):
        r = c.respuesta_offline("hábitos", _ctx([("Siesta", 3), ("asdf", 3)], [("Siesta", 3, 40.0, -12.0), ("asdf", 3, 40.0, 30.0)]))
        self.assertIn("Tras «Siesta»", r)
        self.assertNotIn("asdf", r)

    def test_habito_real_llega_al_contexto_del_usuario(self):
        vm, repo = _vm()
        vm.poner_habito("Fisioterapia")
        ctx = c.recopilar_contexto(repo, None, AHORA + 5)
        self.assertIn(("Fisioterapia", 1), ctx.etiquetas)


class TestDisciplinaPersonalizada(unittest.TestCase):
    def _sesion(self, repo, uid="s"):
        ini = AHORA - 86400
        a = repo.guardar_actividad(uid, ini, ini + 1200, "x")
        for i in range(0, 1200, 10):
            repo.guardar_medicion(130, datetime.fromtimestamp(ini + i), uid=f"{uid}{i}", etiqueta="ACTIVIDAD", actividad_id=a, nivel_actividad=1)
        return a

    def test_normalizar_disciplina(self):
        self.assertEqual(disc.normalizar_disciplina("  Remo   indoor "), "Remo indoor")
        self.assertEqual(disc.normalizar_disciplina("carrera"), "Carrera")
        with self.assertRaises(ValueError):
            disc.normalizar_disciplina(" ")

    def test_guardar_y_aparecer_en_el_filtro(self):
        vm, repo = _vm()
        a = self._sesion(repo)
        vm.guardar_disciplina(a, "Remo indoor")
        self.assertEqual(vm.disciplinas()[a], "Remo indoor")
        v = VistaActividades(vm)
        v.selector.establecer_rango(date.fromtimestamp(AHORA - 5 * 86400), date.fromtimestamp(AHORA))
        v.actualizar()
        self.assertGreaterEqual(v.combo_filtro_disciplina.findData("Remo indoor"), 0)
        self.assertEqual(v.combo_filtro_disciplina.itemData(v.combo_filtro_disciplina.count() - 1), "")   # «Sin disciplina» al final
        v.combo_filtro_disciplina.setCurrentIndex(v.combo_filtro_disciplina.findData("Remo indoor"))
        self.assertEqual(v.tabla.rowCount(), 1)
        v.combo_filtro_disciplina.setCurrentIndex(v.combo_filtro_disciplina.findData("Fuerza"))
        self.assertEqual(v.tabla.rowCount(), 0)

    def test_combo_editable_guarda_texto_libre(self):
        vm, repo = _vm()
        a = self._sesion(repo)
        v = VistaActividades(vm)
        v.selector.establecer_rango(date.fromtimestamp(AHORA - 5 * 86400), date.fromtimestamp(AHORA))
        v.actualizar()
        v.tabla.selectRow(0)
        self.assertTrue(v.combo_disciplina.isEditable())
        for predef in disc.DISCIPLINAS:                                   # las predefinidas siguen ahí
            self.assertGreaterEqual(v.combo_disciplina.findData(predef), 0)
        v.combo_disciplina.setEditText("Remo indoor")
        v.btn_disciplina.click()
        self.assertEqual(vm.disciplinas()[a], "Remo indoor")
        self.assertEqual(v.combo_disciplina.currentData(), "Remo indoor")     # reaparece tras actualizar
        v.combo_disciplina.setEditText("carrera")                             # texto = predefinida → su grafía
        v.btn_disciplina.click()
        self.assertEqual(vm.disciplinas()[a], "Carrera")


if __name__ == "__main__":
    unittest.main()
