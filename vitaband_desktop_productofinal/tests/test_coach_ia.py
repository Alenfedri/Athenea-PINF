"""Coach IA: contexto SQLite, elección de modelo, memoria, respaldo offline y widget."""
import os
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame, QPushButton

from domain.hrv import ResultadoHrv
from services import coach_ia as c
from services.repositorio_historial import RepositorioHistorial
from ui.coach_ia_widget import CONSULTAS_RAPIDAS, CoachIaWidget
from ui.main_window import MainWindow
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])
AHORA = 1_800_000_000
DIA = 86400


def esperar(hilo):
    """Espera a un QThread procesando eventos (sus señales llegan en cola al hilo principal)."""
    while hilo is not None and hilo.isRunning():
        _app.processEvents()
        hilo.wait(10)
    _app.processEvents()


class Reloj:
    def __call__(self):
        return float(AHORA)


def _repo_con_datos():
    repo = RepositorioHistorial(":memory:", usuario_id=1)
    repo.guardar_perfil(35, "M", 75.0, 150)
    for i in range(20):  # base ~50 ms los días antiguos, ~30 ms los 3 últimos
        d = 19 - i
        valor = 30.0 if d < 3 else 50.0
        repo.guardar_hrv(ResultadoHrv(AHORA - d * DIA - 3600 * 5, valor, 60.0, 100))
    for k in range(3):
        repo.guardar_marcador(AHORA - (4 + k) * DIA, "Café")
    ini = AHORA - 2 * DIA
    aid = repo.guardar_actividad("a1", ini, ini + 1800, "carrera")
    for s in range(0, 1800, 10):
        repo.guardar_medicion(140 + (s % 20), datetime.fromtimestamp(ini + s), uid=f"m{s}", actividad_id=aid)
    return repo


class TestContexto(unittest.TestCase):
    def test_lee_datos_reales(self):
        repo = _repo_con_datos()
        ctx = c.recopilar_contexto(repo, VitaBandViewModel(MagicMock(), repositorio=repo, reloj=Reloj()).perfil(), AHORA)
        self.assertEqual(ctx.perfil["edad"], 35)
        self.assertEqual(ctx.recuperacion, "baja")          # 30/50 = 0,6
        self.assertAlmostEqual(ctx.ratio_hrv, 0.6, places=2)
        self.assertEqual(ctx.ultima["duracion_min"], 30)
        self.assertEqual(ctx.etiquetas[0], ("Café", 3))
        self.assertEqual(ctx.semana["sesiones"], 1)
        self.assertIn("Café", ctx.a_texto())

    def test_sin_repositorio_o_sin_datos(self):
        self.assertTrue(c.recopilar_contexto(None, None, AHORA).vacio)
        repo = RepositorioHistorial(":memory:", usuario_id=1)
        self.assertIsNone(c.recopilar_contexto(repo, None, AHORA).recuperacion)

    def test_solo_lectura(self):
        repo = _repo_con_datos()
        antes = repo._conn.total_changes
        c.recopilar_contexto(repo, None, AHORA)
        self.assertEqual(repo._conn.total_changes, antes)


class TestModelo(unittest.TestCase):
    def test_eleccion_por_ram_y_modelos(self):
        m = ["qwen2.5:7b-instruct", "qwen2.5:3b"]
        self.assertEqual(c.elegir_modelo(16, m), "qwen2.5:7b-instruct")
        self.assertEqual(c.elegir_modelo(12, ["qwen2.5:7b-q4_K_M"]), "qwen2.5:7b-q4_K_M")
        self.assertEqual(c.elegir_modelo(8, m), "qwen2.5:7b-instruct")      # el capaz va primero, sin depender de la RAM
        self.assertEqual(c.elegir_modelo(None, m), "qwen2.5:7b-instruct")
        self.assertEqual(c.elegir_modelo(32, ["qwen2.5:3b-instruct"]), "qwen2.5:3b-instruct")
        self.assertEqual(c.elegir_modelo(32, ["llama3:8b", "mistral"]), "mistral")
        self.assertEqual(c.elegir_modelo(8, ["qwen2.5:3b", "llama3.1:8b"]), "llama3.1:8b")
        self.assertIsNone(c.elegir_modelo(32, []))

    def test_prefijo_no_confunde_70b(self):
        self.assertTrue(c.coincide("qwen2.5:7b", "qwen2.5:7b"))
        self.assertTrue(c.coincide("qwen2.5:7b-q4_K_M", "qwen2.5:7b"))
        self.assertFalse(c.coincide("qwen2.5:70b", "qwen2.5:7b"))

    def test_detectar_motor(self):
        with patch.object(c, "modelos_ollama", return_value=["qwen2.5:7b", "qwen2.5:3b"]):
            self.assertEqual(c.detectar_motor(ram=lambda: 16.0), c.Motor("ollama", "qwen2.5:7b"))
            m = c.detectar_motor(ram=lambda: 8.0)
            self.assertEqual((m.etiqueta, m.acento), ("Motor: Ollama (qwen2.5:7b)", "emerald"))
        with patch.object(c, "modelos_ollama", return_value=None):
            m = c.detectar_motor()
            self.assertEqual((m.etiqueta, m.acento), ("Motor: Análisis Offline", "gold"))

    def test_modelos_ollama_con_timeout_de_1_5s(self):
        with patch("urllib.request.urlopen", side_effect=OSError("sin red")) as u:
            self.assertIsNone(c.modelos_ollama())
        self.assertEqual(u.call_args.kwargs.get("timeout", c.TIMEOUT_DETECCION_S), 1.5)


class TestMemoriaYRespuesta(unittest.TestCase):
    def test_memoria_de_3_turnos(self):
        m = c.MemoriaCorta()
        for i in range(12):
            m.agregar(f"q{i}", f"a{i}")
        self.assertEqual(m.turnos, [(f"q{i}", f"a{i}") for i in range(2, 12)])      # últimos 10 turnos
        p = c.construir_prompt("nueva", "ctx", m.turnos)
        self.assertIn("Usuario: q2", p)
        self.assertNotIn("Usuario: q1\n", p)
        m.limpiar()
        self.assertEqual(m.turnos, [])

    def test_offline_segun_intencion(self):
        ctx = c.recopilar_contexto(_repo_con_datos(), None, AHORA)
        self.assertIn("recuperación", c.respuesta_offline("¿Estoy recuperado para entrenar hoy?", ctx).lower())
        self.assertIn("30", c.respuesta_offline("Analiza mi última sesión", ctx))
        self.assertIn("Café", c.respuesta_offline("¿Cómo me están afectando mis hábitos?", ctx))
        self.assertTrue(c.respuesta_offline("Resumen de mi estado semanal", ctx))
        vacio = c.respuesta_offline("hola", c.ContextoCoach())
        self.assertIn("Aún no tengo datos", vacio)

    def test_ollama_ok_y_fallo(self):
        ctx = c.recopilar_contexto(_repo_con_datos(), None, AHORA)
        motor = c.Motor("ollama", "qwen2.5:3b")
        ok = MagicMock(return_value="Respuesta IA")
        self.assertEqual(c.responder(motor, "hola", ctx, [], consultar=ok), ("Respuesta IA", motor))
        self.assertEqual(ok.call_args.args[2], 120)
        mal = MagicMock(side_effect=TimeoutError())
        texto, usado = c.responder(motor, "Analiza mi última sesión", ctx, [], consultar=mal)
        self.assertEqual(usado, c.MOTOR_OFFLINE)
        self.assertIn("sesión", texto.lower())

    def test_consultar_ollama_post_a_generate(self):
        resp = MagicMock()
        resp.__enter__.return_value.__iter__.return_value = iter([b'{"response": " hola "}\n', b'{"done": true}\n'])
        with patch("urllib.request.urlopen", return_value=resp) as u:
            self.assertEqual(c.consultar_ollama("m", "p"), "hola")
        peticion = u.call_args.args[0]
        self.assertTrue(peticion.full_url.endswith("/api/generate"))
        self.assertEqual(u.call_args.kwargs["timeout"], 120)


class TestWidget(unittest.TestCase):
    def setUp(self):
        self.repo = _repo_con_datos()
        self.vm = VitaBandViewModel(MagicMock(), repositorio=self.repo, reloj=Reloj())
        with patch.object(c, "detectar_motor", return_value=c.MOTOR_OFFLINE):
            self.w = CoachIaWidget(self.vm)
            self.w._construir()
            self._esperar_deteccion()

    def _esperar_deteccion(self):
        esperar(self.w._hilo_det)

    def _esperar_respuesta(self):
        esperar(self.w._hilo)

    def tearDown(self):
        self.w.close()

    def test_cabecera_y_botones(self):
        self.assertEqual(self.w.lbl_motor.text(), "Motor: Análisis Offline")
        self.assertEqual(self.w.lbl_motor.property("accent"), "gold")
        self.assertEqual(self.w.cabecera.property("card"), "true")
        self.assertEqual([b.text() for b in self.w.botones_rapidos], list(CONSULTAS_RAPIDAS))
        self.assertEqual(self.w.btn_enviar.property("primary"), "true")
        self.assertIsInstance(self.w.btn_reconectar, QPushButton)

    def test_boton_rapido_envia_y_responde_offline(self):
        self.w.botones_rapidos[1].click()
        burbujas = self.w.findChildren(QFrame)
        usuario = [b for b in burbujas if b.property("burbuja") == "usuario"]
        self.assertEqual(len(usuario), 1)
        self.assertIn("#1B4D3E", usuario[0].styleSheet())
        self.assertEqual(self.w.memoria.turnos[0][0], CONSULTAS_RAPIDAS[1])

    def test_enter_envia_y_limpia_entrada(self):
        self.w.txt_entrada.setText("¿Estoy recuperado?")
        self.w.txt_entrada.returnPressed.emit()
        self.assertEqual(self.w.txt_entrada.text(), "")
        self.assertEqual(len(self.w.memoria.turnos), 1)

    def test_ollama_en_hilo_y_fallo_cambia_a_offline(self):
        self.w._mostrar_motor(c.Motor("ollama", "qwen2.5:7b"))
        self.assertEqual(self.w.lbl_motor.property("accent"), "emerald")
        with patch.object(c, "consultar_ollama", return_value="Hola desde Ollama"):
            self.w.enviar("hola")
            self._esperar_respuesta()
        self.assertEqual(self.w.memoria.turnos[-1][1], "Hola desde Ollama")
        with patch.object(c, "consultar_ollama", side_effect=ConnectionRefusedError("caído")):
            self.w.enviar("Analiza mi última sesión")
            self._esperar_respuesta()
        self.assertEqual(self.w.lbl_motor.text(), "Motor: Análisis Offline")
        self.assertTrue(self.w.btn_enviar.isEnabled())

    def test_reconectar_redetecta_en_segundo_plano(self):
        with patch.object(c, "detectar_motor", return_value=c.Motor("ollama", "qwen2.5:3b")):
            self.w.btn_reconectar.click()
            self._esperar_deteccion()
        self.assertEqual(self.w.lbl_motor.text(), "Motor: Ollama (qwen2.5:3b)")
        self.assertTrue(self.w.btn_reconectar.isEnabled())

    def test_reiniciar_limpia_memoria_e_historial(self):
        self.w.enviar("hola")
        self.w.reiniciar()
        self.assertEqual(self.w.memoria.turnos, [])
        self.assertEqual(self.w._chat.count(), 1)


class TestRegistro(unittest.TestCase):
    def test_pestana_y_cierre_de_sesion(self):
        repo = RepositorioHistorial(":memory:", usuario_id=1)
        vm = VitaBandViewModel(MagicMock(), repositorio=repo, reloj=Reloj())
        with patch.object(c, "detectar_motor", return_value=c.MOTOR_OFFLINE):
            v = MainWindow(vm, "Ana", "ana@correo.es")
            v.coach_ia._construir()
            esperar(v.coach_ia._hilo_det)
        textos = [v.pestanas.tabText(i) for i in range(v.pestanas.count())]
        self.assertIn("Coach IA", textos)
        v.coach_ia.memoria.agregar("q", "a")
        v.cerrar_sesion_solicitada.emit()
        self.assertEqual(v.coach_ia.memoria.turnos, [])
        v.close()


if __name__ == "__main__":
    unittest.main()
