"""Coach IA Maxx: nivel Sencillo/Experto, píldoras, chuleta, arquetipos, memoria coach_memoria y botones [ACCION:...]."""
import os
import tempfile
import unittest
from datetime import date, datetime
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from services import coach_ia as c
from services import contexto_coach as cc
from services.repositorio_historial import RepositorioHistorial
from ui.coach_ia_widget import CoachIaWidget
from ui.main_window import MainWindow
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])
AHORA = int(datetime.now().timestamp())


def esperar(hilo):
    while hilo is not None and hilo.isRunning():
        _app.processEvents()
        hilo.wait(10)
    _app.processEvents()


class Reloj:
    def __call__(self):
        return float(AHORA)


def _vm():
    repo = RepositorioHistorial(os.path.join(tempfile.mkdtemp(), "t.db"), usuario_id=1)
    repo.guardar_perfil(35, "M", 75.0, 150)
    ini = AHORA - 86400
    a = repo.guardar_actividad("a1", ini, ini + 1800, "x")
    for i in range(0, 1800, 10):
        repo.guardar_medicion(120 + (i // 300), datetime.fromtimestamp(ini + i), uid=f"m{i}", etiqueta="ACTIVIDAD",
                              actividad_id=a, nivel_actividad=1)
    return VitaBandViewModel(MagicMock(), repositorio=repo, reloj=Reloj()), repo


class TestPrompt(unittest.TestCase):
    def test_nivel_sencillo_inyecta_etiqueta_analogias_y_3_bloques(self):
        p = cc.prompt_sistema(cc.NIVEL_SENCILLO)
        self.assertIn("[NIVEL:SENCILLO]", p)
        self.assertNotIn("[NIVEL:EXPERTO]", p)
        for frase in ("marchas de una bici", "porcentaje de batería", "fatiga acumulada", "depósito de resistencia",
                      "desacoplamiento aeróbico", "1. En resumen", "Qué dicen tus datos (en palabras fáciles)",
                      "Qué te recomiendo hacer hoy"):
            self.assertIn(frase, p)

    def test_nivel_experto(self):
        p = cc.prompt_sistema(cc.NIVEL_EXPERTO)
        self.assertIn("[NIVEL:EXPERTO]", p)
        self.assertNotIn("[NIVEL:SENCILLO]", p)
        for frase in ("VEREDICTO CLARO", "EVIDENCIA FISIOLÓGICA", "ACCIÓN INMEDIATA"):
            self.assertIn(frase, p)

    def test_arquetipos_acciones_y_memoria_en_el_prompt(self):
        self.assertEqual([v[0] for v in cc.ARQUETIPOS.values()],
                         ["Entrenador Cercano", "Fisiólogo Clínico", "Copiloto Antiestrés"])
        self.assertIn("Copiloto Antiestrés", cc.prompt_sistema(arquetipo="antiestres"))
        p = cc.prompt_sistema(memoria="- Lesión: rodilla")
        self.assertIn("COHERENCIA_60S", p)
        self.assertIn("PLAN_ZONA2", p)
        self.assertIn("Lesión: rodilla", p)

    def test_offline_sencillo_usa_analogias(self):
        ctx = c.ContextoCoach(fc_reposo=55.0, hrv_reciente=40.0, hrv_base=50.0, ratio_hrv=0.8, recuperacion="moderada")
        self.assertIn("batería", c.respuesta_offline("¿Cómo está mi batería hoy?", ctx, sencillo=True))
        self.assertNotIn("En resumen", c.respuesta_offline("¿Cómo está mi batería hoy?", ctx))
        self.assertIn("marchas de una bicicleta", c.respuesta_offline("¿Qué son las Zonas 1 a 5?", c.ContextoCoach()))


class TestAcciones(unittest.TestCase):
    def test_extraer_acciones(self):
        t, a = cc.extraer_acciones("Respira hondo. [ACCION:COHERENCIA_60S] Luego rueda suave. [ACCION:PLAN_ZONA2] [ACCION:BORRAR]")
        self.assertEqual(a, ["COHERENCIA_60S", "PLAN_ZONA2"])
        self.assertNotIn("[ACCION", t)
        self.assertEqual(cc.extraer_acciones("sin etiquetas")[1], [])


class TestMemoria(unittest.TestCase):
    def test_persistencia_sin_duplicados_y_borrado(self):
        vm, repo = _vm()
        m = vm.memoria_coach()
        a = m.agregar("Maratón de Valencia en diciembre")
        self.assertIsNone(m.agregar("Maratón de Valencia en diciembre"))
        self.assertEqual([t for _, _, _, t in vm.memoria_coach().listar()], ["Maratón de Valencia en diciembre"])
        self.assertTrue(m.eliminar(a))
        self.assertEqual(m.listar(), [])
        with self.assertRaises(ValueError):
            m.agregar("   ")

    def test_hechos_del_chat(self):
        vm, _ = _vm()
        m = vm.memoria_coach()
        nuevos = m.registrar_hechos_de("Tengo una lesión en el gemelo. Dormí mal esta semana. ¿Puedo correr?")
        self.assertEqual(len(nuevos), 2)
        self.assertIn("Lesión: Tengo una lesión en el gemelo.", m.a_texto())
        self.assertEqual(m.registrar_hechos_de("Hoy hace sol"), [])

    def test_contexto_total_incluye_ficha_carga_y_ultima_sesion(self):
        vm, repo = _vm()
        from services.balance_mental import BalanceCargaMental
        BalanceCargaMental(repo).sumar(60, 20, 10)
        t = vm.contexto_total_coach()
        for clave in ("FICHA", "objetivo 150 min semanales", "Carga: CTL", "Balance de estrés de hoy", "Última sesión ECG"):
            self.assertIn(clave, t)


class TestWidget(unittest.TestCase):
    def setUp(self):
        self.vm, self.repo = _vm()
        with patch.object(c, "detectar_motor", return_value=c.MOTOR_OFFLINE):
            self.w = CoachIaWidget(self.vm)
            self.w._construir()
            esperar(self.w._hilo_det)

    def tearDown(self):
        self.w.close()

    def test_nivel_por_defecto_sencillo_y_arquetipo(self):
        self.assertEqual(self.w.combo_nivel.currentText(), "Sencillo (Explicado)")
        self.assertEqual(self.w.nivel, cc.NIVEL_SENCILLO)
        self.w.combo_nivel.setCurrentIndex(1)
        self.assertEqual((self.w.combo_nivel.currentText(), self.w.nivel), ("Experto (Técnico)", cc.NIVEL_EXPERTO))
        self.assertEqual([self.w.combo_arquetipo.itemText(i) for i in range(3)],
                         ["Entrenador Cercano", "Fisiólogo Clínico", "Copiloto Antiestrés"])

    def test_pildoras_rapidas_para_principiantes(self):
        self.assertEqual([b.text() for b in self.w.botones_principiante],
                         ["¿Cómo está mi batería hoy?", "¿Qué son las Zonas 1 a 5?", "Resume mi última sesión fácil"])
        self.w.botones_principiante[1].click()
        self.assertEqual(self.w.memoria.turnos[-1][0], "¿Qué son las Zonas 1 a 5?")
        self.assertIn("marchas de una bicicleta", self.w.memoria.turnos[-1][1])

    def test_chuleta_instantanea_de_5_lineas_sin_inferencia(self):
        n = len(self.w.memoria.turnos)
        with patch.object(c, "responder") as r:
            self.w.btn_metricas.click()
        r.assert_not_called()
        self.assertEqual(len(self.w.memoria.turnos), n)
        self.assertEqual(len(cc.CHULETA.splitlines()), 5)
        for k in ("BPM", "Zonas 1–5", "HRV/RMSSD", "TRIMP", "Desacoplamiento"):
            self.assertIn(k, cc.CHULETA)

    def test_ollama_recibe_nivel_arquetipo_memoria_y_contexto_total(self):
        self.w._mostrar_motor(c.Motor("ollama", "vitaband-coach"))
        self.w.combo_arquetipo.setCurrentIndex(self.w.combo_arquetipo.findData("antiestres"))
        vistos = {}

        def falso(modelo, prompt, timeout, **kw):
            vistos["p"] = prompt
            return "Respira. [ACCION:COHERENCIA_60S]"

        with patch.object(c, "consultar_ollama", falso):
            self.w.enviar("Tengo una lesión en el pie. ¿Qué hago?")
            esperar(self.w._hilo)
        p = "\n".join(m["content"] for m in vistos["p"])
        self.assertIn("[NIVEL:SENCILLO]", p)
        self.assertIn("Copiloto Antiestrés", p)
        self.assertIn("FICHA", p)
        self.assertIn("Lesión: Tengo una lesión en el pie.", self.vm.memoria_coach().a_texto())
        self.assertEqual(len(self.w.botones_accion), 1)
        self.assertIn("#D4AF37", self.w.botones_accion[0].styleSheet())

    def test_botones_de_accion_lanzan_coherencia_y_plan_zona2(self):
        hechos = []
        self.w.accion_coherencia.connect(lambda: hechos.append("coh"))
        self.w.accion_plan_zona2.connect(lambda: hechos.append("z2"))
        self.w._terminar("q", "Haz esto. [ACCION:COHERENCIA_60S] [ACCION:PLAN_ZONA2]", c.MOTOR_OFFLINE)
        self.assertEqual(len(self.w.botones_accion), 2)
        for b in self.w.botones_accion:
            b.click()
        self.assertEqual(hechos, ["coh", "z2"])
        self.assertNotIn("[ACCION", self.w.memoria.turnos[-1][1])

    def test_analizar_ultima_y_auto_analisis(self):
        self.w.btn_analizar_ultima.click()
        self.assertEqual(self.w.memoria.turnos[-1][0], "Analiza mi última sesión")
        n = len(self.w.memoria.turnos)
        self.vm.sesion_importada.emit()                          # sin el check no hace nada
        self.assertEqual(len(self.w.memoria.turnos), n)
        self.w.chk_auto_analisis.setChecked(True)
        self.vm.sesion_importada.emit()
        self.assertEqual(len(self.w.memoria.turnos), n + 1)

    def test_modal_perfil_y_memoria(self):
        self.w.btn_memoria.click()
        d = self.w.dialogo_memoria
        d.txt_nota.setText("Carrera de 10K en marzo")
        d.btn_anadir.click()
        self.assertEqual(d.lista.count(), 1)
        self.assertIn("FICHA", d.lbl_ficha.text())
        self.assertEqual(len(self.vm.memoria_coach().listar()), 1)
        d.lista.setCurrentRow(0)
        d.btn_eliminar.click()
        self.assertEqual(d.lista.count(), 0)
        d.close()


class TestIntegracionVentana(unittest.TestCase):
    def test_accion_plan_zona2_agenda_40_min_en_planificacion(self):
        vm, repo = _vm()
        v = MainWindow(vm, "Ana")
        v.coach_ia.accion_plan_zona2.emit()
        from services.planificacion_entrenamiento import GestorCalendarioPlanificado
        s = GestorCalendarioPlanificado(repo).entre(date.today(), date.today())
        self.assertEqual([(x.nombre, x.minutos) for x in s], [("Zona 2 (Coach IA)", 40.0)])
        v.close()

    def test_accion_coherencia_abre_el_dialogo(self):
        vm, _ = _vm()
        v = MainWindow(vm, "Ana")
        v.coach_ia.accion_coherencia.emit()
        self.assertIsNotNone(v.dialogo_coherencia)
        v.dialogo_coherencia.close()
        v.close()


if __name__ == "__main__":
    unittest.main()
