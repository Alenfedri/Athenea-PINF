"""Pulido UX v2: Modo Fantasma, Actividades, Coach (input fijo, acciones sin duplicados) y Planificación."""
import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton, QScrollArea

from services import coach_ia as c
from services import inteligencia_biometrica as ib
from services.planificacion_entrenamiento import GestorCalendarioPlanificado
from services.repositorio_historial import RepositorioHistorial
from ui.coach_ia_widget import CoachIaWidget
from ui.main_window import MainWindow
from ui.panel_planificacion import PanelPlanificacion
from ui.vista_actividades import MIN_ALTO_ECG, VistaActividades
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])
HOY = date.today()


def _vm():
    repo = RepositorioHistorial(os.path.join(tempfile.mkdtemp(), "t.db"), usuario_id=1)
    return VitaBandViewModel(MagicMock(), repositorio=repo), repo


def _coach(vm):
    with patch.object(c, "detectar_motor", return_value=c.MOTOR_OFFLINE):
        w = CoachIaWidget(vm)
        w.resize(1200, 800)
        w.show()
        while w._hilo_det is not None and w._hilo_det.isRunning():
            _app.processEvents()
            w._hilo_det.wait(10)
    return w


class TestFantasma(unittest.TestCase):
    def test_etiqueta_completa_y_aviso_si_no_hay_sesion_elegida(self):
        vm, _ = _vm()
        v = MainWindow(vm, "Ana")
        self.assertEqual(v.chk_fantasma.text(), "Modo Fantasma (competir contra sesión previa)")
        self.assertFalse(v.lbl_fantasma.text().endswith("..."))
        self.assertGreaterEqual(v.lbl_fantasma.maximumWidth(), 400)
        v.chk_fantasma.setChecked(True)                                   # sin sesiones guardadas: avisa y se desmarca
        self.assertIn("Aún no hay sesiones", v.lbl_fantasma.text())
        self.assertFalse(v.chk_fantasma.isChecked())
        v.combo_fantasma.addItem("Sesión de ayer", 99)                    # hay selector con opciones: lo enfoca
        v.combo_fantasma.blockSignals(True)
        v.combo_fantasma.setCurrentIndex(0)
        v.combo_fantasma.blockSignals(False)
        v.chk_fantasma.setChecked(True)
        self.assertIn("Elige primero una sesión previa", v.lbl_fantasma.text())
        self.assertTrue(v.chk_fantasma.isChecked())
        v.close()


class TestActividades(unittest.TestCase):
    def test_panel_derecho_vacio_oculto_y_graficas_ecg_visibles(self):
        vm, _ = _vm()
        va = VistaActividades(vm)
        va.show()
        self.assertTrue(va.tarjeta_prs.isHidden())
        self.assertEqual(va.lbl_prs.text(), "")
        self.assertIsInstance(va.scroll_detalle, QScrollArea)
        self.assertIs(va.pestanas_grafica.widget(1), va.scroll_laboratorio)
        self.assertTrue(va.scroll_detalle.widgetResizable())
        self.assertGreaterEqual(MIN_ALTO_ECG, 150)
        self.assertGreaterEqual(va.panel_ecg.vista_general.minimumHeight(), 150)
        self.assertGreaterEqual(va.panel_ecg.vista_detalle.minimumHeight(), 150)
        e = va.panel_edicion
        e._construir()
        self.assertGreaterEqual(e.grafica.minimumHeight(), 150)
        self.assertIn("recortar el tramo", e.grafica.getPlotItem().titleLabel.text)
        va.close()


class TestCoach(unittest.TestCase):
    def test_input_y_pildoras_fijos_abajo_y_solo_el_chat_se_estira(self):
        vm, _ = _vm()
        w = _coach(vm)
        lay = w.layout()
        estira = [i for i in range(lay.count()) if lay.stretch(i) > 0]
        self.assertEqual([lay.itemAt(i).widget() for i in estira], [w.scroll])
        for x in (w.txt_entrada, w.btn_enviar, w.botones_habito[0], w.botones_rapidos[0]):
            self.assertTrue(x.isVisible())
            self.assertTrue(w.barra_inferior.isAncestorOf(x))
        self.assertGreater(w.barra_inferior.geometry().top(), w.scroll.geometry().top())
        w.resize(900, 420)                                                # ventana baja: el input sigue dentro
        _app.processEvents()
        self.assertLessEqual(w.txt_entrada.mapTo(w, w.txt_entrada.rect().bottomLeft()).y(), w.height())
        w.close()

    def test_resumen_medico_en_la_barra_superior_y_etiqueta_legible(self):
        vm, _ = _vm()
        w = _coach(vm)
        self.assertEqual(w.chk_auto_analisis.text(), "Resumir sesión al terminar")
        self.assertIn("#E2E8F0", w.chk_auto_analisis.styleSheet())
        self.assertIn("resumen del Coach cada vez que finalizas", w.chk_auto_analisis.toolTip())
        self.assertIsNotNone(w.btn_informe.parentWidget())
        self.assertLess(w.btn_informe.height(), 60)
        self.assertGreater(w.btn_informe.y(), w.cabecera.y())
        self.assertTrue(w.btn_informe.geometry().top() < w.scroll.geometry().top())
        w.close()

    def test_accion_cambia_a_verde_se_deshabilita_y_no_duplica_sesiones(self):
        vm, repo = _vm()
        w = _coach(vm)
        v = MainWindow(vm, "Ana")
        w.accion_plan_zona2.connect(v._agendar_zona2)
        w._terminar("q", "Hazlo. [ACCION:PLAN_ZONA2]", c.MOTOR_OFFLINE)
        b = w.botones_accion[0]
        b.click()
        self.assertEqual(b.text(), "✓ Añadido al plan de hoy")
        self.assertFalse(b.isEnabled())
        self.assertIn("#10B981", b.styleSheet())
        self.assertEqual(len(GestorCalendarioPlanificado(repo).entre(HOY, HOY)), 1)
        w._terminar("q2", "Otra vez. [ACCION:PLAN_ZONA2]", c.MOTOR_OFFLINE)
        w.botones_accion[0].click()                                       # otra burbuja idéntica: no inserta
        self.assertEqual(len(GestorCalendarioPlanificado(repo).entre(HOY, HOY)), 1)
        v.close()
        w.close()

    def test_agendar_unica_a_nivel_de_servicio(self):
        _, repo = _vm()
        g = GestorCalendarioPlanificado(repo)
        self.assertIsNotNone(g.agendar_unica(HOY, "Zona 2 (Coach IA)", 40))
        self.assertIsNone(g.agendar_unica(HOY, "Zona 2 (Coach IA)", 40))
        self.assertIsNotNone(g.agendar_unica(HOY, "Zona 2 (Coach IA)", 30))      # otra duración: distinta
        self.assertIsNotNone(g.agendar_unica(HOY + timedelta(days=1), "Zona 2 (Coach IA)", 40))


class TestPlanificacion(unittest.TestCase):
    def _panel(self):
        vm, repo = _vm()
        p = PanelPlanificacion(vm)
        p.show()
        _app.processEvents()
        return vm, repo, p

    def test_botones_iniciar_ahora_y_eliminar_en_cada_sesion(self):
        vm, repo, p = self._panel()
        g = GestorCalendarioPlanificado(repo)
        g.agendar(HOY, "Rodaje Zona 2", 45)
        g.agendar(HOY, "Duplicada", 20)
        p.actualizar()
        self.assertEqual(p.lista.count(), 2)
        fila = p.lista.itemWidget(p.lista.item(0))
        self.assertEqual([b.text() for b in fila.findChildren(QPushButton)], ["Iniciar ahora", "Eliminar"])
        p.lista.itemWidget(p.lista.item(1)).btn_eliminar.click()
        self.assertEqual(p.lista.count(), 1)
        self.assertEqual([s.nombre for s in g.entre(HOY, HOY)], ["Rodaje Zona 2"])
        p.close()

    def test_iniciar_ahora_salta_a_tiempo_real_y_fija_el_objetivo_del_susurrador(self):
        vm = None
        vm, repo = _vm()
        v = MainWindow(vm, "Ana")
        v.show()
        g = GestorCalendarioPlanificado(repo)
        g.agendar(HOY, "Series Zona 4", 30)
        sid = g.agendar(HOY + timedelta(days=2), "Rodaje Zona 2", 50)
        v.pestanas.setCurrentIndex(v.pestanas.indexOf(v.panel_plan))
        v.panel_plan.calendario.setSelectedDate(QDate(HOY.year, HOY.month, HOY.day) .addDays(2))
        v.panel_plan.actualizar()
        self.assertEqual(ib.zona_objetivo_hoy(repo, HOY), 3)             # antes: Zona 4 del día
        v.panel_plan.lista.itemWidget(v.panel_plan.lista.item(0)).btn_iniciar_ahora.click()
        self.assertEqual(v.pestanas.currentIndex(), 0)                   # Tiempo Real
        self.assertEqual(ib.zona_objetivo_hoy(repo, HOY), 1)             # el Susurrador guía la sesión iniciada
        s = [x for x in g.entre(HOY, HOY) if x.id == sid][0]
        self.assertEqual((s.nombre, s.minutos), ("Rodaje Zona 2", 50))
        v.close()


if __name__ == "__main__":
    unittest.main()
