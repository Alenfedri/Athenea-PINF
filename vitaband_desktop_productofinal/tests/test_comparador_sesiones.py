"""Comparador «Antes vs. Ahora»: alineación en el minuto 0, orden por fecha y diferencias."""

import os
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QAbstractItemView, QApplication

from domain import comparador_sesiones as cs
from domain.modelos import Actividad, Medicion
from services.repositorio_historial import RepositorioHistorial
from ui.main_window import MainWindow
from ui.panel_comparador import PanelComparador, _GraficaMinutos
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])
DIA = date.today() - timedelta(days=1)
T0 = int(datetime(DIA.year, DIA.month, DIA.day, 8, 0).timestamp())


def actividad(id_, inicio, minutos, tipo="carrera"):
    return Actividad(id_, f"a{id_}", inicio, inicio + minutos * 60, tipo)


def mediciones(inicio, minutos, bpm, rpm, paso=10, desfase=0, id0=1):
    return [Medicion(id0 + i, f"m{id0}-{i}", inicio + desfase + i * paso,
                     bpm(i) if callable(bpm) else bpm, rpm(i) if callable(rpm) else rpm,
                     None, 1, "ACTIVIDAD", 1)
            for i in range((minutos * 60 - desfase) // paso)]


class TestAlineacion(unittest.TestCase):

    def test_cada_sesion_arranca_en_el_minuto_0(self):
        a, b = actividad(1, T0, 20), actividad(2, T0 + 86400 * 3, 30)
        c = cs.comparar((a, mediciones(a.inicio_ts, 20, 140, 25)), (b, mediciones(b.inicio_ts, 30, 150, 28)))
        for s in (c.antes, c.ahora):
            self.assertEqual(s.bpm[0][0], 0.0)
            self.assertEqual(s.rpm[0][0], 0.0)
        self.assertAlmostEqual(c.antes.bpm[-1][0], 20 - 1 / 6)          # última muestra: 19 min 50 s
        self.assertAlmostEqual(c.ahora.bpm[-1][0], 30 - 1 / 6)

    def test_t_rel_es_t_menos_inicio_entre_60(self):
        a = actividad(1, T0 + 5000, 10)
        m = [Medicion(1, "x", a.inicio_ts + 90, 120, 18, None, 1, "ACTIVIDAD", 1)]
        self.assertEqual(cs.serie_relativa(m, a.inicio_ts, "bpm"), ((1.5, 120.0),))
        self.assertEqual(cs.serie_relativa(m, a.inicio_ts, "rpm"), ((1.5, 18.0),))

    def test_si_la_primera_muestra_llega_tarde_la_curva_no_se_desplaza(self):
        a = actividad(1, T0, 10)
        s = cs._sesion("Antes", a, mediciones(a.inicio_ts, 10, 130, 20, desfase=30))
        self.assertAlmostEqual(s.bpm[0][0], 0.5)                        # el origen es el inicio de la sesión

    def test_series_ordenadas_aunque_las_mediciones_vengan_desordenadas(self):
        a = actividad(1, T0, 5)
        m = mediciones(a.inicio_ts, 5, 130, 20)
        serie = cs.serie_relativa(list(reversed(m)), a.inicio_ts, "bpm")
        self.assertEqual([p[0] for p in serie], sorted(p[0] for p in serie))

    def test_valores_nulos_se_omiten(self):
        a = actividad(1, T0, 5)
        m = [Medicion(1, "x", T0, 120, None, None, 1, "ACTIVIDAD", 1),
             Medicion(2, "y", T0 + 10, 0, 18, None, 1, "ACTIVIDAD", 1)]
        self.assertEqual(len(cs.serie_relativa(m, T0, "rpm")), 1)
        self.assertEqual(len(cs.serie_relativa(m, T0, "bpm")), 1)       # BPM 0 no es una lectura válida


class TestAntesAhora(unittest.TestCase):

    def test_se_identifican_por_fecha_sin_importar_el_orden_de_entrada(self):
        vieja, nueva = actividad(7, T0, 20), actividad(3, T0 + 86400, 20)    # el id más alto es el más antiguo
        mv, mn = mediciones(vieja.inicio_ts, 20, 150, 25), mediciones(nueva.inicio_ts, 20, 140, 22)
        for orden in ((vieja, mv), (nueva, mn)), ((nueva, mn), (vieja, mv)):
            c = cs.comparar(*orden)
            self.assertEqual((c.antes.etiqueta, c.ahora.etiqueta), ("Antes", "Ahora"))
            self.assertEqual(c.antes.actividad.id, 7)
            self.assertEqual(c.ahora.actividad.id, 3)

    def test_mismo_inicio_desempata_por_id(self):
        a, b = actividad(5, T0, 10), actividad(4, T0, 10)
        c = cs.comparar((a, []), (b, []))
        self.assertEqual((c.antes.actividad.id, c.ahora.actividad.id), (4, 5))


class TestDiferencias(unittest.TestCase):

    def test_diferencias_ahora_menos_antes_con_duraciones_distintas(self):
        antes, ahora = actividad(1, T0, 20), actividad(2, T0 + 86400 * 7, 35)
        m_antes = mediciones(antes.inicio_ts, 20, lambda i: 140 + (i % 3), 24)          # 140,141,142…
        m_ahora = mediciones(ahora.inicio_ts, 35, lambda i: 130 + (i % 4), 21, id0=1000)
        c = cs.comparar((ahora, m_ahora), (antes, m_antes))
        bpm_a = np.mean([140 + (i % 3) for i in range(120)])
        bpm_b = np.mean([130 + (i % 4) for i in range(210)])
        self.assertAlmostEqual(c.antes.bpm_medio, bpm_a)
        self.assertAlmostEqual(c.ahora.bpm_medio, bpm_b)
        self.assertAlmostEqual(c.d_bpm_medio, bpm_b - bpm_a)
        self.assertEqual((c.antes.bpm_max, c.ahora.bpm_max), (142.0, 133.0))
        self.assertAlmostEqual(c.d_bpm_max, -9.0)
        self.assertAlmostEqual(c.d_rpm_medio, -3.0)
        self.assertEqual(c.d_duracion_s, 15 * 60)
        self.assertEqual((c.antes.duracion_s, c.ahora.duracion_s), (1200, 2100))

    def test_sin_respiracion_en_una_sesion_la_diferencia_es_none(self):
        a, b = actividad(1, T0, 10), actividad(2, T0 + 86400, 10)
        c = cs.comparar((a, mediciones(a.inicio_ts, 10, 140, None)), (b, mediciones(b.inicio_ts, 10, 135, 20)))
        self.assertIsNone(c.antes.rpm_medio)
        self.assertIsNone(c.d_rpm_medio)
        self.assertAlmostEqual(c.d_bpm_medio, -5.0)

    def test_sesiones_sin_mediciones_no_fallan(self):
        a, b = actividad(1, T0, 10), actividad(2, T0 + 86400, 12)
        c = cs.comparar((a, []), (b, []))
        self.assertIsNone(c.d_bpm_medio)
        self.assertIsNone(c.d_bpm_max)
        self.assertEqual(c.d_duracion_s, 120)
        self.assertEqual(c.antes.bpm, ())


class TestViewModelYVista(unittest.TestCase):

    def setUp(self):
        self.repo = RepositorioHistorial(":memory:", usuario_id=1)
        self.vm = VitaBandViewModel(MagicMock(), repositorio=self.repo)
        self.ventana = MainWindow(self.vm, "Ana")
        self.v = self.ventana.vista_actividades
        self.v.selector.establecer_rango(DIA, DIA)
        self.ids = [self.crear(0, 20, 140, 24), self.crear(3 * 3600, 30, 132, 21), self.crear(6 * 3600, 25, 138, 23)]
        self.v.actualizar()

    def tearDown(self):
        self.ventana.close()
        self.vm.cerrar()

    def crear(self, desfase_s, minutos, bpm, rpm):
        ini = T0 + desfase_s
        aid = self.repo.guardar_actividad(f"u{ini}", ini, ini + minutos * 60, "carrera")
        for i in range(minutos * 6):
            self.repo.guardar_medicion(bpm + (i % 3), datetime.fromtimestamp(ini + 10 * i), uid=f"{ini}-{i}",
                                       rpm=rpm, etiqueta="ACTIVIDAD", actividad_id=aid, nivel_actividad=1)
        return aid

    def marcar(self, *filas):
        self.v.tabla.clearSelection()
        for f in filas:
            self.v.tabla.selectionModel().select(
                self.v.tabla.model().index(f, 0),
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)

    def ids_por_fila(self):
        return [self.v.tabla.item(f, 0).data(256) for f in range(self.v.tabla.rowCount())]

    # --- ViewModel ---
    def test_vm_compara_dos_y_rechaza_casos_invalidos(self):
        a, b = self.ids[0], self.ids[1]
        c = self.vm.comparar_actividades(b, a)                       # orden de entrada invertido
        self.assertEqual((c.antes.actividad.id, c.ahora.actividad.id), (a, b))
        self.assertIsNone(self.vm.comparar_actividades(a, a))
        self.assertIsNone(self.vm.comparar_actividades(a, 99999))

    # --- Vista individual intacta ---
    def test_por_defecto_la_vista_individual_sigue_igual(self):
        self.assertFalse(self.v.comparando)
        self.assertEqual(self.v.pila.currentIndex(), 0)
        self.assertEqual(self.v.tabla.selectionMode(), QAbstractItemView.SelectionMode.SingleSelection)
        self.assertEqual(len(self.v.actividades_seleccionadas()), 1)
        self.assertIn("Actividad", self.v.lbl_titulo.text())
        self.assertTrue(self.v.btn_eliminar.isEnabled())

    # --- Modo comparar ---
    def test_activar_el_modo_cambia_de_panel_y_conserva_la_fila_actual(self):
        actual = self.v.actividad_seleccionada()
        self.v.chk_comparar.setChecked(True)
        self.assertEqual(self.v.pila.currentIndex(), 1)
        self.assertEqual(self.v.tabla.selectionMode(), QAbstractItemView.SelectionMode.MultiSelection)
        self.assertEqual(self.v.actividades_seleccionadas(), [actual])
        self.assertIn("segunda sesión", self.v.comparador.lbl_mensaje.text())
        self.assertFalse(self.v.btn_eliminar.isEnabled())              # no se elimina nada comparando

    def test_cero_una_y_mas_de_dos_sesiones_muestran_un_mensaje_sin_errores(self):
        self.v.chk_comparar.setChecked(True)
        for filas, texto in (((), "dos sesiones"), ((0,), "segunda"), ((0, 1, 2), "3 sesiones")):
            self.marcar(*filas)
            self.v._on_seleccion()
            self.assertIn(texto, self.v.comparador.lbl_mensaje.text())
            self.assertFalse(self.v.comparador.grafica_bpm.isVisibleTo(self.v.comparador))

    def test_dos_sesiones_superponen_bpm_y_rpm_desde_el_minuto_0(self):
        self.v.chk_comparar.setChecked(True)
        self.marcar(0, 2)
        self.v._on_seleccion()
        p = self.v.comparador
        self.assertTrue(p.grafica_bpm.isVisibleTo(p))
        for g in (p.grafica_bpm, p.grafica_rpm):
            xa, ya = _GraficaMinutos.datos(g.curva_antes)
            xb, yb = _GraficaMinutos.datos(g.curva_ahora)
            self.assertEqual((xa[0], xb[0]), (0.0, 0.0))
            self.assertGreater(len(xa), 100)
            self.assertGreater(len(xb), 100)
        # Antes dura 20 min y Ahora 30: la comparación se hace en tiempo relativo, no absoluto
        xa, _ = _GraficaMinutos.datos(p.grafica_bpm.curva_antes)
        xb, _ = _GraficaMinutos.datos(p.grafica_bpm.curva_ahora)
        self.assertLess(np.nanmax(xa), np.nanmax(xb))
        self.assertIn("Antes", p.lbl_resumen.text())
        self.assertIn("Ahora", p.lbl_resumen.text())

    def test_estilos_ahora_continua_y_antes_discontinua(self):
        g = PanelComparador().grafica_bpm
        self.assertNotEqual(g.curva_antes.opts["pen"].style(), g.curva_ahora.opts["pen"].style())

    def test_resumen_con_las_diferencias(self):
        self.v.chk_comparar.setChecked(True)
        self.marcar(0, 1)
        self.v._on_seleccion()
        a, b = self.v.actividades_seleccionadas()
        c = self.vm.comparar_actividades(a, b)
        texto = self.v.comparador.lbl_resumen.text()
        self.assertIn(f"{c.d_bpm_medio:+.1f}".replace(".", ","), texto)
        self.assertIn(f"{c.d_rpm_medio:+.1f}".replace(".", ","), texto)
        self.assertIn("esfuerzo fue equivalente", texto)

    def test_el_orden_de_marcado_no_cambia_antes_y_ahora(self):
        self.v.chk_comparar.setChecked(True)
        self.marcar(2, 0)
        self.v._on_seleccion()
        c = self.vm.comparar_actividades(self.ids[2], self.ids[0])
        self.assertEqual((c.antes.actividad.id, c.ahora.actividad.id), (self.ids[0], self.ids[2]))
        self.assertIn(c.antes.actividad.id, self.v.actividades_seleccionadas())

    def test_desactivar_el_modo_vuelve_a_la_vista_individual(self):
        self.v.chk_comparar.setChecked(True)
        self.marcar(0, 1)
        self.v._on_seleccion()
        self.v.chk_comparar.setChecked(False)
        self.assertEqual(self.v.pila.currentIndex(), 0)
        self.assertEqual(self.v.tabla.selectionMode(), QAbstractItemView.SelectionMode.SingleSelection)
        self.assertEqual(len(self.v.actividades_seleccionadas()), 1)
        self.assertIn("Actividad", self.v.lbl_titulo.text())
        self.assertTrue(self.v.btn_eliminar.isEnabled())

    def test_actualizar_conserva_las_dos_marcadas(self):
        self.v.chk_comparar.setChecked(True)
        self.marcar(0, 2)
        previas = self.v.actividades_seleccionadas()
        self.v.actualizar()
        self.assertEqual(self.v.actividades_seleccionadas(), previas)
        self.assertEqual(len(previas), 2)

    def test_sin_actividades_el_modo_comparar_no_falla(self):
        self.repo.borrar_todo()
        self.v.actualizar()
        self.v.chk_comparar.setChecked(True)
        self.assertIn("dos sesiones", self.v.comparador.lbl_mensaje.text())
        self.v.chk_comparar.setChecked(False)
        self.assertEqual(self.v.actividades_seleccionadas(), [])


if __name__ == "__main__":
    unittest.main()
