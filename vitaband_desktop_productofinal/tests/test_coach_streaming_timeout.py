"""Coach IA: streaming NDJSON, timeout 120 s, keep_alive y motor que no revierte a Análisis Offline."""
import json
import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from services import coach_ia as c
from services.repositorio_historial import RepositorioHistorial
from ui.coach_ia_widget import CoachIaWidget, TEXTO_CARGANDO
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])


def _resp(lineas):
    r = MagicMock()
    r.__enter__.return_value.__iter__.return_value = iter([(json.dumps(x) + "\n").encode() for x in lineas])
    return r


def _espera(w, ms=5000):
    t = time.time()
    while w._hilo is not None and w._hilo.isRunning() and time.time() - t < ms / 1000:
        _app.processEvents()
        w._hilo.wait(10)
    for _ in range(5):
        _app.processEvents()


def _widget(modelo="qwen2.5:latest"):
    repo = RepositorioHistorial(os.path.join(tempfile.mkdtemp(), "t.db"), usuario_id=1)
    vm = VitaBandViewModel(MagicMock(), repositorio=repo)
    with patch.object(c, "detectar_motor", return_value=c.MOTOR_OFFLINE):
        w = CoachIaWidget(vm)
        w._construir()
        while w._hilo_det is not None and w._hilo_det.isRunning():
            _app.processEvents()
            w._hilo_det.wait(10)
    w._mostrar_motor(c.Motor("ollama", modelo))
    return w


class TestPeticion(unittest.TestCase):
    def test_envia_keep_alive_opciones_stream_y_timeout_120(self):
        with patch("urllib.request.urlopen", return_value=_resp([{"response": "Ho"}, {"response": "la"}, {"done": True}])) as u:
            self.assertEqual(c.consultar_ollama("qwen2.5:latest", "p"), "Hola")
        cuerpo = json.loads(u.call_args.args[0].data)
        self.assertEqual(cuerpo["model"], "qwen2.5:latest")
        self.assertIs(cuerpo["stream"], True)
        self.assertEqual(cuerpo["keep_alive"], "15m")
        self.assertEqual(cuerpo["options"], {"num_ctx": 4096, "temperature": 0.65, "top_p": 0.9, "num_predict": 700})
        self.assertGreaterEqual(u.call_args.kwargs["timeout"], 120)

    def test_entrega_fragmentos_en_orden(self):
        vistos = []
        with patch("urllib.request.urlopen", return_value=_resp([{"response": "a"}, {"response": "b"}, {"done": True}])):
            c.consultar_ollama("m", "p", al_fragmento=vistos.append)
        self.assertEqual(vistos, ["a", "b"])

    def test_desconexion_vs_fallo_puntual(self):
        with patch("urllib.request.urlopen", side_effect=ConnectionRefusedError()):
            with self.assertRaises(c.OllamaDesconectado):
                c.consultar_ollama("m", "p")
        with patch("urllib.request.urlopen", side_effect=TimeoutError("read timed out")):
            with self.assertRaises(c.ErrorGeneracion):
                c.consultar_ollama("m", "p")
        ctx = c.ContextoCoach() if hasattr(c, "ContextoCoach") else None
        motor = c.Motor("ollama", "qwen2.5:latest")
        with patch.object(c, "consultar_ollama", side_effect=c.ErrorGeneracion("lento")):
            with self.assertRaises(c.ErrorGeneracion):
                c.responder(motor, "hola", ctx, [], estricto=True)
        with patch.object(c, "consultar_ollama", side_effect=c.OllamaDesconectado("x")):
            self.assertEqual(c.responder(motor, "hola", ctx, [], estricto=True)[1], c.MOTOR_OFFLINE)


class TestBurbuja(unittest.TestCase):
    def test_stream_actualiza_la_burbuja_sin_volver_a_offline(self):
        w = _widget("vitaband-coach:latest")
        estados = []

        def lento(modelo, prompt, timeout, al_fragmento=None, **kw):
            self.assertEqual(modelo, "vitaband-coach:latest")
            self.assertGreaterEqual(timeout, 120)
            estados.append(w._vivo.findChild(QLabel).text())          # antes del primer token: indicador de carga
            for t in ("Hola ", "desde ", "Qwen"):
                al_fragmento(t)
                time.sleep(0.05)
            return "Hola desde Qwen"
        with patch.object(c, "consultar_ollama", lento):
            w.enviar("hola")
            self.assertIn(TEXTO_CARGANDO, w._vivo.findChild(QLabel).text())
            _espera(w)
        self.assertIn(TEXTO_CARGANDO, estados[0])
        self.assertEqual(w.memoria.turnos[-1][1], "Hola desde Qwen")
        self.assertEqual(w.lbl_motor.text(), "Motor: Ollama (vitaband-coach:latest)")
        self.assertIsNone(w._vivo)
        self.assertTrue(w.btn_enviar.isEnabled())
        w.close()

    def test_fragmento_reemplaza_el_indicador(self):
        w = _widget()
        w._vivo = w._burbuja(TEXTO_CARGANDO, usuario=False)
        w._acumulado = ""
        w._fragmento("Ho")
        w._fragmento("la")
        t = w._vivo.findChild(QLabel).text()
        self.assertIn("Hola", t)
        self.assertNotIn("Cargando", t)
        w.close()

    def test_error_puntual_mantiene_motor_y_ofrece_reintentar(self):
        w = _widget("qwen2.5:latest")
        with patch.object(c, "consultar_ollama", side_effect=c.ErrorGeneracion("read timed out", "Parcial")):
            w.enviar("hola")
            _espera(w)
        self.assertEqual(w.lbl_motor.text(), "Motor: Ollama (qwen2.5:latest)")
        self.assertEqual(w.btn_reintentar.text(), "Reintentar")
        self.assertTrue(w.btn_enviar.isEnabled())
        with patch.object(c, "consultar_ollama", return_value="Ya estoy"):
            w.btn_reintentar.click()
            _espera(w)
        self.assertEqual(w.memoria.turnos[-1][1], "Ya estoy")
        self.assertEqual(w.lbl_motor.text(), "Motor: Ollama (qwen2.5:latest)")
        w.close()

    def test_servidor_caido_si_pasa_a_offline(self):
        w = _widget()
        with patch.object(c, "consultar_ollama", side_effect=ConnectionRefusedError("x")):
            w.enviar("Analiza mi última sesión")
            _espera(w)
        self.assertEqual(w.lbl_motor.text(), "Motor: Análisis Offline")
        w.close()


if __name__ == "__main__":
    unittest.main()


class TestChatConversacional(unittest.TestCase):
    def test_saludo_va_limpio_y_el_contexto_solo_en_system(self):
        m = c.construir_mensajes("hola", "FC reposo 52 · TSB -12", [("q", "a")])
        self.assertEqual([x["role"] for x in m], ["system", "user", "assistant", "user"])
        self.assertEqual(m[-1]["content"], "hola")
        self.assertIn("TSB -12", m[0]["content"])
        self.assertNotIn("TSB", m[-1]["content"] + m[1]["content"])
        for frase in ("PROHIBIDO soltar", "duelo", "dolor torácico", "<ACTION>"):
            self.assertIn(frase, m[0]["content"])

    def test_acciones_en_formato_action_y_legado(self):
        from services import contexto_coach as cc
        t, a = cc.extraer_acciones('Hecho.<ACTION>{"type": "plan_zona2"}</ACTION> [ACCION:COHERENCIA_60S]')
        self.assertEqual((t, a), ("Hecho.", ["PLAN_ZONA2", "COHERENCIA_60S"]))


class TestChatConversacional(unittest.TestCase):
    def test_saludo_va_limpio_y_el_contexto_solo_en_system(self):
        m = c.construir_mensajes("hola", "FC reposo 52 · TSB -12", [("q", "a")])
        self.assertEqual([x["role"] for x in m], ["system", "user", "assistant", "user"])
        self.assertEqual(m[-1]["content"], "hola")
        self.assertIn("TSB -12", m[0]["content"])
        self.assertNotIn("TSB", m[-1]["content"] + m[1]["content"])
        for frase in ("PROHIBIDO soltar", "duelo", "dolor torácico", "<ACTION>"):
            self.assertIn(frase, m[0]["content"])

    def test_acciones_en_formato_action_y_legado(self):
        from services import contexto_coach as cc
        t, a = cc.extraer_acciones('Hecho.<ACTION>{"type": "plan_zona2"}</ACTION> [ACCION:COHERENCIA_60S]')
        self.assertEqual((t, a), ("Hecho.", ["PLAN_ZONA2", "COHERENCIA_60S"]))
