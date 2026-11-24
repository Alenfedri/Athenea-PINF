"""Blindaje final: Modo Demo 100 Hz, sesiones parciales sin ejes rotos y duplicados de sincronización."""
import os
import statistics
import tempfile
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from domain.ui_state import ConexionEstado
from services.repositorio_historial import RepositorioHistorial
from services.simulador_demo import ESCENARIOS, FS, GeneradorDemo
from ui.aviso_datos import ECG_NO_DISPONIBLE, TERMICO_NO_DISPONIBLE, AvisoCentrado
from ui.main_window import MainWindow
from ui.vista_actividades import VistaActividades
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])


def _vm():
    repo = RepositorioHistorial(os.path.join(tempfile.mkdtemp(), "t.db"), usuario_id=1)
    return VitaBandViewModel(MagicMock(), repositorio=repo), repo


class TestDemo(unittest.TestCase):
    def test_generador_ecg_100hz_con_picos_r_coherentes_con_el_bpm(self):
        for nombre, e in ESCENARIOS.items():
            g = GeneradorDemo(nombre)
            muestras = [g.siguiente() for _ in range(FS * 40)]
            self.assertEqual(len(muestras), 4000)
            ecg = [m[0] for m in muestras]
            picos = [i for i in range(1, len(ecg) - 1) if ecg[i] > 2350 and ecg[i] >= ecg[i - 1] and ecg[i] > ecg[i + 1]]
            bpm = len(picos) / 40 * 60
            self.assertAlmostEqual(bpm, e.bpm, delta=e.bpm * 0.12, msg=nombre)
            self.assertAlmostEqual(statistics.fmean(m[2] for m in muestras), e.rpm, delta=1)
        self.assertGreater(statistics.pstdev(GeneradorDemo("Reposo").rr_ms or [0, 0]) + 1, 0)

    def test_vm_inyecta_telemetria_sin_banda_y_no_toca_el_historial(self):
        vm, repo = _vm()
        latidos = []
        vm.latido.connect(lambda: latidos.append(1))
        vm.detectar_latidos = True
        self.assertTrue(vm.iniciar_demo("Esfuerzo Z3"))
        self.assertTrue(vm.modo_demo)
        self.assertEqual(vm.state.conexionEstado, ConexionEstado.CONECTADO)
        for _ in range(400):                                     # 12 s simulados
            vm._tic_demo()
        self.assertGreater(len(vm.state.ecgMuestras), 100)
        self.assertIn("BPM", vm.state.bpmTexto)
        self.assertGreater(len(latidos), 15)
        self.assertFalse(vm.registrar_medicion())
        vm._volcar_ecg(True)
        self.assertEqual(repo.conexion.execute("SELECT COUNT(*) FROM mediciones").fetchone()[0], 0)
        self.assertEqual(repo.conexion.execute("SELECT COUNT(*) FROM ecg_bloques").fetchone()[0], 0)
        vm.detener_demo()
        self.assertFalse(vm.modo_demo)
        self.assertIsNone(vm._timer_demo)
        self.assertEqual(vm.state.conexionEstado, ConexionEstado.DESCONECTADO)

    def test_no_arranca_con_banda_conectada(self):
        vm, _ = _vm()
        vm._emitir_nuevo_estado(conexionEstado=ConexionEstado.CONECTADO)
        self.assertFalse(vm.iniciar_demo("Reposo"))

    def test_control_de_la_ventana_y_limpieza_de_timer(self):
        vm, _ = _vm()
        v = MainWindow(vm, "Ana")
        self.assertEqual([v.combo_escenario_demo.itemText(i) for i in range(3)], ["Reposo", "Esfuerzo Z3", "Estrés Escritorio"])
        v.chk_demo.setChecked(True)
        self.assertTrue(vm.modo_demo)
        self.assertTrue(vm._timer_demo.isActive())
        v.combo_escenario_demo.setCurrentText("Estrés Escritorio")
        self.assertEqual(vm._demo.escenario.nombre, "Estrés Escritorio")
        timer = vm._timer_demo
        v.close()
        self.assertFalse(timer.isActive())
        self.assertFalse(vm.modo_demo)
        v2 = MainWindow(_vm()[0], "Ana")
        v2.vm._emitir_nuevo_estado(conexionEstado=ConexionEstado.CONECTADO)
        v2.chk_demo.setChecked(True)
        self.assertFalse(v2.chk_demo.isChecked())                 # con banda real el interruptor avisa y se desmarca
        v2.close()


class TestSesionParcial(unittest.TestCase):
    def test_avisos_limpios_sin_rr_ecg_ni_temperatura(self):
        vm, repo = _vm()
        import time
        t0 = int(time.time()) - 3600
        a = repo.guardar_actividad("parcial", t0, t0 + 600, "x")
        for i in range(60):                                       # solo BPM: sin temperatura, R-R ni ECG
            repo.guardar_medicion(120 + i % 5, __import__("datetime").datetime.fromtimestamp(t0 + i * 10),
                                  uid=f"m{i}", etiqueta="ACTIVIDAD", actividad_id=a, nivel_actividad=1)
        va = VistaActividades(vm)
        va.resize(1200, 900)
        va.show()
        va.actualizar()
        va.tabla.selectRow(0)
        _app.processEvents()
        va.pestanas_grafica.setCurrentIndex(1)                     # Laboratorio ECG
        _app.processEvents()
        self.assertTrue(va.aviso_ecg_general.isVisible() and va.aviso_ecg_detalle.isVisible())
        self.assertEqual(va.aviso_ecg_general.text(), ECG_NO_DISPONIBLE)
        self.assertEqual(va.aviso_poincare.text(), ECG_NO_DISPONIBLE)
        self.assertTrue(va.aviso_poincare.isVisible())
        va.pestanas_grafica.setCurrentIndex(0)
        va.combo_variable.setCurrentIndex(va.combo_variable.findData("temp"))
        self.assertTrue(va.aviso_termico.isVisible())
        self.assertEqual(va.aviso_termico.text(), TERMICO_NO_DISPONIBLE)
        va.combo_variable.setCurrentIndex(va.combo_variable.findData("bpm"))
        self.assertFalse(va.aviso_termico.isVisible())
        va.close()

    def test_aviso_centrado_se_recoloca(self):
        from PySide6.QtWidgets import QWidget
        w = QWidget()
        w.resize(500, 300)
        w.show()
        av = AvisoCentrado(w)
        av.mostrar("hola")
        self.assertLessEqual(abs(av.geometry().center().x() - 250), 3)
        w.resize(800, 400)
        _app.processEvents()
        self.assertLessEqual(abs(av.geometry().center().x() - 400), 3)
        w.close()


class TestDuplicadosSync(unittest.TestCase):
    def _paquete(self, uid, inicio, fin, med_uid):
        from domain.paquete_sync import ActividadImportada, MedicionImportada, PaqueteSync
        return PaqueteSync(version=1, usuario="a@b.c",
                           mediciones=(MedicionImportada(med_uid, inicio + 5, 130.0, 15.0, 34.0, 1, "ACTIVIDAD", uid),),
                           actividades=(ActividadImportada(uid, inicio, fin, "x"),))

    def test_misma_marca_temporal_con_otro_uid_se_ignora(self):
        _, repo = _vm()
        p1 = self._paquete("a1", 1000, 2000, "m1")
        p2 = self._paquete("a2", 1000, 2000, "m2")
        r1 = repo.importar_paquete(p1)
        r2 = repo.importar_paquete(p2)
        self.assertEqual((r1.actividades_nuevas, r2.actividades_nuevas, r2.actividades_duplicadas), (1, 0, 1))
        self.assertEqual(r2.mediciones_nuevas, 0)
        self.assertEqual(repo.conexion.execute("SELECT COUNT(*) FROM actividades").fetchone()[0], 1)
        self.assertEqual(repo.conexion.execute("SELECT COUNT(*) FROM mediciones").fetchone()[0], 1)
        r3 = repo.importar_paquete(p1)                            # mismo uid: duplicado clásico
        self.assertEqual((r3.actividades_nuevas, r3.mediciones_nuevas), (0, 0))


if __name__ == "__main__":
    unittest.main()
