"""Aprovisionamiento de Ollama/Qwen: consentimiento explícito, recomendación por hardware y cero red sin permiso."""
import json
import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from services import coach_ia as c
from services import ollama_provisioner as prov
from services.repositorio_historial import RepositorioHistorial
from ui.coach_ia_widget import CoachIaWidget
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])


def esperar(hilo):
    while hilo is not None and hilo.isRunning():
        _app.processEvents()
        hilo.wait(10)
    _app.processEvents()


class Reloj:
    def __call__(self):
        return 1_800_000_000.0


class RespuestaNdjson:
    def __init__(self, eventos):
        self._l = [(json.dumps(e) + "\n").encode() for e in eventos]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self._l)


class RedFalsa:
    """Sustituye al urlopen del aprovisionador y registra cada petición."""

    def __init__(self):
        self.peticiones = []

    def __call__(self, peticion, timeout=None):
        cuerpo = json.loads(peticion.data.decode())
        self.peticiones.append((peticion.full_url, cuerpo))
        if peticion.full_url.endswith("/api/pull"):
            return RespuestaNdjson([{"status": "pulling manifest"}, {"status": "pulling", "total": 100, "completed": 40},
                                    {"status": "pulling", "total": 100, "completed": 100}, {"status": "success"}])
        return RespuestaNdjson([{"status": "success"}])


class TestCapacidadYCatalogo(unittest.TestCase):
    def test_catalogo_exacto(self):
        self.assertEqual((prov.LIGERA.model_id, prov.LIGERA.nombre, prov.LIGERA.tamano_gb, prov.LIGERA.etiqueta_peso),
                         ("qwen2.5:1.5b", "Qwen 2.5 Ligero (1.5B)", 1.0, "1,0 GB"))
        self.assertEqual((prov.COMPLETA.model_id, prov.COMPLETA.nombre, prov.COMPLETA.tamano_gb, prov.COMPLETA.etiqueta_peso),
                         ("qwen2.5", "Qwen 2.5 Completo (7B)", 4.7, "4,7 GB"))

    def test_detectar_capacidad_usa_ram_y_disco_inyectados(self):
        cap = prov.detectar_capacidad_equipo("/x", ram=lambda: 16.0, disco=lambda r: 100.0 if r == "/x" else None)
        self.assertEqual((cap.ram_gb, cap.disco_libre_gb, cap.ruta), (16.0, 100.0, "/x"))
        real = prov.detectar_capacidad_equipo()
        self.assertTrue(real.ram_gb is None or real.ram_gb > 0)
        self.assertTrue(real.disco_libre_gb is None or real.disco_libre_gb >= 0)

    def test_ruta_de_modelos_respeta_ollama_models(self):
        with patch.dict(os.environ, {"OLLAMA_MODELS": "/datos/modelos"}):
            self.assertEqual(prov.ruta_modelos(), "/datos/modelos")

    def test_regla_de_recomendacion(self):
        R = prov.recomendada
        C = prov.Capacidad
        self.assertIs(R(C(8, 200)), prov.LIGERA)
        self.assertIs(R(C(12.0, 200)), prov.LIGERA)         # ≤ 12 GB
        self.assertIs(R(C(32, 14.9)), prov.LIGERA)          # poco disco
        self.assertIs(R(C(12.1, 15.0)), prov.COMPLETA)
        self.assertIs(R(C(32, 500)), prov.COMPLETA)
        self.assertIs(R(C(None, 500)), prov.LIGERA)         # sin datos: lo prudente

    def test_etiqueta_recomendado_dinamica_y_unica(self):
        t = [x[1] for x in prov.opciones(prov.Capacidad(8, 100))]
        self.assertEqual(t, ["Qwen 2.5 Ligero (1.5B) · 1,0 GB (Recomendado)", "Qwen 2.5 Completo (7B) · 4,7 GB"])
        t = [x[1] for x in prov.opciones(prov.Capacidad(32, 100))]
        self.assertEqual(t, ["Qwen 2.5 Ligero (1.5B) · 1,0 GB", "Qwen 2.5 Completo (7B) · 4,7 GB (Recomendado)"])


class TestComprobacionPasiva(unittest.TestCase):
    def test_listo_si_hay_modelo(self):
        with patch.object(c, "modelos_ollama", return_value=["qwen2.5:7b"]):
            estado, motor = prov.comprobar(arrancar=False)
        self.assertEqual((estado, motor.tipo), (prov.READY, "ollama"))

    def test_vitaband_coach_tiene_prioridad(self):
        self.assertEqual(c.elegir_modelo(16.0, ["qwen2.5:3b", "vitaband-coach:latest"]), "vitaband-coach:latest")
        self.assertEqual(c.elegir_modelo(16.0, ["qwen2.5:7b", "vitaband-coach:latest"]), "qwen2.5:7b")

    def test_falta_ollama_o_qwen_pide_consentimiento_sin_descargar(self):
        red = MagicMock()
        for modelos in (None, []):
            with patch.object(c, "modelos_ollama", return_value=modelos), patch.object(prov, "_urlopen", red), \
                    patch.object(prov, "instalar_ollama", red), patch("subprocess.Popen", red), \
                    patch.object(prov, "binario_ollama", return_value=None):
                estado, motor = prov.comprobar()
            self.assertEqual((estado, motor), (prov.CONSENT_REQUIRED, c.MOTOR_OFFLINE))
        red.assert_not_called()

    def test_no_arranca_serve_en_pytest_ni_sin_binario(self):
        with patch.object(c, "modelos_ollama", return_value=None), patch("subprocess.Popen") as popen:
            self.assertFalse(prov.arrancar_si_instalado())
        popen.assert_not_called()


class TestAdoptarQwenExistente(unittest.TestCase):
    def test_crea_vitaband_coach_desde_qwen_ya_instalado_sin_descargar(self):
        red = RedFalsa()
        with patch.object(prov, "_urlopen", red), patch.object(c, "modelos_ollama", return_value=["qwen2.5:1.5b"]):
            self.assertTrue(prov.preparar_coach())
        self.assertEqual([u.rsplit("/", 1)[1] for u, _ in red.peticiones], ["create"])      # ningún /api/pull
        self.assertEqual(red.peticiones[0][1]["from"], "qwen2.5:1.5b")

    def test_no_hace_nada_si_ya_existe_o_no_hay_qwen(self):
        red = RedFalsa()
        for modelos in (["vitaband-coach:latest", "qwen2.5"], ["llama3"], [], None):
            with patch.object(prov, "_urlopen", red), patch.object(c, "modelos_ollama", return_value=modelos):
                self.assertFalse(prov.preparar_coach(version_guardada=prov.COACH_PROMPT_VERSION))
        self.assertEqual(red.peticiones, [])

    def test_sin_ventana_de_consola_en_windows(self):
        with patch.object(prov.sys, "platform", "win32"):
            self.assertEqual(prov._flags_sin_ventana(), {"creationflags": 0x08000000})
        with patch.object(prov.sys, "platform", "linux"):
            self.assertEqual(prov._flags_sin_ventana(), {})


class TestInstalacion(unittest.TestCase):
    CAP = prov.Capacidad(16.0, 100.0)

    def test_instala_exactamente_el_modelo_elegido_y_crea_vitaband_coach(self):
        red, prog = RedFalsa(), []
        with patch.object(prov, "_urlopen", red), patch.object(c, "modelos_ollama", return_value=[]):
            motor = prov.instalar("qwen2.5:1.5b", lambda p, t: prog.append(p), capacidad=self.CAP)
        self.assertEqual([u.rsplit("/", 1)[1] for u, _ in red.peticiones], ["pull", "create"])
        self.assertEqual(red.peticiones[0][1]["model"], "qwen2.5:1.5b")
        crear = red.peticiones[1][1]
        self.assertEqual((crear["model"], crear["from"]), ("vitaband-coach", "qwen2.5:1.5b"))
        self.assertIn("[NIVEL:SENCILLO]", crear["system"])
        self.assertIn("[NIVEL:EXPERTO]", crear["system"])
        self.assertIn(prov.COACH_PROMPT_VERSION, crear["system"])
        self.assertEqual(prov.COACH_PROMPT_VERSION, "v5.0")
        self.assertEqual(crear["parameters"], {"temperature": 0.35, "top_p": 0.85, "repeat_penalty": 1.12, "num_ctx": 8192})
        self.assertEqual(motor, c.Motor("ollama", "vitaband-coach"))
        self.assertIn(40, prog)
        self.assertEqual(max(prog), 100)

    def test_instala_ollama_solo_si_falta(self):
        red, instalador = RedFalsa(), MagicMock()
        with patch.object(prov, "_urlopen", red), patch.object(c, "modelos_ollama", return_value=None), \
                patch.object(prov, "binario_ollama", return_value=None):
            prov.instalar("qwen2.5", lambda p, t: None, capacidad=self.CAP, instalador=instalador,
                          esperar=lambda b, s: True)
        instalador.assert_called_once()
        self.assertEqual(red.peticiones[0][1]["model"], "qwen2.5")

    def test_rechaza_modelos_fuera_del_catalogo_y_disco_insuficiente(self):
        with self.assertRaises(prov.ErrorProvision):
            prov.instalar("llama3:70b", lambda p, t: None, capacidad=self.CAP)
        red = MagicMock()
        with patch.object(prov, "_urlopen", red), self.assertRaises(prov.ErrorProvision):
            prov.instalar("qwen2.5", lambda p, t: None, capacidad=prov.Capacidad(16.0, 3.0))
        red.assert_not_called()

    def test_error_del_servidor_se_propaga(self):
        def falla(peticion, timeout=None):
            return RespuestaNdjson([{"error": "sin espacio"}])
        with patch.object(prov, "_urlopen", falla), patch.object(c, "modelos_ollama", return_value=[]):
            with self.assertRaises(prov.ErrorProvision):
                prov.instalar("qwen2.5:1.5b", lambda p, t: None, capacidad=self.CAP)


class TestWidgetConsentimiento(unittest.TestCase):
    def _widget(self, cap, motor=c.MOTOR_OFFLINE):
        self.red = MagicMock()
        self.patches = [patch.object(c, "detectar_motor", return_value=motor),
                        patch.object(prov, "detectar_capacidad_equipo", return_value=cap),
                        patch.object(prov, "_urlopen", self.red), patch("urllib.request.urlopen", self.red)]
        for p in self.patches:
            p.start()
        repo = RepositorioHistorial(":memory:", usuario_id=1)
        vm = VitaBandViewModel(MagicMock(), repositorio=repo, reloj=Reloj())
        w = CoachIaWidget(vm)
        w._construir()
        esperar(w._hilo_det)
        return w

    def tearDown(self):
        for p in getattr(self, "patches", []):
            p.stop()

    def test_falta_motor_entra_en_consent_required_sin_trafico(self):
        w = self._widget(prov.Capacidad(8, 100))
        self.assertEqual(w.estado, prov.CONSENT_REQUIRED)
        self.assertFalse(w.tarjeta_consentimiento.isHidden())
        self.assertEqual(w.lbl_motor.text(), "Motor: Análisis Offline")
        self.assertIn("100,0 GB", w.lbl_consent_espacio.text())
        self.assertEqual([w.combo_modelo.itemText(i) for i in range(2)],
                         ["Qwen 2.5 Ligero (1.5B) · 1,0 GB (Recomendado)", "Qwen 2.5 Completo (7B) · 4,7 GB"])
        self.assertEqual(w.combo_modelo.currentData(), "qwen2.5:1.5b")
        self.red.assert_not_called()
        w.close()

    def test_equipo_potente_recomienda_y_preselecciona_el_completo(self):
        w = self._widget(prov.Capacidad(32, 200))
        self.assertEqual(w.combo_modelo.currentText(), "Qwen 2.5 Completo (7B) · 4,7 GB (Recomendado)")
        self.assertEqual(w.combo_modelo.currentData(), "qwen2.5")
        self.assertEqual(w.combo_modelo.itemText(0), "Qwen 2.5 Ligero (1.5B) · 1,0 GB")
        w.close()

    def test_poco_disco_recomienda_el_ligero(self):
        w = self._widget(prov.Capacidad(32, 10))
        self.assertEqual(w.combo_modelo.currentText(), "Qwen 2.5 Ligero (1.5B) · 1,0 GB (Recomendado)")
        w.close()

    def test_motor_listo_no_muestra_tarjeta(self):
        w = self._widget(prov.Capacidad(32, 200), motor=c.Motor("ollama", "vitaband-coach"))
        self.assertEqual(w.estado, prov.READY)
        self.assertTrue(w.tarjeta_consentimiento.isHidden())
        w.close()

    def test_no_continuar_offline_conserva_el_chat_sin_red(self):
        w = self._widget(prov.Capacidad(8, 100))
        w.btn_no_offline.click()
        self.assertTrue(w.tarjeta_consentimiento.isHidden())
        self.assertFalse(w.btn_activar_qwen.isHidden())
        self.assertEqual(w.btn_activar_qwen.text(), "Activar IA Qwen")
        w.enviar("¿Estoy recuperado para entrenar hoy?")
        self.assertEqual(w.motor.tipo, "offline")
        self.assertEqual(len(w.memoria.turnos), 1)
        w.reconectar()
        esperar(w._hilo_det)
        self.assertTrue(w.tarjeta_consentimiento.isHidden())          # no vuelve a preguntar
        self.red.assert_not_called()
        w.btn_activar_qwen.click()                                    # …pero puede reabrirse
        self.assertFalse(w.tarjeta_consentimiento.isHidden())
        self.assertTrue(w.btn_activar_qwen.isHidden())
        w.close()

    def test_aceptar_instala_exactamente_el_modelo_del_desplegable(self):
        w = self._widget(prov.Capacidad(32, 200))
        w.combo_modelo.setCurrentIndex(0)                              # el usuario elige el ligero aunque se recomiende el otro
        pedidos = []

        def falso(model_id, progreso, **k):
            pedidos.append(model_id)
            progreso(50, "Descargando… 50 %")
            return c.Motor("ollama", "vitaband-coach")

        with patch.object(prov, "instalar", falso), patch.object(c, "detectar_motor",
                                                                  return_value=c.Motor("ollama", "vitaband-coach")):
            w.btn_si_instalar.click()
            self.assertEqual(w.estado, prov.INSTALLING)
            self.assertFalse(w.btn_si_instalar.isEnabled())
            esperar(w._hilo_inst)
            esperar(w._hilo_det)
        self.assertEqual(pedidos, ["qwen2.5:1.5b"])
        self.assertEqual(w.estado, prov.READY)
        self.assertTrue(w.tarjeta_consentimiento.isHidden())
        self.assertEqual(w.lbl_motor.text(), "Motor: Ollama (vitaband-coach)")
        w.close()

    def test_fallo_de_instalacion_mantiene_el_offline(self):
        w = self._widget(prov.Capacidad(8, 100))
        with patch.object(prov, "instalar", side_effect=prov.ErrorProvision("sin espacio")):
            w.btn_si_instalar.click()
            esperar(w._hilo_inst)
        self.assertEqual(w.estado, prov.ERROR)
        self.assertIn("sin espacio", w.lbl_instalacion.text())
        self.assertTrue(w.btn_si_instalar.isEnabled())
        self.assertEqual(w.motor.tipo, "offline")
        w.close()


if __name__ == "__main__":
    unittest.main()
