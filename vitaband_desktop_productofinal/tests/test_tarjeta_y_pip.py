"""Tarjeta resumen PNG (540×960) y Mini-Widget PiP flotante."""

import math
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent
from PySide6.QtWidgets import QApplication

from domain.calidad_contacto import CalidadContacto
from domain.ui_state import ConexionEstado
from services import calculos_fisiologicos as calc
from services import tarjeta_resumen as tr
from services.repositorio_historial import RepositorioHistorial
from ui.main_window import MainWindow
from ui.mini_widget_pip import MiniWidgetPip
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])
INI = int(datetime(2026, 11, 10, 8).timestamp())


def datos(**kw):
    base = dict(inicio_ts=INI, duracion_s=2400,
                bpm_serie=[(i * 10, 125 + 15 * math.sin(i / 9)) for i in range(240)],
                zonas_pct=[5, 60, 25, 8, 2], kcal=312.0, trimp=88.0,
                insignias=("PR menor BPM medio en Carrera (30–60 min)",), disciplina="Carrera")
    base.update(kw)
    return tr.DatosTarjeta(**base)


class TestTarjeta(unittest.TestCase):

    def test_dimensiones_y_fondo(self):
        img = tr.generar_tarjeta(datos())
        self.assertEqual((img.width(), img.height()), (540, 960))
        self.assertEqual(img.format(), QImage.Format.Format_ARGB32)
        self.assertEqual(img.pixelColor(2, 2), QColor("#090E0C"))
        self.assertEqual(img.pixelColor(537, 957), QColor("#090E0C"))

    def test_dibuja_contenido_en_cada_zona_de_la_tarjeta(self):
        img = tr.generar_tarjeta(datos())
        fondo = QColor("#090E0C")

        def hay(x0, y0, x1, y1):
            return any(img.pixelColor(x, y) != fondo for x in range(x0, x1, 3) for y in range(y0, y1, 3))

        self.assertTrue(hay(36, 40, 300, 130))          # cabecera
        self.assertTrue(hay(36, 210, 300, 300))         # duración
        self.assertTrue(hay(36, 330, 500, 520))         # curva de BPM
        self.assertTrue(hay(84, 600, 430, 770))         # barras de zonas
        self.assertTrue(hay(36, 800, 500, 884))         # kcal / TRIMP
        self.assertTrue(hay(36, 895, 500, 950))         # insignias

    def test_la_curva_usa_el_color_de_acento(self):
        img = tr.generar_tarjeta(datos())
        verdes = sum(1 for x in range(36, 504, 2) for y in range(330, 520, 2)
                     if img.pixelColor(x, y).green() > 150 and img.pixelColor(x, y).red() < 60)
        self.assertGreater(verdes, 50)                       # Esmeralda ECG (#10B981)

    def test_barras_de_zona_proporcionales(self):
        img = tr.generar_tarjeta(datos(zonas_pct=[0, 100, 0, 0, 0]))
        z2 = QColor(tr.COLORES_ZONAS[1])
        y2 = 604 + 34 + 12
        self.assertEqual(img.pixelColor(300, y2), z2)                                  # Z2 llena
        self.assertNotEqual(img.pixelColor(300, 604 + 12), QColor(tr.COLORES_ZONAS[0]))  # Z1 vacía

    def test_sin_datos_no_falla_y_sigue_siendo_valida(self):
        img = tr.generar_tarjeta(datos(bpm_serie=[], zonas_pct=None, kcal=None, trimp=None, insignias=(),
                                       disciplina=None))
        self.assertEqual((img.width(), img.height()), (540, 960))
        un_punto = tr.generar_tarjeta(datos(bpm_serie=[(0, 100)]))
        self.assertEqual(un_punto.height(), 960)

    def test_muchas_insignias_y_textos_largos(self):
        img = tr.generar_tarjeta(datos(insignias=("PR " + "x" * 200, "otro", "tercero")))
        self.assertEqual(img.height(), 960)

    def test_series_largas_se_reducen(self):
        img = tr.generar_tarjeta(datos(bpm_serie=[(i, 120 + 10 * math.sin(i / 50)) for i in range(20000)]))
        self.assertEqual(img.width(), 540)

    def test_guardar_png_valido(self):
        ruta = os.path.join(tempfile.mkdtemp(), "t.png")
        self.assertTrue(tr.guardar_tarjeta(datos(), ruta))
        self.assertGreater(os.path.getsize(ruta), 5000)
        img = QImage(ruta)
        self.assertEqual((img.width(), img.height()), (540, 960))
        with open(ruta, "rb") as f:
            self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n")

    def test_ruta_invalida_devuelve_false(self):
        self.assertFalse(tr.guardar_tarjeta(datos(), os.path.join(tempfile.mkdtemp(), "no", "existe", "t.png")))

    def test_formatos_de_texto(self):
        self.assertEqual(tr._duracion(125), "2:05")
        self.assertEqual(tr._duracion(3725), "1:02:05")
        self.assertEqual(tr._duracion(-4), "0:00")
        self.assertIn("nov 2026", tr._fecha(INI))


class Reloj:
    t = 1_000.0

    def __call__(self):
        return self.t


class Base(unittest.TestCase):
    def setUp(self):
        self.repo = RepositorioHistorial(":memory:", usuario_id=1)
        self.vm = VitaBandViewModel(MagicMock(), repositorio=self.repo, reloj=Reloj())
        self.v = MainWindow(self.vm, "Ana")

    def tearDown(self):
        if getattr(self.v, "pip", None):
            self.v.pip.close()
        self.v.close()
        self.vm.cerrar()

    def sesion(self, dia, minutos=40, bpm=125):
        ini = int(datetime(dia.year, dia.month, dia.day, 8).timestamp())
        aid = self.repo.guardar_actividad(f"a{ini}", ini, ini + minutos * 60, "carrera")
        for i in range(minutos * 6):
            self.repo.guardar_medicion(bpm, datetime.fromtimestamp(ini + i * 10), uid=f"{ini}-{i}", rpm=18,
                                       etiqueta="ACTIVIDAD", actividad_id=aid, nivel_actividad=1)
        return aid


class TestTarjetaEnActividades(Base):

    def setUp(self):
        super().setUp()
        hoy = date.today()
        self.a1 = self.sesion(hoy - timedelta(days=3), 40, 125)
        self.a2 = self.sesion(hoy - timedelta(days=2), 40, 118)
        for a in (self.a1, self.a2):
            self.repo.guardar_disciplina(a, "Carrera")
        self.vm.guardar_perfil(calc.PerfilFisiologico(30, "Hombre", 70.0))
        self.act = self.v.vista_actividades
        self.act.selector.establecer_rango(hoy - timedelta(days=10), hoy)
        self.act.actualizar()

    def seleccionar(self, aid):
        fila = next(i for i in range(self.act.tabla.rowCount()) if self.act.tabla.item(i, 0).data(0x0100) == aid)
        self.act.tabla.selectRow(fila)

    def test_boton_habilitado_solo_con_una_sesion_seleccionada(self):
        self.assertEqual(self.act.btn_tarjeta.text(), "Tarjeta Resumen (.PNG)")
        self.act.tabla.clearSelection()
        self.act._on_seleccion()
        self.assertFalse(self.act.btn_tarjeta.isEnabled())
        self.seleccionar(self.a2)
        self.assertTrue(self.act.btn_tarjeta.isEnabled())

    def test_datos_de_la_tarjeta(self):
        d = self.vm.datos_tarjeta(self.vm.detalle_actividad(self.a2))
        self.assertEqual(d.duracion_s, 2400)
        self.assertAlmostEqual(sum(d.zonas_pct), 100.0, places=3)
        self.assertGreater(d.zonas_pct[1], 90)                         # 118 bpm con FCmáx 190 = Z2
        self.assertIsNotNone(d.kcal)
        self.assertGreater(d.kcal, 0)
        self.assertIsNotNone(d.trimp)
        self.assertEqual(d.disciplina, "Carrera")
        self.assertTrue(any("menor BPM" in i for i in d.insignias))    # a2 es el PR de Carrera
        self.assertGreater(len(d.bpm_serie), 100)
        sin_pr = self.vm.datos_tarjeta(self.vm.detalle_actividad(self.a1))
        self.assertEqual(sin_pr.insignias, ())

    def test_sin_perfil_kcal_es_nd(self):
        repo = RepositorioHistorial(":memory:", usuario_id=3)
        vm = VitaBandViewModel(MagicMock(), repositorio=repo, reloj=Reloj())
        ini = INI
        aid = repo.guardar_actividad("z", ini, ini + 1200)
        for i in range(120):
            repo.guardar_medicion(130, datetime.fromtimestamp(ini + i * 10), uid=f"z{i}", etiqueta="ACTIVIDAD",
                                  actividad_id=aid, nivel_actividad=1)
        self.assertIsNone(vm.datos_tarjeta(vm.detalle_actividad(aid)).kcal)
        vm.cerrar()

    def test_exportar_con_selector_de_archivo(self):
        self.seleccionar(self.a2)
        ruta = os.path.join(tempfile.mkdtemp(), "mi_tarjeta")
        with patch("ui.vista_actividades.QFileDialog.getSaveFileName", return_value=(ruta, "")) as dlg, \
             patch("ui.animations.show_toast") as info:
            self.act.btn_tarjeta.click()
        info.assert_called_once()
        self.assertIn("*.png", dlg.call_args.args[3])
        self.assertTrue(dlg.call_args.args[2].endswith(".png"))
        self.assertTrue(os.path.exists(ruta + ".png"))
        self.assertGreater(os.path.getsize(ruta + ".png"), 0)
        img = QImage(ruta + ".png")
        self.assertEqual((img.width(), img.height()), (540, 960))
        info.assert_called_once()

    def test_cancelar_no_crea_nada(self):
        self.seleccionar(self.a2)
        with patch("ui.vista_actividades.QFileDialog.getSaveFileName", return_value=("", "")), \
             patch("ui.animations.show_toast") as info, \
             patch("ui.vista_actividades.QMessageBox.warning") as aviso:
            self.act.btn_tarjeta.click()
        info.assert_not_called()
        aviso.assert_not_called()

    def test_error_de_escritura_avisa(self):
        self.seleccionar(self.a2)
        mala = os.path.join(tempfile.mkdtemp(), "no", "existe", "t.png")
        with patch("ui.vista_actividades.QFileDialog.getSaveFileName", return_value=(mala, "")), \
             patch("ui.animations.show_toast") as info, \
             patch("ui.vista_actividades.QMessageBox.warning") as aviso:
            self.act.btn_tarjeta.click()
        aviso.assert_called_once()
        info.assert_not_called()

    def test_actividad_borrada_lanza(self):
        with self.assertRaises(RuntimeError):
            self.vm.exportar_tarjeta(99999, "x.png")


class TestMiniWidgetPip(Base):

    def estado(self, bpm="72.0 BPM", rpm="15.0 RPM", **kw):
        self.vm._emitir_nuevo_estado(conexionEstado=ConexionEstado.CONECTADO,
                                     calidadContacto=CalidadContacto.OPTIMO, bpmTexto=bpm, rpmTexto=rpm, **kw)

    def test_banderas_y_transparencia(self):
        w = MiniWidgetPip(self.vm)
        f = w.windowFlags()
        for bandera in (Qt.WindowType.WindowStaysOnTopHint, Qt.WindowType.FramelessWindowHint, Qt.WindowType.Tool):
            self.assertTrue(f & bandera, bandera)
        self.assertLess(w.windowOpacity(), 1.0)
        self.assertGreater(w.windowOpacity(), 0.3)
        self.assertEqual(w.btn_restaurar.text(), "Restaurar")
        w.close()

    def test_apertura_desde_tiempo_real_minimiza_y_muestra_el_widget(self):
        self.v.show()
        self.assertEqual(self.v.btn_pip.text(), "Mini-Widget PiP")
        self.v.btn_pip.click()
        self.assertTrue(self.v.pip.isVisible())
        self.assertTrue(self.v.isMinimized())

    def test_telemetria_en_vivo_y_zona(self):
        self.v.btn_pip.click()
        self.estado("72.0 BPM", "15.0 RPM")
        self.assertEqual(self.v.pip.lbl_bpm.text(), "72")
        self.assertEqual(self.v.pip.lbl_rpm.text(), "15")
        self.assertIn("Z1", self.v.pip.zona_texto)
        self.estado("125.0 BPM", "22.0 RPM")                                  # 66 % de 190 → Z2
        self.assertEqual(self.v.pip.lbl_bpm.text(), "125")
        self.assertIn("Z2", self.v.pip.zona_texto)
        self.assertIn("#2ECC40", self.v.pip.lbl_zona.styleSheet())
        self.estado("175.0 BPM", "35.0 RPM")
        self.assertIn("Z5", self.v.pip.zona_texto)
        self.estado("--", "--")
        self.assertEqual(self.v.pip.lbl_bpm.text(), "--")
        self.assertEqual(self.v.pip.zona_texto, "Sin zona")

    def test_restaurar_vuelve_a_la_ventana_principal_y_deja_de_escuchar(self):
        self.v.show()
        self.v.btn_pip.click()
        self.assertTrue(self.v.isMinimized())
        self.v.pip.btn_restaurar.click()
        self.assertFalse(self.v.pip.isVisible())
        self.assertFalse(self.v.isMinimized())
        self.assertTrue(self.v.isVisible())
        self.estado("99.0 BPM")
        self.assertNotEqual(self.v.pip.lbl_bpm.text(), "99")                  # ya no se sincroniza

    def test_se_puede_reabrir_varias_veces_con_la_misma_instancia(self):
        self.v.btn_pip.click()
        primero = self.v.pip
        self.v.pip.btn_restaurar.click()
        self.v.btn_pip.click()
        self.assertIs(self.v.pip, primero)
        self.estado("88.0 BPM")
        self.assertEqual(self.v.pip.lbl_bpm.text(), "88")

    def test_arrastrable_con_el_raton(self):
        w = MiniWidgetPip(self.vm)
        w.show()
        w.move(100, 100)
        origen = w.pos()

        def ev(tipo, x, y, boton, botones):
            return QMouseEvent(tipo, QPointF(5, 5), QPointF(x, y), boton, botones, Qt.KeyboardModifier.NoModifier)

        w.mousePressEvent(ev(QEvent.Type.MouseButtonPress, 110, 110, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton))
        w.mouseMoveEvent(ev(QEvent.Type.MouseMove, 210, 160, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton))
        self.assertEqual(w.pos() - origen, QPoint(100, 50))
        w.mouseReleaseEvent(ev(QEvent.Type.MouseButtonRelease, 210, 160, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton))
        w.mouseMoveEvent(ev(QEvent.Type.MouseMove, 400, 400, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton))
        self.assertEqual(w.pos() - origen, QPoint(100, 50))                   # suelto: ya no se mueve
        w.close()

    def test_cerrar_el_widget_libera_la_suscripcion(self):
        w = MiniWidgetPip(self.vm)
        w.mostrar_sincronizado()
        w.close()
        self.estado("77.0 BPM")
        self.assertNotEqual(w.lbl_bpm.text(), "77")


if __name__ == "__main__":
    unittest.main()
