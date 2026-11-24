"""Coach de salud: escudo preventivo, detective de hábitos, HRR + calidad ECG, susurrador, modo vida real e informe clínico."""
import os
import random
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from domain.hrv import ResultadoHrv
from services import coach_ia as c
from services import contexto_coach as cc
from services import inteligencia_biometrica as ib
from services import ollama_provisioner as prov
from services.balance_mental import BalanceCargaMental
from services.planificacion_entrenamiento import GestorCalendarioPlanificado
from services.repositorio_historial import RepositorioHistorial
from ui.coach_ia_widget import CoachIaWidget, DialogoInformeClinico
from ui.main_window import MainWindow
from ui.susurrador_widget import TarjetaSusurro
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])
AHORA = int(datetime.now().timestamp())
HOY = date.fromtimestamp(AHORA)


class Reloj:
    t = float(AHORA)

    def __call__(self):
        return self.t


def _repo():
    return RepositorioHistorial(os.path.join(tempfile.mkdtemp(), "t.db"), usuario_id=1)


def _vm(repo=None, reloj=None):
    repo = repo or _repo()
    return VitaBandViewModel(MagicMock(), repositorio=repo, reloj=reloj or Reloj()), repo


def _hrv_dias(repo, fc_rmssd_por_dia):
    """{días atrás: (fc basal, rmssd)} → una ventana HRV por día a mediodía."""
    for atras, (fc, rm) in fc_rmssd_por_dia.items():
        ts = int(datetime.combine(HOY - timedelta(days=atras), datetime.min.time()).timestamp()) + 12 * 3600
        repo.guardar_hrv(ResultadoHrv(ts, rm, fc, 100))


def _escenario_fatiga(repo, dias_malos=4):
    d = {a: (60.0, 60.0) for a in range(dias_malos, 28)}
    d.update({a: (66.0, 45.0) for a in range(dias_malos)})
    _hrv_dias(repo, d)


def esperar(hilo):
    while hilo is not None and hilo.isRunning():
        _app.processEvents()
        hilo.wait(10)
    _app.processEvents()


class TestEscudoPreventivo(unittest.TestCase):
    def test_detecta_3_dias_de_pulso_alto_y_rmssd_bajo(self):
        repo = _repo()
        _escenario_fatiga(repo, 3)
        a = ib.escudo_preventivo(repo, AHORA)
        self.assertIsNotNone(a)
        self.assertGreaterEqual(a.dias, 3)
        self.assertAlmostEqual(a.subida_bpm, 6.0, delta=0.5)
        self.assertAlmostEqual(a.caida_rmssd_pct, 25.0, delta=1.0)

    def test_no_salta_con_datos_estables_ni_con_solo_2_dias(self):
        repo = _repo()
        _hrv_dias(repo, {a: (60.0, 60.0) for a in range(28)})
        self.assertIsNone(ib.escudo_preventivo(repo, AHORA))
        repo2 = _repo()
        _escenario_fatiga(repo2, 2)
        self.assertIsNone(ib.escudo_preventivo(repo2, AHORA))

    def test_explicacion_sencilla_con_analogias_y_experta_con_cifras(self):
        repo = _repo()
        _escenario_fatiga(repo, 4)
        a = ib.escudo_preventivo(repo, AHORA)
        self.assertIn("batería interna", a.texto(True))
        self.assertIn("descanso activo", a.texto(True))
        self.assertIn("RMSSD −25 %", a.texto(False))

    def test_llega_al_prompt_al_modo_offline_y_al_banner(self):
        vm, repo = _vm()
        _escenario_fatiga(repo, 4)
        self.assertTrue(any("ALERTA PREVENTIVA ACTIVA" in x for x in ib.lineas_contexto(repo, AHORA)))
        self.assertIn("ALERTA PREVENTIVA ACTIVA", vm.contexto_total_coach())
        ctx = vm.contexto_coach()
        self.assertIsNotNone(ctx.alerta)
        r = c.respuesta_offline("¿Estoy recuperado para entrenar hoy?", ctx, sencillo=True)
        self.assertIn("batería interna", r)
        self.assertIn("Zona 1–2", r)
        with patch.object(c, "detectar_motor", return_value=c.MOTOR_OFFLINE):
            w = CoachIaWidget(vm)
            w._construir()
            esperar(w._hilo_det)
        self.assertFalse(w.banner_alerta.isHidden())
        self.assertIn("batería interna", w.banner_alerta.text())
        w.combo_nivel.setCurrentIndex(1)
        self.assertIn("RMSSD", w.banner_alerta.text())
        w.close()


class TestDetectiveDeHabitos(unittest.TestCase):
    def _datos(self, repo, marcados=(10, 8, 6, 4), caida=0.18):
        d = {a: (60.0, 60.0) for a in range(30)}
        reg = ib.RegistroHabitos(repo)
        for a in marcados:
            reg.registrar("Mucha pantalla", HOY - timedelta(days=a))
            d[a - 1] = (60.0, 60.0 * (1 - caida))                       # el día siguiente cae un 18 %
        _hrv_dias(repo, d)
        return reg

    def test_registro_sin_duplicados_y_etiquetas_libres(self):
        repo = _repo()
        reg = ib.RegistroHabitos(repo)
        self.assertEqual(ib.HABITOS_RAPIDOS, ("Dormí mal", "Café tarde", "Mucha pantalla", "Buena hidratación"))
        self.assertTrue(reg.registrar("Dormí mal", HOY))
        self.assertFalse(reg.registrar("Dormí mal", HOY))
        self.assertTrue(reg.registrar("Siesta 30 min", HOY))                # compatible con hábitos personalizados
        self.assertEqual(sorted(reg.del_dia(HOY)), ["Dormí mal", "Siesta 30 min"])

    def test_correlacion_real_con_el_rmssd_del_dia_siguiente(self):
        repo = _repo()
        reg = self._datos(repo)
        hs = [h for h in reg.correlaciones(AHORA) if h.metrica.startswith("recuperación") and h.ambito == "el día siguiente"]
        self.assertEqual(len(hs), 1)
        self.assertAlmostEqual(hs[0].variacion_pct, -18.0, delta=1.0)
        self.assertEqual(hs[0].n, 4)
        self.assertIn("tras «Mucha pantalla», tu recuperación (RMSSD) el día siguiente baja un 18 %", hs[0].texto())

    def test_cruza_tambien_con_el_estres_del_modo_escritorio(self):
        repo = _repo()
        reg = self._datos(repo, caida=0.0)
        bal = BalanceCargaMental(repo)
        for a in range(1, 30):
            marcado = (HOY - timedelta(days=a)) in set(reg.dias("Mucha pantalla"))
            bal.sumar(600, 600, 1200 if marcado else 100, (HOY - timedelta(days=a)).isoformat())
        h = [x for x in reg.correlaciones(AHORA) if x.metrica == "estrés" and x.ambito == "ese día"]
        self.assertTrue(h and h[0].variacion_pct > 50)

    def test_pocos_dias_no_generan_conclusiones(self):
        repo = _repo()
        reg = self._datos(repo, marcados=(5,))
        self.assertEqual(reg.correlaciones(AHORA), [])

    def test_los_hallazgos_llegan_al_coach_online_y_offline(self):
        vm, repo = _vm()
        self._datos(repo)
        self.assertIn("HÁBITOS ↔ CORAZÓN", vm.contexto_total_coach())
        r = c.respuesta_offline("¿Cómo me están afectando mis hábitos?", vm.contexto_coach())
        self.assertIn("Mucha pantalla", r)
        self.assertIn("baja un 18 %", r)

    def test_barra_de_botones_del_coach_registra_en_sqlite(self):
        vm, repo = _vm()
        with patch.object(c, "detectar_motor", return_value=c.MOTOR_OFFLINE):
            w = CoachIaWidget(vm)
            w._construir()
            esperar(w._hilo_det)
        self.assertEqual([b.text() for b in w.botones_habito], list(ib.HABITOS_RAPIDOS))
        w.botones_habito[0].click()
        w.botones_habito[0].click()
        self.assertEqual(vm.habitos_de_hoy(), ["Dormí mal"])
        self.assertIn("ya estaba registrado", w.lbl_habito.text())
        w.close()


class TestHrrYCalidadEcg(unittest.TestCase):
    @staticmethod
    def _serie(t_fin, pico=170, b60=150, b120=135):
        s = [(t_fin - 30 + i, pico) for i in range(31)]
        s += [(t_fin + 60 + i, b60) for i in range(-3, 4)] + [(t_fin + 120 + i, b120) for i in range(-3, 4)]
        return s

    def test_calculo_de_hrr_1_y_2_minutos(self):
        h = ib.calcular_hrr(self._serie(1000), 1000)
        self.assertEqual((h.bpm_pico, h.hrr_1m, h.hrr_2m), (170, 20, 35))
        self.assertIn("20 latidos en el primer minuto", h.texto(True))
        self.assertIn("HRR 1' 20 BPM · HRR 2' 35 BPM", h.texto(False))
        self.assertIsNone(ib.calcular_hrr([(1000, 170)], 1000))

    def test_sesion_cerrada_se_evalua_y_se_guarda(self):
        repo = _repo()
        ini = AHORA - 4000
        a = repo.guardar_actividad("x", ini, ini + 1800, "x")
        for ts, b in self._serie(ini + 1800):
            repo.guardar_medicion(b, datetime.fromtimestamp(ts), uid=f"u{ts}", etiqueta="ACTIVIDAD", actividad_id=a if ts <= ini + 1800 else None,
                                  nivel_actividad=1)
        act = repo.actividades_rango(ini - 1, ini + 2000)[0]
        h = ib.evaluar_sesion_cerrada(repo, act)
        self.assertEqual((h.hrr_1m, h.hrr_2m), (20, 35))
        self.assertEqual(ib.RecuperacionSesiones(repo).ultimo()[1].hrr_1m, 20)

    def test_finalizar_sesion_mide_y_guarda_hrr_a_los_2_minutos(self):
        reloj = Reloj()
        vm, repo = _vm(reloj=reloj)
        medidos = []
        vm.hrr_calculado.connect(medidos.append)
        t0 = reloj.t
        for i in range(40):
            reloj.t = t0 + i
            vm._inteligencia_en_vivo(reloj.t, 170.0)
        reloj.t = t0 + 39
        self.assertTrue(vm.finalizar_sesion())
        fin = reloj.t
        for i in range(1, 131):
            reloj.t = fin + i
            vm._inteligencia_en_vivo(reloj.t, 150.0 if i < 90 else 135.0)
        self.assertEqual(len(medidos), 1)
        self.assertEqual(medidos[0].hrr_1m, 20)
        self.assertEqual(ib.RecuperacionSesiones(repo).ultimo()[1].hrr_2m, 35)

    def test_ecg_limpio_frente_a_pico_aislado_y_electrodo_seco(self):
        rnd = random.Random(1)
        limpio = [800 + rnd.uniform(-60, 60) for _ in range(120)]
        q = ib.analizar_calidad_ecg(limpio)
        self.assertEqual((q.nivel, q.pct_artefactos), ("limpia", 0.0))
        aislado = list(limpio)
        aislado[50] = 120.0                                              # RR < 250 ms imposible
        q = ib.analizar_calidad_ecg(aislado)
        self.assertEqual((q.nivel, q.aislados), ("ruido_aislado", 1))
        self.assertIn("no te preocupes", q.texto(True))
        seco = list(limpio)
        for i in range(40, 60):
            seco[i] = rnd.choice([90.0, 2600.0, 180.0, 1900.0, 300.0])    # electrodo seco: saltos bruscos
        q = ib.analizar_calidad_ecg(seco)
        self.assertEqual(q.nivel, "mal_contacto")
        self.assertIn("humedece los electrodos", q.texto(True))
        self.assertIsNone(ib.analizar_calidad_ecg([800] * 5))

    def test_hrr_y_calidad_llegan_al_coach_offline(self):
        vm, repo = _vm()
        ib.RecuperacionSesiones(repo).guardar(AHORA - 100, ib.Hrr(170, 22, 38))
        rnd = random.Random(2)
        ruido = [800 + rnd.uniform(-50, 50) for _ in range(60)]
        for i in range(30, 45):
            ruido[i] = rnd.choice([90.0, 2600.0, 150.0])
        repo.guardar_rr(AHORA - 3600, ruido)
        ctx = vm.contexto_coach()
        self.assertIn("22 latidos", c.respuesta_offline("¿Cuánto baja mi pulso, mi HRR?", ctx, sencillo=True))
        self.assertIn("humedece", c.respuesta_offline("¿Qué tal la calidad de la señal del electrodo?", ctx, sencillo=True))
        self.assertIn("Última recuperación postesfuerzo", vm.contexto_total_coach())


class TestSusurrador(unittest.TestCase):
    def test_zona_objetivo_del_plan_de_hoy(self):
        repo = _repo()
        self.assertIsNone(ib.zona_objetivo_hoy(repo, HOY))
        g = GestorCalendarioPlanificado(repo)
        g.agendar(HOY, "Rodaje Zona 2", 45)
        self.assertEqual(ib.zona_objetivo_hoy(repo, HOY), 1)
        from services.planificacion_entrenamiento import Bloque, EntrenamientoEstructurado, Paso
        e = EntrenamientoEstructurado("Series", [Paso.simple("Z4", 600, 3), Paso.simple("Z2", 1200, 1)]) if hasattr(Paso, "simple") else None
        if e is not None:
            g.agendar(HOY + timedelta(days=1), "Series", 30, entrenamiento=e)
            self.assertIn(ib.zona_objetivo_hoy(repo, HOY + timedelta(days=1)), (1, 3))

    def test_dispara_tras_mas_de_4_minutos_fuera_de_zona_y_traduce(self):
        s = ib.Susurrador(zona_objetivo=1)
        self.assertIsNone(s.actualizar(0, 158, 190))
        self.assertIsNone(s.actualizar(239, 158, 190))
        msg = s.actualizar(241, 158, 190)
        self.assertIn("cuarta marcha (158 BPM)", msg)
        self.assertIn("hablar sin jadear", msg)
        self.assertIsNone(s.actualizar(300, 158, 190))                    # enfriamiento
        s2 = ib.Susurrador(zona_objetivo=1)
        s2.actualizar(0, 158, 190)
        s2.actualizar(200, 125, 190)                                       # vuelve a la zona: la cuenta se reinicia
        self.assertIsNone(s2.actualizar(300, 158, 190))
        s3 = ib.Susurrador(zona_objetivo=1)
        s3.silenciar()
        s3.actualizar(0, 158, 190)
        self.assertIsNone(s3.actualizar(500, 158, 190))
        self.assertIsNone(ib.Susurrador(None).actualizar(500, 158, 190))

    def test_en_vivo_emite_la_senal_y_la_tarjeta_se_silencia(self):
        reloj = Reloj()
        vm, repo = _vm(reloj=reloj)
        GestorCalendarioPlanificado(repo).agendar(HOY, "Rodaje Zona 2", 45)
        vm.sesion_directo.activa = True
        vistos = []
        vm.susurro.connect(vistos.append)
        t0 = reloj.t
        for i in range(0, 250):
            reloj.t = t0 + i
            vm._inteligencia_en_vivo(reloj.t, 160.0)
        self.assertEqual(len(vistos), 1)
        self.assertIn("marcha", vistos[0])
        host = MagicMock()
        from PySide6.QtWidgets import QWidget
        padre = QWidget()
        padre.resize(900, 600)
        t = TarjetaSusurro(padre)
        t.mostrar(vistos[0])
        self.assertTrue(t._timer.isActive())
        self.assertIn("#D4AF37", t.styleSheet())
        t.silenciado.connect(vm.susurrador.silenciar)
        t.btn_silenciar.click()
        self.assertTrue(vm.susurrador.silenciado)
        self.assertFalse(t._timer.isActive())

    def test_ventana_con_boton_finalizar_y_tarjeta(self):
        vm, _ = _vm()
        v = MainWindow(vm, "Ana")
        self.assertEqual(v.btn_finalizar.text(), "Finalizar sesión")
        self.assertFalse(v.btn_finalizar.isEnabled())
        vm.susurro.emit("Vas en cuarta marcha")
        self.assertFalse(v.tarjeta_susurro.isHidden())
        v.close()
        self.assertFalse(v.tarjeta_susurro._timer.isActive())


class TestModoVidaReal(unittest.TestCase):
    def _hoy(self):
        return date(2026, 11, 18)                                          # miércoles

    def test_detecta_sesion_saltada_y_estres_alto(self):
        repo = _repo()
        hoy = self._hoy()
        self.assertIsNone(ib.detectar_reajuste(repo, hoy))
        g = GestorCalendarioPlanificado(repo)
        g.agendar(hoy - timedelta(days=1), "Rodaje Zona 2", 60)
        m = ib.detectar_reajuste(repo, hoy)
        self.assertEqual(m.sesion_saltada, "Rodaje Zona 2")
        self.assertFalse(m.estres_alto)
        repo2 = _repo()
        BalanceCargaMental(repo2).sumar(1000, 800, 2400, (hoy - timedelta(days=1)).isoformat())
        self.assertTrue(ib.detectar_reajuste(repo2, hoy).estres_alto)

    def test_no_salta_si_ayer_si_entreno(self):
        repo = _repo()
        hoy = self._hoy()
        GestorCalendarioPlanificado(repo).agendar(hoy - timedelta(days=1), "Rodaje", 60)
        ini = int(datetime.combine(hoy - timedelta(days=1), datetime.min.time()).timestamp()) + 8 * 3600
        repo.guardar_actividad("a", ini, ini + 1800, "x")
        self.assertIsNone(ib.detectar_reajuste(repo, hoy))

    def test_reajusta_lo_que_queda_de_semana_acortando_y_suavizando(self):
        repo = _repo()
        hoy = self._hoy()
        g = GestorCalendarioPlanificado(repo)
        g.agendar(hoy - timedelta(days=1), "Saltada", 60)
        g.agendar(hoy + timedelta(days=2), "Series Zona 4", 60, trimp=100.0)
        g.agendar(hoy + timedelta(days=4), "Fondo", 100)
        g.agendar(hoy + timedelta(days=7), "Próxima semana", 60)
        cambios = ib.reajustar_semana(repo, hoy)
        self.assertEqual([(x.minutos_antes, x.minutos_despues) for x in cambios], [(60, 45), (100, 75)])
        s = {x.nombre: x for x in g.entre(hoy - timedelta(days=1), hoy + timedelta(days=8))}
        self.assertIn("Series Zona 4 (suave Z1–2)", s)
        self.assertEqual(s["Próxima semana"].minutos, 60)
        self.assertEqual(s["Saltada"].minutos, 60)
        msg = ib.mensaje_reajuste(ib.MotivoReajuste("Saltada", False), cambios)
        self.assertIn("Sin culpa", msg)
        self.assertIn("no pudiste hacer «Saltada»", msg)

    def test_boton_y_accion_del_coach_ejecutan_el_reajuste(self):
        vm, repo = _vm()
        g = GestorCalendarioPlanificado(repo)
        g.agendar(HOY - timedelta(days=1), "Ayer", 60)
        g.agendar(HOY, "Hoy Zona 2", 60)
        with patch.object(c, "detectar_motor", return_value=c.MOTOR_OFFLINE):
            w = CoachIaWidget(vm)
            w._construir()
            esperar(w._hilo_det)
        self.assertFalse(w.btn_reajustar.isHidden())
        self.assertEqual(w.btn_reajustar.text(), "Reajustar semana sin culpa")
        r = c.respuesta_offline("Quiero reajustar mi semana sin culpa", vm.contexto_coach())
        self.assertIn("[ACCION:REAJUSTAR_SEMANA]", r)
        hechos = []
        w.plan_modificado.connect(lambda: hechos.append(1))
        w._terminar("q", "Tranquilo. [ACCION:REAJUSTAR_SEMANA]", c.MOTOR_OFFLINE)
        self.assertEqual(w.botones_accion[0].text(), "Reajustar semana sin culpa")
        w.botones_accion[0].click()
        self.assertEqual(hechos, [1])
        self.assertIn("(suave Z1–2)", [x.nombre for x in g.entre(HOY, HOY)][0] if HOY.weekday() >= 0 else "")
        self.assertTrue(w.btn_reajustar.isHidden())
        w.close()


class TestInformeClinico(unittest.TestCase):
    def _datos(self):
        vm, repo = _vm()
        _escenario_fatiga(repo, 4)
        ib.RecuperacionSesiones(repo).guardar(AHORA - 5 * 86400, ib.Hrr(170, 20, 35))
        BalanceCargaMental(repo).sumar(7200, 3600, 5400, HOY.isoformat())
        rnd = random.Random(3)
        repo.guardar_rr(AHORA - 7200, [800 + rnd.uniform(-50, 50) for _ in range(60)])
        return vm, repo

    def test_dossier_estructurado_del_ultimo_mes(self):
        vm, _ = self._datos()
        t = vm.informe_clinico()
        for k in ("banda pectoral ECG", "PULSO BASAL", "VARIABILIDAD CARDÍACA (RMSSD)", "tendencia a la baja",
                  "HRR 1' medio 20 BPM", "1.5 h en estrés sostenido", "CALIDAD DEL TRAZADO ECG: 100 %",
                  "OBSERVACIONES RELEVANTES", "Alerta preventiva", "no sustituyen una valoración médica"):
            self.assertIn(k, t)

    def test_sin_datos_no_falla(self):
        vm, _ = _vm()
        t = vm.informe_clinico()
        self.assertIn("sin mediciones en reposo", t)
        self.assertIn("Sin hallazgos destacables", t)

    def test_modal_copiar_y_exportar_txt_y_pdf(self):
        vm, _ = self._datos()
        with patch.object(c, "detectar_motor", return_value=c.MOTOR_OFFLINE):
            w = CoachIaWidget(vm)
            w._construir()
            esperar(w._hilo_det)
        self.assertEqual(w.btn_informe.text(), "Preparar resumen para mi médico")
        w.btn_informe.click()
        d = w.dialogo_informe
        self.assertIsInstance(d, DialogoInformeClinico)
        d.btn_copiar.click()
        self.assertEqual(QApplication.clipboard().text(), d.txt.toPlainText())
        carpeta = tempfile.mkdtemp()
        d.exportar_txt(os.path.join(carpeta, "i.txt"))
        d.exportar_pdf(os.path.join(carpeta, "i.pdf"))
        self.assertIn("PULSO BASAL", open(os.path.join(carpeta, "i.txt"), encoding="utf-8").read())
        self.assertTrue(open(os.path.join(carpeta, "i.pdf"), "rb").read(5).startswith(b"%PDF"))
        d.close()
        w.close()


class TestPromptYVersion(unittest.TestCase):
    def test_version_y_pilares_en_ambos_niveles_y_en_el_modelo(self):
        self.assertEqual(prov.COACH_PROMPT_VERSION, "v5.0")
        for nivel in (cc.NIVEL_SENCILLO, cc.NIVEL_EXPERTO):
            p = cc.prompt_sistema(nivel)
            for k in ("ESCUDO PREVENTIVO", "DETECTIVE DE HÁBITOS", "MODO VIDA REAL", "Preparar resumen para mi médico",
                      "REAJUSTAR_SEMANA", "humedecer los electrodos"):
                self.assertIn(k, p)
        self.assertIn("ESCUDO PREVENTIVO", cc.PROMPT_MAESTRO)

    def test_se_actualiza_vitaband_coach_sin_descargar_al_cambiar_la_version(self):
        cuerpos = []

        def falso(peticion, timeout=None):
            import json
            cuerpos.append((peticion.full_url, json.loads(peticion.data.decode())))

            class R:
                def __enter__(s): return s
                def __exit__(s, *a): return False
                def __iter__(s): return iter([b'{"status":"success"}\n'])
            return R()
        with patch.object(prov, "_urlopen", falso), patch.object(c, "modelos_ollama", return_value=["vitaband-coach:latest", "qwen2.5:1.5b"]):
            self.assertTrue(prov.preparar_coach(version_guardada="v3.0"))
            self.assertFalse(prov.preparar_coach(version_guardada="v5.0"))
        self.assertEqual([u.rsplit("/", 1)[1] for u, _ in cuerpos], ["create"])
        self.assertIn("MODO VIDA REAL", cuerpos[0][1]["system"])

    def test_accion_reajustar_semana_se_extrae(self):
        t, a = cc.extraer_acciones("Tranquilo. [ACCION:REAJUSTAR_SEMANA]")
        self.assertEqual(a, ["REAJUSTAR_SEMANA"])


if __name__ == "__main__":
    unittest.main()
