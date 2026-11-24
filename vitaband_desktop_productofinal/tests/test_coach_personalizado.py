"""Coach personalizado: vitaband-coach v5.0 sobre qwen2.5:1.5b / qwen2.5, versión en app_meta, ficha y reglas de coach."""
import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from services import coach_ia as c
from services import contexto_coach as cc
from services import ollama_provisioner as prov
from services.app_meta import AppMeta
from services.repositorio_historial import RepositorioHistorial
from ui.coach_ia_widget import CoachIaWidget
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


class Red:
    def __init__(self):
        self.peticiones = []

    def __call__(self, peticion, timeout=None):
        self.peticiones.append((peticion.full_url, json.loads(peticion.data.decode())))

        class R:
            def __enter__(s):
                return s

            def __exit__(s, *a):
                return False

            def __iter__(s):
                return iter([b'{"status": "success"}\n'])
        return R()


def _vm():
    repo = RepositorioHistorial(os.path.join(tempfile.mkdtemp(), "t.db"), usuario_id=1)
    repo.guardar_perfil(35, "M", 75.0, 150)
    ini = AHORA - 86400
    a = repo.guardar_actividad("a1", ini, ini + 1800, "x")
    for i in range(0, 1800, 10):
        repo.guardar_medicion(110 + (i // 100), datetime.fromtimestamp(ini + i), uid=f"m{i}", etiqueta="ACTIVIDAD",
                              actividad_id=a, nivel_actividad=1)
    return VitaBandViewModel(MagicMock(), repositorio=repo, reloj=Reloj()), repo


class TestCreacionDeVitabandCoach(unittest.TestCase):
    def test_constantes_v3(self):
        self.assertEqual(prov.COACH_MODEL_NAME, "vitaband-coach")
        self.assertEqual(prov.COACH_PROMPT_VERSION, "v5.0")

    def test_crea_sobre_ligero_y_sobre_completo_sin_descargar(self):
        for instalado, esperado in ((["qwen2.5:1.5b"], "qwen2.5:1.5b"), (["qwen2.5:latest"], "qwen2.5:latest"),
                                    (["qwen2.5", "qwen2.5:1.5b"], "qwen2.5")):
            red = Red()
            with patch.object(prov, "_urlopen", red), patch.object(c, "modelos_ollama", return_value=instalado):
                self.assertTrue(prov.preparar_coach())
            self.assertEqual([u.rsplit("/", 1)[1] for u, _ in red.peticiones], ["create"])      # nunca /api/pull
            cuerpo = red.peticiones[0][1]
            self.assertEqual((cuerpo["model"], cuerpo["from"]), ("vitaband-coach", esperado))
            self.assertEqual(cuerpo["parameters"], {"temperature": 0.35, "top_p": 0.85, "repeat_penalty": 1.12, "num_ctx": 8192})
            self.assertIn("v5.0", cuerpo["system"])
            self.assertIn("[NIVEL:SENCILLO]", cuerpo["system"])
            self.assertIn("[NIVEL:EXPERTO]", cuerpo["system"])

    def test_actualiza_solo_si_cambia_la_version_guardada(self):
        modelos = ["vitaband-coach:latest", "qwen2.5:1.5b"]
        red = Red()
        with patch.object(prov, "_urlopen", red), patch.object(c, "modelos_ollama", return_value=modelos):
            self.assertFalse(prov.preparar_coach(version_guardada="v5.0"))
            self.assertEqual(red.peticiones, [])
            self.assertTrue(prov.preparar_coach(version_guardada="v2.0"))
            self.assertTrue(prov.preparar_coach(version_guardada=None))
        self.assertEqual(len(red.peticiones), 2)

    def test_sin_qwen_ni_ollama_no_hace_nada(self):
        red = Red()
        for modelos in (None, [], ["llama3"]):
            with patch.object(prov, "_urlopen", red), patch.object(c, "modelos_ollama", return_value=modelos):
                self.assertFalse(prov.preparar_coach())
        self.assertEqual(red.peticiones, [])

    def test_version_en_app_meta(self):
        _, repo = _vm()
        m = AppMeta(repo)
        self.assertIsNone(m.obtener("coach_prompt_version"))
        m.guardar("coach_prompt_version", "v5.0")
        m.guardar("coach_prompt_version", "v3.1")
        self.assertEqual(AppMeta(repo).obtener("coach_prompt_version"), "v3.1")

    def test_el_widget_guarda_la_version_y_no_toca_el_consentimiento(self):
        vm, _ = _vm()
        red = Red()
        with patch.object(c, "detectar_motor", return_value=c.MOTOR_OFFLINE), patch.object(prov, "_urlopen", red):
            w = CoachIaWidget(vm)
            w._construir()
            esperar(w._hilo_det)
            self.assertFalse(w.tarjeta_consentimiento.isHidden())         # falta motor → sigue pidiendo consentimiento
            self.assertEqual(red.peticiones, [])
        w._guardar_version_coach()
        self.assertEqual(vm.app_meta().obtener(prov.CLAVE_VERSION_META), "v5.0")
        w.close()


class TestPromptMaestro(unittest.TestCase):
    def test_reglas_de_coach_y_acciones(self):
        p = cc.PROMPT_MAESTRO
        for frase in ("15 %", "-20", "Zona 1–2", "COHERENCIA_60S", "PLAN_ZONA2", "agujetas internas",
                      "tu Zona 2 hoy está entre X e Y BPM"):
            self.assertIn(frase, p)

    def test_por_defecto_sencillo_y_cambio_a_experto(self):
        self.assertIn("[NIVEL:SENCILLO]", cc.prompt_sistema())
        self.assertNotIn("[NIVEL:EXPERTO]", cc.prompt_sistema())
        self.assertIn("[NIVEL:EXPERTO]", cc.prompt_sistema(cc.NIVEL_EXPERTO))
        self.assertIn("VEREDICTO CLARO", cc.prompt_sistema(cc.NIVEL_EXPERTO))

    def test_arquetipos(self):
        self.assertEqual([v[0] for v in cc.ARQUETIPOS.values()], ["Entrenador Cercano", "Fisiólogo Clínico", "Copiloto Antiestrés"])
        self.assertEqual(cc.ARQUETIPO_DEFECTO, "cercano")


class TestContextoYMemoria(unittest.TestCase):
    def test_zonas_con_los_bpm_del_usuario(self):
        z = cc.zonas_bpm(190)
        self.assertEqual([(a, lo, hi) for a, lo, hi in z][1], (2, 114, 133))
        self.assertIn("Z2 114-133 BPM", cc.texto_zonas(190))

    def test_contexto_incluye_zonas_trimp_y_desacoplamiento(self):
        vm, _ = _vm()
        t = vm.contexto_total_coach()
        for k in ("FICHA", "Zonas de pulso del usuario", "Última sesión ECG", "Z1", "TRIMP", "Desacoplamiento"):
            self.assertIn(k, t)

    def test_ficha_editable_sobrescribe_lo_automatico(self):
        vm, _ = _vm()
        m = vm.memoria_coach()
        m.fijar_ficha("disciplina", "Ciclismo")
        m.fijar_ficha("fc_max", "180")
        m.fijar_ficha("fc_reposo", "52")
        t = vm.contexto_total_coach()
        self.assertIn("disciplina habitual Ciclismo", t)
        self.assertIn("FC máx 180 BPM", t)
        self.assertIn("FC reposo 52 BPM", t)
        self.assertIn("Z2 108-126 BPM", t)
        self.assertEqual(m.listar(), [])                                  # la ficha no se mezcla con las notas
        m.fijar_ficha("disciplina", "")
        self.assertNotIn("disciplina", m.ficha())

    def test_solo_las_ultimas_8_notas_se_inyectan(self):
        vm, _ = _vm()
        m = vm.memoria_coach()
        for i in range(12):
            m.agregar(f"nota {i}", "nota", ts=AHORA + i)
        txt = m.a_texto()
        self.assertEqual(len(txt.splitlines()), 8)
        self.assertIn("nota 11", txt)
        self.assertNotIn("nota 3\n", txt + "\n")

    def test_alerta_si_el_rmssd_cae_mas_de_un_15_por_ciento(self):
        from domain.hrv import ResultadoHrv
        vm, repo = _vm()
        for d in range(28):
            repo.guardar_hrv(ResultadoHrv(AHORA - d * 86400 - 3600, 50.0 if d < 7 else 80.0, 60.0, 100))
        self.assertIn("ALERTA: el RMSSD de 7 días ha caído más de un 15 %", vm.contexto_total_coach())
        for d in range(28):
            repo.guardar_hrv(ResultadoHrv(AHORA - d * 86400 - 3600, 80.0, 60.0, 100))
        self.assertNotIn("ALERTA: el RMSSD", vm.contexto_total_coach())


class TestWidgetDidactico(unittest.TestCase):
    def setUp(self):
        self.vm, _ = _vm()
        with patch.object(c, "detectar_motor", return_value=c.MOTOR_OFFLINE):
            self.w = CoachIaWidget(self.vm)
            self.w._construir()
            esperar(self.w._hilo_det)

    def tearDown(self):
        self.w.close()

    def test_nivel_defecto_y_cambio(self):
        self.assertEqual(self.w.combo_nivel.currentText(), "Sencillo (Explicado)")
        self.w.combo_nivel.setCurrentIndex(1)
        self.assertEqual(self.w.combo_nivel.currentText(), "Experto (Técnico)")
        self.assertEqual([self.w.combo_arquetipo.itemText(i) for i in range(3)],
                         ["Entrenador Cercano", "Fisiólogo Clínico", "Copiloto Antiestrés"])
        self.assertEqual(self.w.combo_arquetipo.currentText(), "Entrenador Cercano")

    def test_pildora_zonas_usa_las_pulsaciones_reales_offline(self):
        self.w.botones_principiante[1].click()
        resp = self.w.memoria.turnos[-1][1]
        self.assertIn("marchas de una bicicleta", resp)
        self.assertIn("BPM", resp)
        self.assertIn("Z2", resp)

    def test_pildora_bateria_traduce_a_lenguaje_cotidiano(self):
        ctx = c.ContextoCoach(fc_reposo=55.0, hrv_reciente=40.0, hrv_base=50.0, ratio_hrv=0.8, recuperacion="moderada",
                              hrv_ultimo=("01/01/2026", 40.0))
        r = c.respuesta_offline("¿Cómo está mi batería hoy?", ctx, sencillo=True)
        self.assertIn("batería de tu sistema nervioso", r)
        self.assertIn("80 %", r)

    def test_chuleta_acciones_y_modal_con_ficha(self):
        self.w.btn_metricas.click()
        self.assertEqual(len(cc.CHULETA.splitlines()), 5)
        hechos = []
        self.w.accion_plan_zona2.connect(lambda: hechos.append(1))
        self.w._terminar("q", "Rueda suave. [ACCION:PLAN_ZONA2]", c.MOTOR_OFFLINE)
        self.w.botones_accion[0].click()
        self.assertEqual(hechos, [1])
        self.w.btn_memoria.click()
        d = self.w.dialogo_memoria
        d.campos_ficha["disciplina"].setText("Remo")
        d.btn_guardar_ficha.click()
        self.assertEqual(self.vm.memoria_coach().ficha(), {"disciplina": "Remo"})
        d.close()


if __name__ == "__main__":
    unittest.main()
