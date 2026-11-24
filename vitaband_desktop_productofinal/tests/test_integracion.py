"""Integración: ajustes, generador de paquetes demo, arranque/cierre de SesionActiva."""

import json
import os
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from domain.paquete_sync import parsear_paquete
from services.ajustes import Ajustes, AjustesInvalidos
from services.consultas_historial import ConsultasHistorial
from services.repositorio_historial import RepositorioHistorial
from services.servicio_auth import Sesion
from services.servicio_sync import ServicioSync
from tools import generar_paquete_demo as demo
from ui.sesion_activa import SesionActiva

_app = QApplication.instance() or QApplication([])

RAIZ = Path(__file__).resolve().parent.parent
EMAIL = "ana@correo.com"
AHORA = int(time.time())


class TestAjustes(unittest.TestCase):

    def test_valores_por_defecto_con_config_antigua(self):
        a = Ajustes.desde_config({"mqtt": {}, "monitorizacion": {"ventana_segundos": 6}})
        self.assertEqual((a.registro_intervalo_ms, a.periodico_dias, a.actividades_dias), (10_000, 30, 365))
        self.assertEqual((a.carpeta_intercambio, a.sync_intervalo_ms, a.observaciones_intervalo_ms),
                         ("intercambio", 60_000, 3_600_000))

    def test_el_settings_json_del_proyecto_es_valido(self):
        with open(RAIZ / "settings.json", encoding="utf-8") as f:
            config = json.load(f)
        for seccion in ("mqtt", "monitorizacion", "persistencia"):      # las claves antiguas siguen
            self.assertIn(seccion, config)
        a = Ajustes.desde_config(config)
        self.assertEqual((a.registro_intervalo_s, a.periodico_dias, a.actividades_dias, a.carpeta_intercambio),
                         (10, 30, 365, "intercambio"))

    def test_valores_personalizados(self):
        a = Ajustes.desde_config({
            "registro": {"intervalo_s": 5}, "conservacion": {"periodico_dias": 7, "actividades_dias": 90},
            "intercambio": {"carpeta": " datos/mov ", "intervalo_comprobacion_s": 0},
            "observaciones": {"intervalo_min": 0.5},
        })
        self.assertEqual((a.registro_intervalo_ms, a.periodico_dias, a.actividades_dias), (5000, 7, 90))
        self.assertEqual((a.carpeta_intercambio, a.sync_intervalo_ms, a.observaciones_intervalo_ms),
                         ("datos/mov", 0, 30_000))

    def test_rechaza_valores_invalidos(self):
        malos = [
            {"registro": {"intervalo_s": 0}},
            {"registro": {"intervalo_s": "10"}},
            {"registro": {"intervalo_s": True}},
            {"registro": {"intervalo_s": float("nan")}},
            {"registro": []},
            {"conservacion": {"periodico_dias": 0}},
            {"conservacion": {"periodico_dias": 2.5}},
            {"conservacion": {"periodico_dias": 30, "actividades_dias": 10}},
            {"intercambio": {"carpeta": ""}},
            {"intercambio": {"carpeta": 5}},
            {"intercambio": {"intervalo_comprobacion_s": -1}},
            {"observaciones": {"intervalo_min": -5}},
        ]
        for cfg in malos:
            with self.subTest(cfg), self.assertRaises(AjustesInvalidos) as cm:
                Ajustes.desde_config(cfg)
            self.assertIn("settings.json", str(cm.exception))


class TestGeneradorDemo(unittest.TestCase):

    def test_el_paquete_pasa_la_validacion_del_escritorio(self):
        p = demo.generar_paquete(EMAIL, dias=3, actividades=2, ahora_ts=AHORA)
        parsed = parsear_paquete(json.dumps(p).encode(), AHORA)
        self.assertEqual(parsed.usuario, EMAIL)
        self.assertEqual(len(parsed.actividades), 2)
        etiquetas = {m.etiqueta for m in parsed.mediciones}
        self.assertEqual(etiquetas, {"PERIODICO", "ACTIVIDAD", "AMBOS"})
        self.assertGreaterEqual(len(parsed.ecg), 3)                 # una por actividad + los últimos minutos
        self.assertTrue(all(m.ts <= AHORA for m in parsed.mediciones))

    def test_es_determinista_y_la_semilla_cambia_los_uid(self):
        a = demo.generar_paquete(EMAIL, ahora_ts=AHORA, semilla=1)
        b = demo.generar_paquete(EMAIL, ahora_ts=AHORA, semilla=1)
        c = demo.generar_paquete(EMAIL, ahora_ts=AHORA, semilla=2)
        self.assertEqual(a, b)
        self.assertNotEqual({m["uid"] for m in a["mediciones"]}, {m["uid"] for m in c["mediciones"]})

    def test_uids_unicos(self):
        p = demo.generar_paquete(EMAIL, dias=5, actividades=12, ahora_ts=AHORA)
        uids = [m["uid"] for m in p["mediciones"]]
        self.assertEqual(len(uids), len(set(uids)))
        self.assertEqual(len({a["uid"] for a in p["actividades"]}), 12)

    def test_hueco_simulado_y_opcion_sin_huecos(self):
        def mayor_salto(p):
            ts = sorted(m["ts"] for m in p["mediciones"] if m["uid"].startswith("demo1-per-"))
            return max(b - a for a, b in zip(ts, ts[1:]))
        self.assertGreaterEqual(mayor_salto(demo.generar_paquete(EMAIL, dias=3, ahora_ts=AHORA)), 2 * 3600)
        self.assertLessEqual(mayor_salto(demo.generar_paquete(EMAIL, dias=3, ahora_ts=AHORA, con_hueco=False)), 60)

    def test_sin_actividades(self):
        p = demo.generar_paquete(EMAIL, actividades=0, ahora_ts=AHORA)
        self.assertEqual(p["actividades"], [])
        parsear_paquete(json.dumps(p).encode(), AHORA)

    def test_parametros_invalidos(self):
        for kw in ({"dias": 0}, {"actividades": -1}, {"intervalo_s": 5}):
            with self.assertRaises(ValueError):
                demo.generar_paquete(EMAIL, ahora_ts=AHORA, **kw)

    def test_cli_escribe_el_archivo_de_forma_atomica(self):
        with tempfile.TemporaryDirectory() as d:
            carpeta = os.path.join(d, "nueva", "intercambio")
            salida = []
            with patch("builtins.print", side_effect=lambda *a, **k: salida.append(" ".join(map(str, a)))):
                self.assertEqual(demo.main(["--usuario", EMAIL, "--salida", carpeta, "--dias", "1",
                                            "--actividades", "1", "--nombre", "p.json"]), 0)
            self.assertEqual(os.listdir(carpeta), ["p.json"])                # sin restos .tmp
            with open(os.path.join(carpeta, "p.json"), "rb") as f:
                parsear_paquete(f.read(), int(time.time()))
            self.assertTrue(any("Paquete creado" in l for l in salida))

    def test_cli_con_parametros_invalidos(self):
        with patch("sys.stderr"):
            self.assertEqual(demo.main(["--usuario", EMAIL, "--dias", "0"]), 2)

    def test_de_extremo_a_extremo_generador_sync_consultas(self):
        with tempfile.TemporaryDirectory() as d:
            carpeta = os.path.join(d, "i")
            demo.main(["--usuario", EMAIL, "--salida", carpeta, "--dias", "3", "--actividades", "2"])
            repo = RepositorioHistorial(os.path.join(d, "t.db"), 1)
            try:
                sync = ServicioSync(repo, carpeta, EMAIL)
                r = sync.sincronizar()
                self.assertEqual((r.importados, r.rechazados), (1, 0))
                n = repo.contar_mediciones()
                self.assertGreater(n, 4000)
                self.assertEqual(sync.sincronizar().importados, 0)             # sin duplicados
                self.assertEqual(repo.contar_mediciones(), n)

                c = ConsultasHistorial(repo)
                self.assertEqual(len(c.actividades(0, AHORA + 86400)), 2)
                rango = c.rango_disponible()
                s = c.serie("bpm", rango[0], rango[1] + 1)
                self.assertGreaterEqual(len(s.interrupciones), 1)              # la interrupción simulada
                self.assertTrue(c.ecg(AHORA - 600, AHORA).tiene_datos)
            finally:
                repo.cerrar()


class BaseSesion(unittest.TestCase):

    CONFIG_BASE = {
        "mqtt": {"broker_host": "localhost", "broker_port": 1883, "device_id": "vitaband-01"},
        "monitorizacion": {"ventana_segundos": 6},
    }

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.carpeta = os.path.join(self.dir.name, "intercambio")
        self.ruta_bd = os.path.join(self.dir.name, "t.db")
        self.parche = patch("ui.sesion_activa.MqttVitaBandService")
        self.mqtt_cls = self.parche.start()
        self.activas = []

    def tearDown(self):
        for a in self.activas:
            a.liberar()
        self.parche.stop()
        self.dir.cleanup()

    def config(self, **extra):
        c = dict(self.CONFIG_BASE)
        c["intercambio"] = {"carpeta": self.carpeta, "intervalo_comprobacion_s": 0}
        c["observaciones"] = {"intervalo_min": 0}
        c.update(extra)
        return c

    def crear(self, config=None, usuario_id=1, email=EMAIL):
        a = SesionActiva(_app, config or self.config(), Sesion(usuario_id, email, "Ana"), self.ruta_bd)
        self.activas.append(a)
        return a

    def dejar_paquete(self, email=EMAIL, **kw):
        demo.main(["--usuario", email, "--salida", self.carpeta, "--dias", "2", "--actividades", "1"])


class TestSesionActiva(BaseSesion):

    def test_construccion_crea_carpeta_y_aplica_los_ajustes(self):
        cfg = self.config(registro={"intervalo_s": 5}, conservacion={"periodico_dias": 7, "actividades_dias": 90})
        a = self.crear(cfg)
        self.assertTrue(os.path.isdir(self.carpeta))
        self.assertEqual(a.vm._timer_registro.interval(), 5000)
        self.assertEqual((a.vm._dias_periodico, a.vm._dias_actividades), (7, 90))
        self.assertEqual(a.sync.carpeta, self.carpeta)
        self.assertIsNone(a.resultado_arranque)                  # el arranque aún no ha corrido
        self.assertFalse(a.vm._timer_registro.isActive())

    def test_configuracion_antigua_sin_secciones_nuevas(self):
        anterior = os.getcwd()
        os.chdir(self.dir.name)                                   # la carpeta por defecto se crea en el cwd
        try:
            a = SesionActiva(_app, self.CONFIG_BASE, Sesion(1, EMAIL, "Ana"), self.ruta_bd)
            self.activas.append(a)
            self.assertEqual(a.ajustes.carpeta_intercambio, "intercambio")
            self.assertTrue(os.path.isdir(os.path.join(self.dir.name, "intercambio")))
        finally:
            os.chdir(anterior)

    def test_mostrar_arranca_con_la_ventana_visible(self):
        self.dejar_paquete()
        a = self.crear()
        a.mostrar()
        self.assertTrue(a.ventana.isVisible())
        self.assertIsNone(a.resultado_arranque)                  # se difiere un ciclo del bucle de eventos
        _app.processEvents()
        r = a.resultado_arranque
        self.assertIsNotNone(r)
        self.assertEqual(r.errores, ())
        self.assertEqual((r.sync.importados, r.sync.rechazados), (1, 0))
        self.assertGreater(a.repositorio.contar_mediciones(), 1000)
        self.assertGreaterEqual(r.observaciones.total, 1)
        self.assertTrue(a.vm._timer_registro.isActive())
        self.assertIn("Nuevos:", a.ventana.lbl_sync.text())
        self.assertEqual(a.vm.state.syncSincronizados, 1)

    def test_el_arranque_purga_segun_la_configuracion(self):
        cfg = self.config(conservacion={"periodico_dias": 2, "actividades_dias": 5})
        a = self.crear(cfg)
        a.repositorio.guardar_medicion(60, datetime.fromtimestamp(AHORA - 10 * 86400), uid="viejo")
        a.repositorio.guardar_medicion(61, datetime.fromtimestamp(AHORA - 3600), uid="nuevo")
        a.mostrar()
        _app.processEvents()
        self.assertEqual([m.uid for m in a.repositorio.todas_las_mediciones()], ["nuevo"])
        self.assertEqual(a.resultado_arranque.purga.mediciones, 1)

    def test_paquete_de_otro_usuario_se_ignora(self):
        self.dejar_paquete(email="otra@correo.com")
        a = self.crear()
        a.mostrar()
        _app.processEvents()
        self.assertEqual((a.resultado_arranque.sync.importados, a.resultado_arranque.sync.rechazados), (0, 0))
        self.assertEqual(a.repositorio.contar_mediciones(), 0)

    def test_carpeta_imposible_no_impide_arrancar(self):
        bloqueo = os.path.join(self.dir.name, "archivo")
        Path(bloqueo).write_text("x")
        cfg = self.config()
        cfg["intercambio"] = {"carpeta": os.path.join(bloqueo, "dentro"), "intervalo_comprobacion_s": 0}
        a = self.crear(cfg)
        a.mostrar()
        _app.processEvents()
        self.assertEqual(a.resultado_arranque.errores, ())
        self.assertEqual(a.vm.state.syncTexto, "Carpeta de intercambio no encontrada")
        self.assertTrue(a.vm._timer_registro.isActive())

    def test_arranque_con_enlace_registra_mediciones_con_el_temporizador(self):
        cfg = self.config(registro={"intervalo_s": 1})
        a = self.crear(cfg)
        a.vm._timer_registro.setInterval(30)                      # acelera el reloj para el test
        a.mostrar()
        _app.processEvents()
        a.vm.conectar()
        for _ in range(3):
            a.vm.on_paquete_telemetria(1600.0, 72.0, 15.0, 36.5, 0, 255)
        time.sleep(0.15)
        _app.processEvents()
        self.assertGreaterEqual(a.repositorio.contar_mediciones(), 1)

    def test_liberar_vuelca_ecg_detiene_temporizadores_y_es_idempotente(self):
        a = self.crear()
        a.mostrar()
        _app.processEvents()
        a.vm.conectar()
        for _ in range(3):
            a.vm.on_paquete_telemetria(1600.0, 72.0, 15.0, 36.5, 0, 255)
        guardar = MagicMock()
        a.repositorio.guardar_ecg_segundos = guardar
        a.liberar()
        guardar.assert_called_once()                              # el segundo de ECG en curso no se pierde
        self.assertFalse(a.vm._timer_registro.isActive())
        a.mqtt.cerrar_conexion.assert_called_once()
        a.liberar()                                               # segunda llamada: no hace nada ni falla
        a.mqtt.cerrar_conexion.assert_called_once()

    def test_cerrar_antes_de_que_llegue_el_arranque_no_falla(self):
        a = self.crear()
        a.mostrar()
        a.liberar()
        _app.processEvents()                                      # el aviso diferido llega con la sesión ya cerrada
        self.assertIsNone(a.resultado_arranque)

    def test_los_datos_persisten_entre_sesiones_y_se_separan_por_usuario(self):
        self.dejar_paquete()
        a = self.crear()
        a.mostrar()
        _app.processEvents()
        n = a.repositorio.contar_mediciones()
        a.liberar()

        b = self.crear()                                          # mismo usuario: conserva y no reimporta
        b.mostrar()
        _app.processEvents()
        self.assertEqual(b.repositorio.contar_mediciones(), n)
        self.assertEqual(b.resultado_arranque.sync.importados, 0)
        self.assertEqual(b.resultado_arranque.sync.sin_cambios, 1)
        b.liberar()

        c = self.crear(usuario_id=2, email="otra@correo.com")     # otro usuario: no ve nada
        c.mostrar()
        _app.processEvents()
        self.assertEqual(c.repositorio.contar_mediciones(), 0)


if __name__ == "__main__":
    unittest.main()
