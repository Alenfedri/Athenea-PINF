"""Vueltas (Lap), sesión en directo y auto-pausa por retirada de banda."""

import os
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from domain.calidad_contacto import CalidadContacto
from domain.modelos import Medicion
from domain.ui_state import ConexionEstado
from services import calculos_fisiologicos as calc
from services.repositorio_historial import RepositorioHistorial
from ui.main_window import MainWindow
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])
DIA = date.today() - timedelta(days=1)
T0 = int(datetime(DIA.year, DIA.month, DIA.day, 8, 0).timestamp())


def med(t, bpm, rpm=18.0):
    return Medicion(t, f"m{t}", T0 + t, bpm, rpm, None, 1, "ACTIVIDAD", 1)


class TestDesgloseVueltas(unittest.TestCase):

    def test_tramos_y_medias(self):
        ms = [med(t, 100 if t < 60 else 140 if t < 120 else 160, 15 if t < 60 else 20) for t in range(0, 180, 10)]
        v = calc.desglose_vueltas(T0, T0 + 180, [T0 + 60, T0 + 120], ms)
        self.assertEqual([x.numero for x in v], [1, 2, 3])
        self.assertEqual([x.duracion_s for x in v], [60, 60, 60])
        self.assertEqual([x.bpm_medio for x in v], [100, 140, 160])
        self.assertEqual([x.rpm_medio for x in v], [15, 20, 20])

    def test_marcas_fuera_o_duplicadas_y_sin_marcas(self):
        ms = [med(t, 120) for t in range(0, 100, 10)]
        self.assertEqual(calc.desglose_vueltas(T0, T0 + 100, [], ms), [])
        self.assertEqual(calc.desglose_vueltas(T0, T0 + 100, [T0 - 5, T0 + 500], ms), [])
        v = calc.desglose_vueltas(T0, T0 + 100, [T0 + 50, T0 + 50, T0 + 999], ms)
        self.assertEqual(len(v), 2)

    def test_tramo_sin_mediciones(self):
        v = calc.desglose_vueltas(T0, T0 + 100, [T0 + 50], [med(0, 100), med(10, 100)])
        self.assertIsNone(v[1].bpm_medio)
        self.assertIsNone(v[1].rpm_medio)


class TestSesionDirecto(unittest.TestCase):

    def avanzar(self, s, segundos, contacto=True, bpm=140.0, rpm=18.0, t0=0.0, paso=1.0):
        t = t0
        for _ in range(int(segundos / paso)):
            t += paso
            s.actualizar(True, contacto, bpm, rpm, t)
        return t

    def sesion(self):
        s = calc.SesionDirecto()
        s.actualizar(True, True, 140, 18, 0.0)                    # arranque
        return s

    def test_tiempo_efectivo_y_medias_con_contacto(self):
        s = self.sesion()
        self.avanzar(s, 30)
        self.assertAlmostEqual(s.tiempo_efectivo_s, 30)
        self.assertAlmostEqual(s.bpm_medio, 140)
        self.assertAlmostEqual(s.rpm_medio, 18)
        self.assertEqual(s.estado, "")

    def test_pausa_tras_mas_de_5_s_sin_contacto(self):
        s = self.sesion()
        t = self.avanzar(s, 10)
        t = self.avanzar(s, 5, contacto=False, t0=t)
        self.assertFalse(s.pausada)                                # exactamente 5 s: todavía no
        t = self.avanzar(s, 1, contacto=False, t0=t)
        self.assertTrue(s.pausada)
        self.assertEqual(s.estado, "PAUSA AUTOMÁTICA (Sin contacto)")
        congelado = s.tiempo_efectivo_s
        t = self.avanzar(s, 20, contacto=False, bpm=0, t0=t)
        self.assertEqual(s.tiempo_efectivo_s, congelado)           # el cronómetro no avanza
        self.assertAlmostEqual(congelado, 10)                       # el tramo sin contacto no cuenta

    def test_las_muestras_sin_contacto_no_entran_en_las_medias(self):
        s = self.sesion()
        t = self.avanzar(s, 10, bpm=140, rpm=18)
        t = self.avanzar(s, 30, contacto=False, bpm=40, rpm=5, t0=t)       # valores basura sin banda
        self.avanzar(s, 10, bpm=140, rpm=18, t0=t)
        self.assertAlmostEqual(s.bpm_medio, 140)
        self.assertAlmostEqual(s.rpm_medio, 18)
        self.assertFalse(s.pausada)                                  # al volver la señal, sale de la pausa
        self.assertAlmostEqual(s.tiempo_efectivo_s, 20)

    def test_corte_breve_cuenta_como_tiempo_pero_no_en_las_medias(self):
        s = self.sesion()
        t = self.avanzar(s, 10)
        t = self.avanzar(s, 3, contacto=False, bpm=40, t0=t)
        self.assertFalse(s.pausada)
        self.avanzar(s, 10, t0=t)
        self.assertAlmostEqual(s.tiempo_efectivo_s, 23)
        self.assertAlmostEqual(s.bpm_medio, 140)

    def test_desconectar_cierra_y_reconectar_reinicia(self):
        s = self.sesion()
        self.avanzar(s, 20)
        s.vueltas = 3
        s.actualizar(False, False, None, None, 25.0)
        self.assertFalse(s.activa)
        s.actualizar(True, True, 140, 18, 100.0)
        self.assertTrue(s.activa)
        self.assertEqual((s.tiempo_efectivo_s, s.vueltas, s.bpm_medio), (0.0, 0, None))

    def test_un_salto_de_reloj_no_infla_el_tiempo(self):
        s = self.sesion()
        s.actualizar(True, True, 140, 18, 500.0)
        self.assertLessEqual(s.tiempo_efectivo_s, calc.MAX_DT_S)

    def test_sin_datos_no_hay_medias(self):
        s = self.sesion()
        self.assertIsNone(s.bpm_medio)
        self.assertIsNone(s.rpm_medio)


class Reloj:
    t = 1_000.0

    def __call__(self):
        return self.t


class Base(unittest.TestCase):
    def setUp(self):
        self.reloj = Reloj()
        self.repo = RepositorioHistorial(":memory:", usuario_id=1)
        self.vm = VitaBandViewModel(MagicMock(), repositorio=self.repo, reloj=self.reloj)
        self.v = MainWindow(self.vm, "Ana")

    def tearDown(self):
        if getattr(self.v, "modo_entrenamiento", None):
            self.v.modo_entrenamiento.close()
        self.v.close()
        self.vm.cerrar()

    def estado(self, contacto=CalidadContacto.OPTIMO, conexion=ConexionEstado.CONECTADO, **kw):
        self.vm._emitir_nuevo_estado(conexionEstado=conexion, calidadContacto=contacto, **kw)

    def tic(self, segundos, **kw):
        for _ in range(int(segundos)):
            self.reloj.t += 1
            self.estado(**kw)


class TestVueltasVm(Base):

    def test_sin_banda_conectada_no_se_marca(self):
        self.assertIsNone(self.vm.marcar_vuelta())
        self.assertFalse(self.v.btn_lap.isEnabled())

    def test_numeracion_guardado_y_reinicio_por_sesion(self):
        recibidas = []
        self.vm.vuelta_marcada.connect(recibidas.append)
        self.estado(); self.tic(2)
        self.assertEqual(self.vm.marcar_vuelta(), 1)
        self.reloj.t += 30
        self.assertEqual(self.vm.marcar_vuelta(), 2)
        self.assertEqual(recibidas, [1, 2])
        self.assertEqual(len(self.repo.vueltas_rango(0, 2 ** 31)), 2)
        self.estado(conexion=ConexionEstado.DESCONECTADO)
        self.assertIsNone(self.vm.marcar_vuelta())
        self.estado(); self.tic(1)
        self.assertEqual(self.vm.marcar_vuelta(), 1)                 # sesión nueva, cuenta desde 1

    def test_sin_repositorio(self):
        vm = VitaBandViewModel(MagicMock())
        vm._emitir_nuevo_estado(conexionEstado=ConexionEstado.CONECTADO)
        self.assertIsNone(vm.marcar_vuelta())
        vm.cerrar()


class TestVueltasUi(Base):

    def test_boton_lap_y_feedback(self):
        self.estado(); self.tic(1)
        self.assertTrue(self.v.btn_lap.isEnabled())
        self.v.btn_lap.click()
        self.assertEqual(self.v.lbl_vuelta.text(), "Vuelta #1 marcada")
        self.v.btn_lap.click()
        self.assertEqual(self.v.lbl_vuelta.text(), "Vuelta #2 marcada")

    def test_espacio_en_modo_entrenamiento_marca_una_sola_vez(self):
        self.estado(); self.tic(1)
        self.v.btn_entrenamiento.click()
        d = self.v.modo_entrenamiento
        self.assertEqual(d.btn_salir.focusPolicy(), Qt.FocusPolicy.NoFocus)
        self.assertEqual(d.btn_sonido.focusPolicy(), Qt.FocusPolicy.NoFocus)
        QTest.keyClick(d, Qt.Key.Key_Space)
        self.assertEqual(len(self.repo.vueltas_rango(0, 2 ** 31)), 1)       # una pulsación = una vuelta
        self.assertEqual(self.vm.sesion_directo.vueltas, 1)
        self.assertTrue(d.lbl_vuelta.isVisibleTo(d))
        self.assertIn("Vuelta #1", d.lbl_vuelta.text())
        self.assertTrue(d.isVisible())                                        # Espacio no cierra ni pulsa «Salir»

    def test_espacio_sin_sesion_avisa_y_no_guarda(self):
        self.v.btn_entrenamiento.click()
        d = self.v.modo_entrenamiento
        QTest.keyClick(d, Qt.Key.Key_Space)
        self.assertEqual(self.repo.vueltas_rango(0, 2 ** 31), [])
        self.assertIn("Conecta", d.lbl_vuelta.text())


class TestAutoPausaUi(Base):

    def test_banner_de_pausa_y_reanudacion(self):
        self.estado(bpmTexto="140.0 BPM", rpmTexto="18.0 RPM"); self.tic(3, bpmTexto="140.0 BPM", rpmTexto="18.0 RPM")
        self.assertFalse(self.v.lbl_pausa.isVisibleTo(self.v))
        self.tic(7, contacto=CalidadContacto.SIN_SENAL, bpmTexto="40.0 BPM", rpmTexto="5.0 RPM")
        self.assertTrue(self.v.lbl_pausa.isVisibleTo(self.v))
        self.assertEqual(self.v.lbl_pausa.text(), "PAUSA AUTOMÁTICA (Sin contacto)")
        efectivo = self.vm.sesion_directo.tiempo_efectivo_s
        self.tic(10, contacto=CalidadContacto.SIN_SENAL, bpmTexto="40.0 BPM", rpmTexto="5.0 RPM")
        self.assertEqual(self.vm.sesion_directo.tiempo_efectivo_s, efectivo)
        self.tic(2, bpmTexto="140.0 BPM", rpmTexto="18.0 RPM")
        self.assertFalse(self.v.lbl_pausa.isVisibleTo(self.v))
        self.assertAlmostEqual(self.vm.sesion_directo.bpm_medio, 140)       # los 40 BPM sin contacto no entraron

    def test_el_modo_entrenamiento_muestra_la_pausa(self):
        self.estado(); self.tic(2)
        self.v.btn_entrenamiento.click()
        self.tic(8, contacto=CalidadContacto.SIN_SENAL)
        self.assertIn("PAUSA AUTOMÁTICA", self.v.modo_entrenamiento.lbl_sesion.text())

    def test_texto_de_sesion_con_kcal_solo_con_perfil(self):
        self.estado(bpmTexto="140.0 BPM", rpmTexto="18.0 RPM"); self.tic(30, bpmTexto="140.0 BPM", rpmTexto="18.0 RPM")
        self.assertIn("FC media 140", self.v.lbl_sesion.text())
        self.assertNotIn("kcal", self.v.lbl_sesion.text())
        self.vm.guardar_perfil(calc.PerfilFisiologico(30, "Hombre", 70.0))
        self.tic(1, bpmTexto="140.0 BPM", rpmTexto="18.0 RPM")
        self.assertIn("kcal", self.v.lbl_sesion.text())


class TestTablaVueltasActividades(Base):

    def crear(self, marcas):
        aid = self.repo.guardar_actividad("a1", T0, T0 + 180, "carrera")
        for t in range(0, 180, 10):
            self.repo.guardar_medicion(100 if t < 60 else 150, datetime.fromtimestamp(T0 + t), uid=f"u{t}", rpm=15,
                                       etiqueta="ACTIVIDAD", actividad_id=aid, nivel_actividad=1)
        for i, m in enumerate(marcas, 1):
            self.repo.guardar_vuelta(T0 + m, i)
        a = self.v.vista_actividades
        a.selector.establecer_rango(DIA, DIA)
        a.actualizar()
        return a

    def test_tabla_con_vueltas(self):
        a = self.crear([60, 120])
        t = a.tabla_vueltas
        self.assertTrue(t.isVisibleTo(a))
        self.assertEqual(t.rowCount(), 3)
        self.assertEqual([t.horizontalHeaderItem(i).text() for i in range(4)],
                         ["Vuelta", "Duración", "BPM medio", "RPM medio"])
        self.assertEqual(t.item(0, 0).text(), "#1")
        self.assertEqual(t.item(0, 2).text(), "100")
        self.assertEqual(t.item(1, 2).text(), "150")

    def test_sin_vueltas_la_tabla_se_oculta(self):
        a = self.crear([])
        self.assertFalse(a.tabla_vueltas.isVisibleTo(a))


if __name__ == "__main__":
    unittest.main()
