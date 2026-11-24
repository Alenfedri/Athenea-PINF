"""Modo Escritorio (Pausa por estrés): detector ECG, overlay de respiración guiada, bandeja y balance en SQLite."""
import os
import tempfile
import unittest
from datetime import date
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from domain import estres_cognitivo as ec
from services.balance_mental import BalanceCargaMental, BalanceDia
from services.repositorio_historial import RepositorioHistorial
from ui import modo_escritorio as me
from ui.main_window import MainWindow
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])


class Reloj:
    t = 1_800_000_000.0

    def __call__(self):
        return self.t


def _repo():
    return RepositorioHistorial(os.path.join(tempfile.mkdtemp(), "t.db"), usuario_id=1)


class TestDetector(unittest.TestCase):
    def test_clasificacion_umbrales(self):
        self.assertEqual(ec.clasificar_instante(68, 45), ec.CALMA)
        self.assertEqual(ec.clasificar_instante(70, 38), ec.CALMA)
        self.assertEqual(ec.clasificar_instante(70, 30), ec.TENSION)
        self.assertEqual(ec.clasificar_instante(72, 20), ec.TENSION)          # RMSSD bajo pero sin subida de pulso
        self.assertEqual(ec.clasificar_instante(70, 50, basal=60), ec.TENSION)  # subida moderada de pulso basal
        self.assertEqual(ec.clasificar_instante(100, 20), ec.ESTRES)
        self.assertEqual(ec.clasificar_instante(78, 20, basal=62), ec.ESTRES)    # +15 sobre basal
        self.assertIsNone(ec.clasificar_instante(None, 30))

    def test_verde_ambar_rojo_dinamico(self):
        m = ec.MonitorEstresCognitivo()
        self.assertEqual(m.actualizar(66, 55, 0).estado, ec.CALMA)
        self.assertEqual(m.actualizar(70, 31, 1).estado, ec.TENSION)
        self.assertEqual(m.actualizar(102, 18, 2).estado, ec.ESTRES)
        self.assertEqual([ec.COLORES[e] for e in ec.ESTADOS], ["#10B981", "#F59E0B", "#EF4444"])

    def test_estres_sostenido_20s_y_enfriamiento_5min(self):
        m = ec.MonitorEstresCognitivo()
        alertas = [m.actualizar(105, 18, t).alerta for t in range(0, 19)]
        self.assertFalse(any(alertas))                                        # 18 s: aún no
        self.assertTrue(m.actualizar(105, 18, 20).alerta)                     # 20 s continuos
        self.assertFalse(any(m.actualizar(105, 18, t).alerta for t in range(21, 320)))   # enfriamiento
        self.assertTrue(m.actualizar(105, 18, 321).alerta)                    # pasados 5 min

    def test_una_pausa_en_el_estres_reinicia_la_cuenta(self):
        m = ec.MonitorEstresCognitivo()
        for t in range(0, 15):
            m.actualizar(105, 18, t)
        m.actualizar(70, 55, 15)                                              # vuelve la calma
        self.assertFalse(any(m.actualizar(105, 18, t).alerta for t in range(16, 30)))

    def test_acumula_segundos_por_estado_sin_contar_huecos(self):
        m = ec.MonitorEstresCognitivo()
        m.actualizar(66, 55, 0)
        m.actualizar(66, 55, 2)
        m.actualizar(70, 30, 4)
        m.actualizar(70, 30, 6)
        m.actualizar(70, 30, 600)                                             # hueco largo: no suma
        ac = m.vaciar_acumulado()
        self.assertEqual((ac[ec.CALMA], ac[ec.TENSION], ac[ec.ESTRES]), (4.0, 2.0, 0.0))
        self.assertEqual(m.vaciar_acumulado()[ec.CALMA], 0.0)


class TestBalanceSqlite(unittest.TestCase):
    def test_persistencia_y_consulta(self):
        repo = _repo()
        b = BalanceCargaMental(repo)
        self.assertEqual(b.dia().total_s, 0)
        self.assertEqual(b.dia().texto(), "Aún sin datos de hoy")
        b.sumar(60, 30, 10, "2026-11-20")
        b.sumar(40, 0, 10, "2026-11-20")
        d = b.dia("2026-11-20")
        self.assertEqual((d.calma_s, d.tension_s, d.estres_s), (100, 30, 20))
        self.assertAlmostEqual(d.porcentajes()[0], 100 / 150 * 100)
        self.assertEqual(b.dia("2026-11-19"), BalanceDia("2026-11-19"))
        b.sumar(5, 0, 0)
        self.assertEqual(b.dia(date.today().isoformat()).calma_s, 5)
        b2 = BalanceCargaMental(repo)                                         # reabrir: mismos datos, esquema idempotente
        self.assertEqual(b2.dia("2026-11-20").calma_s, 100)


class TestOverlay(unittest.TestCase):
    def test_fases_de_respiracion(self):
        self.assertEqual(me.fase_respiracion(0)[0], "Inhala")
        self.assertEqual(me.fase_respiracion(3.9)[0], "Inhala")
        self.assertEqual(me.fase_respiracion(4.1)[0], "Exhala")
        self.assertEqual(me.fase_respiracion(10.5)[0], "Inhala")
        self.assertAlmostEqual(me.fase_respiracion(0)[1], 0.0)
        self.assertAlmostEqual(me.fase_respiracion(4.0)[1], 1.0)
        self.assertAlmostEqual(me.fase_respiracion(10.0)[1], 0.0, places=6)

    def test_ciclo_completo_y_cierre_limpio_de_timers(self):
        o = me.PausaEstresOverlay()
        self.assertTrue(o.windowFlags() & me.Qt.WindowStaysOnTopHint)
        o.iniciar(88.0, 24.0)
        self.assertTrue(o._timer.isActive())
        o.actualizar_datos(80.0, 31.0)
        self.assertEqual(o.descenso_bpm, 8.0)
        self.assertIn("RMSSD 31", o.lbl_datos.text())
        for _ in range(30):
            o._tick(1.0)
        self.assertEqual(o.lbl_tiempo.text(), "30 s")
        for _ in range(35):
            o._tick(1.0)
        self.assertTrue(o.finalizada)
        self.assertEqual(o.lbl_fase.text(), "Pausa completada")
        hechos = []
        o.completada.connect(lambda: hechos.append(1))
        o.btn_completar.click()
        self.assertEqual(hechos, [1])
        self.assertFalse(o._timer.isActive())
        self.assertFalse(o.isVisible())

    def test_posponer_y_fundido_sin_efecto_residual(self):
        o = me.PausaEstresOverlay()
        o.iniciar()
        o._anim.stop()
        o._fin_animacion()
        self.assertIsNone(o.graphicsEffect())
        pos = []
        o.pospuesta.connect(lambda: pos.append(1))
        o.btn_posponer.click()
        self.assertEqual(pos, [1])
        self.assertFalse(o._timer.isActive())

    def test_icono_de_bandeja_por_estado(self):
        for e in ec.ESTADOS:
            ic = me.icono_estado(ec.COLORES[e])
            self.assertFalse(ic.isNull())
            self.assertFalse(ic.pixmap(32, 32).isNull())


class TestIntegracion(unittest.TestCase):
    def setUp(self):
        self.reloj = Reloj()
        self.repo = _repo()
        self.vm = VitaBandViewModel(MagicMock(), repositorio=self.repo, reloj=self.reloj)
        self.v = MainWindow(self.vm, "Ana")
        self.c = self.v.controlador_escritorio

    def tearDown(self):
        self.v.close()
        self.vm.cerrar()

    def test_activar_muestra_la_pildora_y_desactivar_la_oculta(self):
        self.assertTrue(self.v.pildora_estres.isHidden())
        self.v.chk_escritorio.setChecked(True)
        self.assertTrue(self.c.activo)
        self.assertFalse(self.v.pildora_estres.isHidden())
        self.assertEqual(self.v.pildora_estres.btn_estado.text(), "Vigilancia estrés: ACTIVA")
        self.assertEqual(self.v.pildora_estres.btn_minimizar.text(), "Minimizar a bandeja")
        self.assertTrue(self.vm.modo_escritorio)                              # el aviso clásico sigue funcionando
        self.assertTrue(self.v.pildora_estres._timer.isActive())
        self.v.chk_escritorio.setChecked(False)
        self.assertFalse(self.c.activo)
        self.assertTrue(self.v.pildora_estres.isHidden())
        self.assertFalse(self.v.pildora_estres._timer.isActive())

    def test_bandeja_solo_si_esta_disponible(self):
        self.v.chk_escritorio.setChecked(True)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.assertIsNotNone(self.c.bandeja)
            self.assertEqual([a.text() for a in self.c.acciones_bandeja],
                             ["Restaurar VitaBand App", "Simular alerta de estrés (Demo)", "Desactivar Modo Escritorio"])
        else:
            self.assertIsNone(self.c.bandeja)
            self.c.minimizar_a_bandeja()                                      # sin bandeja no rompe ni oculta
        self.v.chk_escritorio.setChecked(False)
        self.assertIsNone(self.c.bandeja)

    def test_cambio_de_estado_y_disparo_automatico(self):
        self.v.chk_escritorio.setChecked(True)
        self.c.procesar(66, 55, 0)
        self.assertEqual(self.v.pildora_estres.punto.color, ec.COLORES[ec.CALMA])
        self.c.procesar(72, 30, 1)
        self.assertEqual(self.v.pildora_estres.punto.color, ec.COLORES[ec.TENSION])
        for t in range(2, 24):
            self.c.procesar(104, 18, t)
        self.assertEqual(self.v.pildora_estres.punto.color, ec.COLORES[ec.ESTRES])
        self.assertEqual(self.c.pausas_lanzadas, 1)
        self.assertTrue(self.c.overlay.isVisible())
        self.c.overlay.btn_posponer.click()
        self.assertFalse(self.c.overlay._timer.isActive())

    def test_demo_desde_el_menu_de_modos_de_pantalla(self):
        self.assertEqual(self.v.btn_demo_pausa.text(), "Probar Pausa por Estrés (Demo)")
        self.v.btn_demo_pausa.click()
        self.assertEqual(self.c.pausas_lanzadas, 1)
        self.assertTrue(self.c.overlay.isVisible())
        self.assertTrue(self.c.overlay._timer.isActive())

    def test_balance_se_persiste_y_se_sincroniza_con_las_vistas(self):
        self.v.chk_escritorio.setChecked(True)
        for t in range(0, 11):
            self.c.procesar(66, 55, t)
        for t in range(11, 21):
            self.c.procesar(72, 30, t)
        self.c.refrescar_balance()
        d = BalanceCargaMental(self.repo).dia()
        self.assertGreater(d.calma_s, 0)
        self.assertGreater(d.tension_s, 0)
        self.assertIn("Foco calmado", self.v.pildora_estres.lbl_balance.text())
        self.assertIn("Foco calmado", self.v.vista_historial.resumen_balance.lbl.text())

    def test_cierre_de_ventana_detiene_todos_los_timers(self):
        self.v.chk_escritorio.setChecked(True)
        self.c.simular_alerta()
        self.v.close()
        self.assertFalse(self.c._timer_volcado.isActive())
        self.assertFalse(self.v.pildora_estres._timer.isActive())
        self.assertFalse(self.c.overlay._timer.isActive())
        self.assertFalse(self.c.overlay.isVisible())


if __name__ == "__main__":
    unittest.main()
