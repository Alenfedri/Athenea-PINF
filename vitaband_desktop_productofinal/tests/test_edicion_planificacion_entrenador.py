"""Edición de sesiones, entrenamiento estructurado, calendario y Modo Entrenador (.vbcoach)."""
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from domain.hrv import ResultadoHrv
from services import edicion_sesiones as ed
from services import modo_entrenador as me
from services import planificacion_entrenamiento as pl
from services.repositorio_historial import RepositorioHistorial

_app = QApplication.instance() or QApplication([])
T0 = int(datetime(2026, 11, 18, 9, 0).timestamp())


def sesion(n=600, bpm=lambda i: 120 + (i % 60), rr_ms=800.0):
    ts = tuple(T0 + i for i in range(n))
    rr = tuple([rr_ms] * int(n / (rr_ms / 1000)))
    return ed.Sesion(T0, T0 + n, ts, tuple(float(bpm(i)) for i in range(n)), tuple([16.0] * n), rr)


class TestEdicion(unittest.TestCase):
    def test_recorte_recalcula_metricas(self):
        s = sesion(600, lambda i: 100 if i < 300 else 170)
        r = ed.recortar_sesion(s, T0 + 300, T0 + 599)
        m, m0 = ed.metricas(r), ed.metricas(s)
        self.assertEqual(r.inicio_ts, T0 + 300)
        self.assertEqual(m.duracion_s, 299)
        self.assertAlmostEqual(m.bpm_medio, 170)
        self.assertAlmostEqual(m.bpm_max, 170)
        self.assertLess(m0.bpm_medio, 140)
        self.assertGreater(m.trimp, 0)
        self.assertAlmostEqual(sum(m.zonas_s), m.duracion_s, delta=3)
        self.assertLess(len(r.rr_ms), len(s.rr_ms))
        with self.assertRaises(ValueError):
            ed.recortar_sesion(s, T0 + 10, T0 + 10)

    def test_artefactos_rr_se_interpolan_sin_cambiar_la_duracion(self):
        rr = [800.0] * 30
        rr[10], rr[20], rr[21] = 400.0, 1500.0, 1100.0
        limpio, n = ed.corregir_artefactos_rr(rr)
        self.assertEqual(n, 3)
        self.assertAlmostEqual(sum(limpio), sum(rr), places=6)
        self.assertTrue(all(abs(x - 800) < 150 for x in limpio))
        self.assertAlmostEqual(limpio[0], 800.0, delta=25)
        self.assertEqual(ed.corregir_artefactos_rr([800.0] * 30), ([800.0] * 30, 0))
        s, n2 = ed.limpiar_sesion(ed.Sesion(T0, T0 + 24, rr_ms=tuple(rr)))
        self.assertEqual((n2, len(s.rr_ms)), (3, 30))

    def test_dividir_y_fusionar_son_consistentes(self):
        s = sesion(600, lambda i: 100 if i < 200 else 160)
        a, b = ed.dividir_sesion(s, T0 + 200)
        ma, mb, m = ed.metricas(a), ed.metricas(b), ed.metricas(s)
        self.assertEqual((ma.duracion_s, mb.duracion_s), (200, 400))
        self.assertAlmostEqual(ma.bpm_medio, 100)
        self.assertAlmostEqual(mb.bpm_medio, 160)
        self.assertEqual(len(a.ts) + len(b.ts), len(s.ts))
        self.assertEqual(len(a.rr_ms) + len(b.rr_ms), len(s.rr_ms))
        f = ed.fusionar_sesiones(b, a)                                   # orden indiferente
        self.assertEqual((f.inicio_ts, f.fin_ts, len(f.ts)), (s.inicio_ts, s.fin_ts, len(s.ts)))
        self.assertAlmostEqual(ed.metricas(f).bpm_medio, m.bpm_medio)
        self.assertAlmostEqual(ed.metricas(f).trimp, m.trimp, delta=0.5)
        with self.assertRaises(ValueError):
            ed.dividir_sesion(s, T0 - 5)
        with self.assertRaises(ValueError):
            ed.fusionar_sesiones(s, a)

    def test_persistencia_en_sqlite(self):
        repo = RepositorioHistorial(":memory:", usuario_id=1)
        otro = RepositorioHistorial(":memory:", usuario_id=2)

        def crear(uid, t0, n):
            aid = repo.guardar_actividad(uid, t0, t0 + n, "carrera")
            for i in range(n):
                repo.guardar_medicion(130, datetime.fromtimestamp(t0 + i), uid=f"{uid}{i}", actividad_id=aid)
            return aid

        a = crear("a", T0, 600)
        self.assertTrue(ed.aplicar_recorte(repo, a, T0 + 100, T0 + 500))
        act = repo.obtener_actividad(a)
        self.assertEqual((act.inicio_ts, act.fin_ts, len(repo.mediciones_de_actividad(a))), (T0 + 100, T0 + 500, 401))
        b = ed.aplicar_division(repo, a, T0 + 300)
        self.assertEqual(repo.obtener_actividad(a).fin_ts, T0 + 300)
        self.assertEqual(repo.obtener_actividad(b).inicio_ts, T0 + 300)
        self.assertEqual(len(repo.mediciones_de_actividad(a)) + len(repo.mediciones_de_actividad(b)), 401)
        self.assertEqual(ed.aplicar_fusion(repo, b, a), a)
        self.assertEqual(repo.obtener_actividad(a).fin_ts, T0 + 500)
        self.assertIsNone(repo.obtener_actividad(b))
        self.assertEqual(len(repo.mediciones_de_actividad(a)), 401)
        self.assertIsNone(ed.aplicar_division(repo, a, T0 - 1))
        s = ed.cargar_sesion(repo, a)
        self.assertEqual(len(s.ts), 401)
        self.assertIsNone(ed.cargar_sesion(otro, a))


class TestBloques(unittest.TestCase):
    def entreno(self):
        return pl.EntrenamientoEstructurado("Series", [
            pl.Bloque("Calentamiento", 600, 0),
            pl.Repeticion(4, (pl.Bloque("Fuerte", 240, 3), pl.Bloque("Suave", 120, 0))),
            pl.Bloque("Enfriamiento", 300, 0)])

    def test_expansion_y_resumen(self):
        e = self.entreno()
        self.assertEqual(len(e.bloques_planos()), 10)
        self.assertEqual(e.duracion_total_s, 600 + 4 * 360 + 300)
        self.assertEqual(e.resumen(), "10 min Z1 + 4 × [4 min Z4 / 2 min Z1] + 5 min Z1")
        self.assertEqual(pl.EntrenamientoEstructurado.desde_dict(json.loads(json.dumps(e.a_dict()))).resumen(), e.resumen())
        with self.assertRaises(ValueError):
            pl.Bloque("x", 0, 1)
        with self.assertRaises(ValueError):
            pl.Bloque("x", 10, 5)

    def test_ejecutor_secuencia_cuenta_atras_y_zona(self):
        piloto = SimpleNamespace(zona=None)
        ex = pl.EjecutorBloques(self.entreno())
        with self.assertRaises(RuntimeError):
            ex.actualizar(0)
        ex.iniciar(1000)
        s = ex.actualizar(1000, piloto)
        self.assertEqual((s.indice, s.zona, s.restante_bloque_s, s.cambio_de_bloque), (0, 0, 600, True))
        self.assertEqual(piloto.zona, 0)
        s = ex.actualizar(1300, piloto)
        self.assertEqual((s.restante_bloque_s, s.progreso_bloque, s.cambio_de_bloque), (300, 0.5, False))
        s = ex.actualizar(1000 + 600 + 10, piloto)                         # primera serie fuerte
        self.assertEqual((s.indice, s.zona, piloto.zona), (1, 3, 3))
        self.assertIn("(1/4)", s.bloque.nombre)
        s = ex.actualizar(1000 + 600 + 240 + 5, piloto)                    # recuperación
        self.assertEqual((s.zona, piloto.zona), (0, 0))
        total = self.entreno().duracion_total_s
        self.assertAlmostEqual(ex.actualizar(1000 + total / 2, piloto).progreso_total, 0.5)
        s = ex.actualizar(1000 + total + 1, piloto)
        self.assertTrue(s.terminado and ex.terminado)
        self.assertIsNone(piloto.zona)
        self.assertFalse(ex.activo)


class TestCalendario(unittest.TestCase):
    def test_agenda_y_cumplimiento_semanal(self):
        repo = RepositorioHistorial(":memory:", usuario_id=1)
        otro = RepositorioHistorial(":memory:", usuario_id=2)
        g = pl.GestorCalendarioPlanificado(repo)
        lunes = date(2026, 11, 16)
        self.assertEqual(g.cumplimiento_semanal(lunes).pct, None)
        g.agendar(lunes, "Rodaje", 60)
        g.agendar(lunes + timedelta(days=2), "Series", 40, entrenamiento=pl.EntrenamientoEstructurado(
            "S", [pl.Bloque("a", 600, 2)]))
        g.agendar(lunes + timedelta(days=9), "Otra semana", 90)
        self.assertEqual(len(g.entre(lunes, lunes + timedelta(days=6))), 2)
        self.assertEqual(len(g.del_mes(2026, 11)), 3)
        self.assertEqual(g.del_mes(2026, 11)[1].plan["nombre"], "S")
        self.assertEqual(len(pl.GestorCalendarioPlanificado(otro).del_mes(2026, 11)), 0)
        # ejecutado: una sesión de 50 min
        ini = int(datetime.combine(lunes, datetime.min.time()).timestamp()) + 8 * 3600
        a = repo.guardar_actividad("x", ini, ini + 3000, "carrera")
        for i in range(0, 3000, 10):
            repo.guardar_medicion(140, datetime.fromtimestamp(ini + i), uid=f"m{i}", actividad_id=a)
        c = g.cumplimiento_semanal(lunes + timedelta(days=3))
        self.assertEqual((c.lunes, c.sesiones_plan, c.sesiones_real), (lunes, 2, 1))
        self.assertAlmostEqual(c.minutos_real, 50)
        self.assertAlmostEqual(c.pct, 100 * (0.5 + 0.5) / 2)               # sesiones 1/2, minutos 50/100
        for _ in range(2):
            ini += 4000
            b = repo.guardar_actividad(f"y{ini}", ini, ini + 3000, "carrera")
        self.assertEqual(g.cumplimiento_semanal(lunes).sesiones_real, 3)
        self.assertEqual(g.cumplimiento_semanal(lunes).pct, 100.0)           # 3 ≥ 2 sesiones y 150 ≥ 100 min
        self.assertTrue(g.eliminar(1))
        self.assertFalse(g.eliminar(1))


def _repo_con_datos():
    repo = RepositorioHistorial(":memory:", usuario_id=1)
    hoy = date.today()
    repo.guardar_perfil(30, "M", 70.0, 150)
    for d in range(30):
        repo.guardar_hrv(ResultadoHrv(int(datetime.combine(hoy - timedelta(days=d), datetime.min.time()).timestamp()) + 3600,
                                      45.0, 60.0, 100))
    ini = int(datetime.combine(hoy - timedelta(days=2), datetime.min.time()).timestamp()) + 36000
    a = repo.guardar_actividad("a", ini, ini + 1800, "carrera")
    for i in range(0, 1800, 10):
        repo.guardar_medicion(150, datetime.fromtimestamp(ini + i), uid=f"m{i}", actividad_id=a)
    for k in range(3):
        repo.guardar_marcador(ini - k * 86400, "Café")
    repo.guardar_marcador(ini + 5, "Estrés")
    return repo


class TestModoEntrenador(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.repo = _repo_con_datos()

    def tearDown(self):
        self.tmp.cleanup()

    def test_etiquetas_omitidas_por_defecto(self):
        ruta = me.exportar_coach_pack(self.repo, os.path.join(self.dir, "ana"), dias=42, nombre="Ana García")
        self.assertTrue(ruta.endswith(".vbcoach"))
        texto = open(ruta, encoding="utf-8").read()
        d = json.loads(texto)
        self.assertNotIn("habitos", d)
        self.assertNotIn("Café", texto)
        self.assertNotIn("Estrés", texto)
        self.assertFalse(d["incluye_etiquetas"])
        self.assertEqual(d["alias"], "Ana García")
        self.assertAlmostEqual(d["metricas"]["rmssd_medio_ms"], 45.0)
        self.assertEqual(len(d["pmc"]), 42)
        self.assertEqual(d["sesiones"]["n"], 1)
        self.assertAlmostEqual(sum(d["sesiones"]["zonas_pct"]), 100.0, delta=0.01)

    def test_etiquetas_con_consentimiento_y_alias(self):
        ruta = me.exportar_coach_pack(self.repo, os.path.join(self.dir, "b.vbcoach"), dias=90,
                                      incluir_etiquetas=True, alias_opcional="Atleta-7", nombre="Ana García")
        d = json.load(open(ruta, encoding="utf-8"))
        self.assertEqual(d["alias"], "Atleta-7")
        self.assertNotIn("Ana", json.dumps(d))
        self.assertEqual(d["habitos"][0], {"etiqueta": "Café", "veces": 3})
        self.assertEqual(len(d["pmc"]), 90)
        with self.assertRaises(ValueError):
            me.exportar_coach_pack(self.repo, os.path.join(self.dir, "c"), dias=30)

    def test_bandeja_aislada_sin_sqlite(self):
        origen = me.exportar_coach_pack(self.repo, os.path.join(self.dir, "o"), alias_opcional="A")
        bandeja = os.path.join(self.dir, "data", "coach_packs")
        self.assertEqual(me.listar_coach_packs(bandeja), [])               # arranca vacía
        r1, r2 = me.importar_coach_pack(origen, bandeja), me.importar_coach_pack(origen, bandeja)
        self.assertNotEqual(r1, r2)
        self.assertEqual(len(me.listar_coach_packs(bandeja)), 2)
        open(os.path.join(bandeja, "roto.vbcoach"), "w").write("{no es json")
        self.assertEqual(len(me.listar_coach_packs(bandeja)), 2)
        mala = os.path.join(self.dir, "mala.vbcoach")
        json.dump({"formato": "otro"}, open(mala, "w"))
        with self.assertRaises(ValueError):
            me.importar_coach_pack(mala, bandeja)
        fuente = open(me.__file__, encoding="utf-8").read()
        self.assertNotIn("sqlite3", fuente)                                # el módulo no abre bases de datos
        self.assertNotIn("RepositorioHistorial", fuente)

    def test_pdfs_anonimizados_por_lotes(self):
        a = me.exportar_coach_pack(self.repo, os.path.join(self.dir, "a"), alias_opcional="Maria Lopez")
        b = me.exportar_coach_pack(self.repo, os.path.join(self.dir, "b"), incluir_etiquetas=True, alias_opcional="Juan Perez")
        salida = os.path.join(self.dir, "pdfs")
        rutas = me.exportar_informes_lote_anonimizados([a, b], salida)
        self.assertEqual([os.path.basename(r) for r in rutas], ["informe_sujeto_001.pdf", "informe_sujeto_002.pdf"])
        for r in rutas:
            self.assertGreater(os.path.getsize(r), 0)
            self.assertTrue(open(r, "rb").read(5) == b"%PDF-")
            self.assertNotIn(b"Maria", open(r, "rb").read())


class Reloj:
    t = float(T0)

    def __call__(self):
        return self.t


class TestUi(unittest.TestCase):
    def setUp(self):
        from unittest.mock import MagicMock
        from ui.main_window import MainWindow
        from viewmodel.vitaband_vm import VitaBandViewModel
        self.reloj = Reloj()
        self.repo = RepositorioHistorial(":memory:", usuario_id=1)
        self.vm = VitaBandViewModel(MagicMock(), repositorio=self.repo, reloj=self.reloj)
        self.v = MainWindow(self.vm, "Ana", "ana@correo.es")
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.v.close()
        self.tmp.cleanup()

    def test_pestanas_registradas(self):
        p = self.v.pestanas
        textos = [p.tabText(i) for i in range(p.count())]
        for t in ("Análisis avanzado", "Planificación", "Modo Entrenador"):
            self.assertIn(t, textos)

    def test_builder_carga_en_tiempo_real_y_cambia_zona(self):
        b = self.v.panel_plan
        b._construir()
        b.tabla.setRowCount(0)
        b.anadir_bloque("Calentamiento", 10, 0)
        b.anadir_bloque("Fuerte", 4, 3, grupo=1, veces=4)
        b.anadir_bloque("Suave", 2, 0, grupo=1, veces=4)
        b.anadir_bloque("Enfriamiento", 5, 0)
        self.assertEqual(b.entrenamiento.resumen(), "10 min Z1 + 4 × [4 min Z4 / 2 min Z1] + 5 min Z1")
        b.btn_cargar.click()
        e = self.v.panel_ejecucion
        self.assertTrue(e.btn_iniciar.isEnabled())
        e.iniciar()
        self.assertEqual(self.vm.zona_objetivo, 0)
        self.assertEqual(e.lbl_cuenta.text(), "10:00")
        self.reloj.t = T0 + 600 + 30
        e.tick()
        self.assertEqual(self.vm.zona_objetivo, 3)                      # Piloto Automático → Z4
        self.assertEqual(e.lbl_cuenta.text(), "03:30")
        self.assertGreater(e.barra_bloque.value(), 100)
        self.reloj.t = T0 + 99999
        e.tick()
        self.assertIsNone(self.vm.zona_objetivo)
        self.assertEqual(e.barra_total.value(), 1000)

    def test_builder_valores_invalidos(self):
        b = self.v.panel_plan
        b._construir()
        b.tabla.item(0, 1).setText("abc")
        self.assertIsNone(b.entrenamiento)
        self.assertFalse(b.btn_cargar.isEnabled())

    def test_calendario_agenda_y_cumplimiento(self):
        from PySide6.QtCore import QDate
        pnl = self.v.panel_plan
        pnl._construir()
        hoy = date.today()
        pnl.calendario.setSelectedDate(QDate(hoy.year, hoy.month, hoy.day))
        pnl.edit_nombre.setText("Rodaje")
        pnl.btn_agendar.click()
        self.assertEqual(pnl.lista.count(), 1)
        self.assertIn("0 %", pnl.lbl_cumpl.text())
        self.assertEqual(pnl.barra_cumpl.value(), 0)
        pnl.lista.setCurrentRow(0)
        pnl.btn_borrar.click()
        self.assertEqual(pnl.lista.count(), 0)

    def test_trimmer_dividir_recortar_y_dialogo_coach(self):
        from unittest.mock import patch
        from ui.panel_edicion_sesion import DialogoCoachPack
        aid = self.repo.guardar_actividad("a", T0, T0 + 600, "carrera")
        for i in range(600):
            self.repo.guardar_medicion(130, datetime.fromtimestamp(T0 + i), uid=f"m{i}", actividad_id=aid)
        pe = self.v.vista_actividades.panel_edicion
        pe.set_actividad(aid)
        self.assertTrue(pe.btn_recorte.isEnabled())
        pe.region.setRegion([100, 400])
        pe.btn_dividir.click()
        self.assertEqual(self.repo.obtener_actividad(aid).fin_ts, T0 + 100)
        pe.set_actividad(aid)
        pe.region.setRegion([20, 60])
        with patch("ui.panel_edicion_sesion.confirmar", return_value=True):
            pe.btn_recorte.click()
        a = self.repo.obtener_actividad(aid)
        self.assertEqual((a.inicio_ts, a.fin_ts), (T0 + 20, T0 + 60))
        d = DialogoCoachPack()
        self.assertFalse(d.chk_etiquetas.isChecked())
        self.assertEqual(d.valores(), {"dias": 42, "alias_opcional": "", "incluir_etiquetas": False})

    def test_modo_entrenador_arranca_vacio_e_importa(self):
        from unittest.mock import patch
        from ui.modo_entrenador_widget import ModoEntrenadorWidget
        repo = _repo_con_datos()
        origen = me.exportar_coach_pack(repo, os.path.join(self.tmp.name, "x"), alias_opcional="Atleta-1")
        w = ModoEntrenadorWidget(os.path.join(self.tmp.name, "bandeja"))
        self.assertEqual(w.tabla.rowCount(), 0)
        self.assertFalse(w.btn_pdf.isEnabled())
        with patch("ui.modo_entrenador_widget.QFileDialog.getOpenFileNames", return_value=([origen], "")):
            w.btn_importar.click()
        self.assertEqual(w.tabla.rowCount(), 1)
        self.assertEqual(w.tabla.item(0, 0).text(), "Atleta-1")
        self.assertEqual(w.tabla.item(0, 5).text(), "No compartido")
        destino = os.path.join(self.tmp.name, "pdf")
        with patch("ui.modo_entrenador_widget.QFileDialog.getExistingDirectory", return_value=destino), \
                patch("ui.modo_entrenador_widget.QMessageBox.information"):
            w.btn_pdf.click()
        self.assertGreater(os.path.getsize(os.path.join(destino, "informe_sujeto_001.pdf")), 0)
        w.reiniciar()
        self.assertEqual(w.tabla.rowCount(), 0)

    def test_analisis_avanzado_dibuja(self):
        p = self.v.panel_fisiologia
        p.actualizar()
        self.assertIn("CTL", p.lbl_pmc.text())
        p.btn_recalcular.click()
        self.assertIn("R-R", p.lbl_umbrales.text())


if __name__ == "__main__":
    unittest.main()
