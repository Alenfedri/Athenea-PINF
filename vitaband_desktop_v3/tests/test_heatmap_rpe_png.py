"""Mapa de calor y rachas, RPE con su cruce en observaciones y exportación PNG."""

import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QLabel

from services import calculos_fisiologicos as calc
from services import constancia as cn
from services.repositorio_historial import RepositorioHistorial
from services.servicio_observaciones import ServicioObservaciones
from ui import exportar_png
from ui.main_window import MainWindow
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])
HOY = date.today()
MIERCOLES = date(2026, 11, 18)                        # miércoles fijo para las rachas
D = cn.DiaActividad


def ts(dia, h=8):
    return int(datetime(dia.year, dia.month, dia.day, h).timestamp())


class TestNivelesYFechas(unittest.TestCase):

    def test_cinco_niveles(self):
        self.assertEqual([cn.nivel(m) for m in (0, 0.5, 1, 14.9, 15, 29.9, 30, 59.9, 60, 300)],
                         [0, 0, 1, 1, 2, 2, 3, 3, 4, 4])

    def test_mapa_de_12_semanas_empieza_en_lunes_y_acaba_hoy(self):
        d0 = cn.primer_dia_mapa(MIERCOLES)
        self.assertEqual(d0.weekday(), 0)
        self.assertEqual((cn.lunes(MIERCOLES) - d0).days, 11 * 7)
        from ui.mapa_calor import MapaCalor
        m = MapaCalor()
        m.mostrar({}, MIERCOLES)
        fechas = m.fechas()
        self.assertEqual(fechas[-1], MIERCOLES)
        self.assertLessEqual(len(fechas), 84)
        self.assertEqual(len(fechas), 11 * 7 + 3)                   # lunes..miércoles de la semana actual

    def test_dia_de_semana_cae_en_su_fila(self):
        from ui.mapa_calor import MapaCalor
        m = MapaCalor()
        m.mostrar({}, MIERCOLES)
        self.assertEqual(m._celda(MIERCOLES).y(), m._celda(MIERCOLES - timedelta(days=2)).y() + 2 * 19)


class TestRachas(unittest.TestCase):

    def dias(self, mapa):
        return {MIERCOLES - timedelta(days=k): D(minutos=m) for k, m in mapa.items()}

    def test_racha_de_dias(self):
        self.assertEqual(cn.racha_dias(self.dias({0: 20, 1: 30, 2: 10}), MIERCOLES), 3)
        self.assertEqual(cn.racha_dias(self.dias({1: 30, 2: 10}), MIERCOLES), 2)        # hoy aún sin actividad
        self.assertEqual(cn.racha_dias(self.dias({0: 20, 2: 10}), MIERCOLES), 1)        # un hueco la corta
        self.assertEqual(cn.racha_dias({}, MIERCOLES), 0)
        self.assertEqual(cn.racha_dias(self.dias({5: 20}), MIERCOLES), 0)

    def semanas(self, minutos_por_semana):
        """minutos_por_semana[0] = semana actual, [1] = anterior…; todo el volumen el lunes de cada una."""
        lun = cn.lunes(MIERCOLES)
        return {lun - timedelta(weeks=i): D(minutos=m) for i, m in enumerate(minutos_por_semana)}

    def test_racha_de_semanas(self):
        self.assertEqual(cn.racha_semanas(self.semanas([160, 150, 200, 10]), MIERCOLES, 150), 3)
        self.assertEqual(cn.racha_semanas(self.semanas([60, 150, 200, 10]), MIERCOLES, 150), 2)   # la actual aún no rompe
        self.assertEqual(cn.racha_semanas(self.semanas([160, 100, 200]), MIERCOLES, 150), 1)
        self.assertEqual(cn.racha_semanas(self.semanas([0, 0]), MIERCOLES, 150), 0)
        self.assertEqual(cn.racha_semanas({}, MIERCOLES, 150), 0)

    def test_objetivo_cambia_la_racha(self):
        d = self.semanas([100, 100, 100])
        self.assertEqual(cn.racha_semanas(d, MIERCOLES, 150), 0)
        self.assertEqual(cn.racha_semanas(d, MIERCOLES, 90), 3)

    def test_minutos_de_la_semana_y_kcal_semanal(self):
        d = {MIERCOLES: D(minutos=30, kcal=200), MIERCOLES - timedelta(days=2): D(minutos=45, kcal=300),
             MIERCOLES - timedelta(days=9): D(minutos=99, kcal=900)}
        self.assertEqual(cn.minutos_semana(d, cn.lunes(MIERCOLES)), 75)
        self.assertEqual(cn.kcal_semana(d, MIERCOLES), 500)


class Base(unittest.TestCase):
    def setUp(self):
        self.repo = RepositorioHistorial(":memory:", usuario_id=1)
        self.vm = VitaBandViewModel(MagicMock(), repositorio=self.repo)
        self.v = MainWindow(self.vm, "Ana")

    def tearDown(self):
        self.v.close()
        self.vm.cerrar()

    def sesion(self, dia, minutos=30, bpm=140, h=8):
        ini = ts(dia, h)
        aid = self.repo.guardar_actividad(f"a{ini}", ini, ini + minutos * 60, "carrera")
        for i in range(minutos * 6):
            self.repo.guardar_medicion(bpm, datetime.fromtimestamp(ini + i * 10), uid=f"{ini}-{i}", rpm=18,
                                       etiqueta="ACTIVIDAD", actividad_id=aid, nivel_actividad=1)
        return aid


class TestMapaEnHistorial(Base):

    def test_resumen_dias_y_tooltip(self):
        self.vm.guardar_perfil(calc.PerfilFisiologico(30, "Hombre", 70.0))
        self.sesion(HOY - timedelta(days=1), 45)
        self.sesion(HOY - timedelta(days=1), 15, h=18)
        h = self.v.vista_historial
        h.actualizar()
        m = h.constancia.mapa
        ayer = HOY - timedelta(days=1)
        self.assertEqual(m.nivel_de(ayer), 4)                         # 60 min
        self.assertEqual(m.nivel_de(HOY - timedelta(days=2)), 0)
        t = m.texto_dia(ayer)
        self.assertIn(f"{ayer:%d/%m/%Y}", t)
        self.assertIn("60 min", t)
        self.assertIn("kcal", t)
        self.assertEqual(m.texto_dia(HOY - timedelta(days=3)).count("kcal"), 0)
        self.assertEqual(m.fecha_en(m._celda(ayer).center()), ayer)
        self.assertIsNone(m.fecha_en(QPointF(-5, -5)))

    def test_objetivo_por_defecto_barra_y_rachas(self):
        h = self.v.vista_historial
        h.actualizar()
        p = h.constancia
        self.assertEqual(p.spin_objetivo.value(), 150)
        self.assertEqual(p.barra.maximum(), 150)
        self.assertIn("0 semanas", p.lbl_racha.text())
        self.sesion(HOY, 40)
        h.actualizar()
        self.assertEqual(p.barra.value(), 40)
        self.assertIn("1 días seguidos", p.lbl_racha.text())

    def test_objetivo_editable_se_guarda(self):
        h = self.v.vista_historial
        h.actualizar()
        h.constancia.spin_objetivo.setValue(200)
        h.constancia.spin_objetivo.editingFinished.emit()
        self.assertEqual(self.vm.perfil().objetivo_semanal_min, 200)
        self.assertEqual(h.constancia.barra.maximum(), 200)
        self.assertEqual(self.vm.constancia()["objetivo"], 200)

    def test_sin_datos_ni_repositorio(self):
        vm = VitaBandViewModel(MagicMock())
        c = vm.constancia()
        self.assertEqual((c["racha_semanas"], c["racha_dias"], c["kcal_semana"], c["objetivo"]), (0, 0, 0, 150))
        vm.cerrar()


class TestRpe(Base):

    def test_cruce_suave_con_pulso_alto(self):
        self.assertIn("desajuste esfuerzo-pulso", calc.cruce_rpe(3, 160, []))
        self.assertIsNotNone(calc.cruce_rpe(4, 142.5, []))             # 75 % exacto
        self.assertIsNone(calc.cruce_rpe(4, 142.4, []))
        self.assertIsNone(calc.cruce_rpe(5, 170, []))                  # RPE 5 ya no es «suave»
        self.assertIsNone(calc.cruce_rpe(3, 110, []))

    def test_cruce_duro_con_pulso_contenido_solo_si_se_repite(self):
        self.assertIsNone(calc.cruce_rpe(8, 120, []))                  # una vez no basta
        self.assertIn("fatiga acumulada", calc.cruce_rpe(8, 120, [(9, 118)]))
        self.assertIn("fatiga acumulada", calc.cruce_rpe(8, 120, [(5, 150), (8, 110)]))
        self.assertIsNone(calc.cruce_rpe(8, 120, [(5, 118), (6, 118)]))           # antes no fueron duras
        self.assertIsNone(calc.cruce_rpe(8, 120, [(9, 160)]))                      # antes duras pero con pulso alto
        self.assertIsNone(calc.cruce_rpe(9, 165, [(9, 118)]))                      # pulso proporcionado al esfuerzo
        self.assertIsNone(calc.cruce_rpe(8, 120, [(9, 118)] * 0 + [(None, 0)] if False else []))

    def test_sin_datos(self):
        self.assertIsNone(calc.cruce_rpe(None, 150, []))
        self.assertIsNone(calc.cruce_rpe(3, None, []))
        self.assertIsNone(calc.cruce_rpe(3, 0, []))

    def test_repositorio(self):
        aid = self.sesion(HOY - timedelta(days=1))
        self.assertIsNone(self.repo.nota_sesion(aid))
        self.repo.guardar_nota_sesion(aid, 7, "  piernas pesadas ")
        self.assertEqual(self.repo.nota_sesion(aid), (7, "piernas pesadas"))
        self.repo.guardar_nota_sesion(aid, None, "solo nota")
        self.assertEqual(self.repo.nota_sesion(aid), (None, "solo nota"))
        for malo in (0, 11, -1):
            with self.assertRaises(ValueError):
                self.repo.guardar_nota_sesion(aid, malo, "")
        self.repo.borrar_actividad(aid)
        self.assertIsNone(self.repo.nota_sesion(aid))

    def test_observacion_cruzada_desde_la_ui(self):
        aid = self.sesion(HOY - timedelta(days=1), 30, bpm=160)        # 84 % de 190
        a = self.v.vista_actividades
        a.selector.establecer_rango(HOY - timedelta(days=1), HOY - timedelta(days=1))
        a.actualizar()
        self.assertTrue(a.btn_valoracion.isEnabled())
        a.spin_rpe.setValue(3)
        a.edit_nota.setText("Rodaje fácil")
        recibidas = []
        self.vm.observaciones_actualizadas.connect(lambda: recibidas.append(1))
        a.btn_valoracion.click()
        self.assertTrue(recibidas)
        self.assertEqual(self.repo.nota_sesion(aid), (3, "Rodaje fácil"))
        o = self.repo.observacion_actividad(aid).texto
        self.assertIn("desajuste esfuerzo-pulso", o)
        self.assertTrue(o.rstrip().endswith("diagnóstico médico."))
        # al seleccionar de nuevo se recuperan los valores guardados
        a.actualizar()
        self.assertEqual((a.spin_rpe.value(), a.edit_nota.text()), (3, "Rodaje fácil"))

    def test_sin_valoracion_no_hay_cruce_y_guardar_vacio_no_hace_nada(self):
        aid = self.sesion(HOY - timedelta(days=1), 30, bpm=160)
        a = self.v.vista_actividades
        a.selector.establecer_rango(HOY - timedelta(days=1), HOY - timedelta(days=1))
        a.actualizar()
        a.btn_valoracion.click()
        self.assertIsNone(self.repo.nota_sesion(aid))
        ServicioObservaciones(self.repo).actualizar_todo()
        self.assertNotIn("desajuste", self.repo.observacion_actividad(aid).texto)

    def test_fatiga_acumulada_con_tres_sesiones(self):
        ids = [self.sesion(HOY - timedelta(days=d), 30, bpm=120) for d in (3, 2, 1)]
        for aid in ids[:2]:
            self.repo.guardar_nota_sesion(aid, 9, "")
        self.repo.guardar_nota_sesion(ids[2], 8, "")
        ServicioObservaciones(self.repo).actualizar_todo()
        self.assertIn("fatiga acumulada", self.repo.observacion_actividad(ids[2]).texto)
        self.assertNotIn("fatiga acumulada", self.repo.observacion_actividad(ids[0]).texto)   # la primera no repite nada


class TestPng(Base):

    def widget(self):
        w = QLabel("hola gráfica")
        w.resize(200, 120)
        return w

    def test_exporta_en_alta_resolucion(self):
        ruta = os.path.join(tempfile.mkdtemp(), "g.png")
        w = self.widget()
        with patch("ui.exportar_png.QFileDialog.getSaveFileName", return_value=(ruta, "")) as dlg, \
             patch("ui.exportar_png.QMessageBox.information") as info:
            self.assertEqual(exportar_png.exportar_grafica_png(w, "vitaband_ecg"), ruta)
        self.assertIn("*.png", dlg.call_args.args[3])
        self.assertIn("vitaband_ecg_", dlg.call_args.args[2])
        img = QImage(ruta)
        self.assertFalse(img.isNull())
        self.assertEqual((img.width(), img.height()), (400, 240))        # el doble que en pantalla
        self.assertIn(ruta, info.call_args.args[2])
        self.assertFalse(all(img.pixelColor(x, y) == img.pixelColor(0, 0) for x in range(0, 400, 7) for y in range(0, 240, 7)))

    def test_cancelar_y_extension(self):
        w = self.widget()
        with patch("ui.exportar_png.QFileDialog.getSaveFileName", return_value=("", "")):
            self.assertIsNone(exportar_png.exportar_grafica_png(w, "x"))
        base = os.path.join(tempfile.mkdtemp(), "sin_ext")
        with patch("ui.exportar_png.QFileDialog.getSaveFileName", return_value=(base, "")), \
             patch("ui.exportar_png.QMessageBox.information"):
            self.assertEqual(exportar_png.exportar_grafica_png(w, "x"), base + ".png")
        self.assertTrue(os.path.exists(base + ".png"))

    def test_ruta_no_escribible_avisa(self):
        w = self.widget()
        mala = os.path.join(tempfile.mkdtemp(), "no", "existe", "g.png")
        with patch("ui.exportar_png.QFileDialog.getSaveFileName", return_value=(mala, "")), \
             patch("ui.exportar_png.QMessageBox.warning") as aviso, \
             patch("ui.exportar_png.QMessageBox.information") as info:
            self.assertIsNone(exportar_png.exportar_grafica_png(w, "x"))
        aviso.assert_called_once()
        info.assert_not_called()

    def test_botones_png_junto_a_las_tres_graficas(self):
        from PySide6.QtWidgets import QPushButton
        for ventana in (self.v, self.v.vista_actividades, self.v.vista_historial):
            textos = [b.text() for b in ventana.findChildren(QPushButton)]
            self.assertIn("PNG", textos, type(ventana).__name__)

    def test_cada_boton_exporta_su_grafica(self):
        from PySide6.QtWidgets import QPushButton
        casos = {"ecg": self.v, "comparador": self.v.vista_actividades, "historial": self.v.vista_historial}
        for nombre, ventana in casos.items():
            ruta = os.path.join(tempfile.mkdtemp(), f"{nombre}.png")
            boton = next(b for b in ventana.findChildren(QPushButton) if b.text() == "PNG")
            with patch("ui.exportar_png.QFileDialog.getSaveFileName", return_value=(ruta, "")) as dlg, \
                 patch("ui.exportar_png.QMessageBox.information"):
                boton.click()
            self.assertTrue(os.path.exists(ruta), nombre)
            self.assertIn("vitaband_", dlg.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
