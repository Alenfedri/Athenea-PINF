"""Zonas cardíacas Z1–Z5 y umbral de fatiga (BPM + RPM) de una actividad."""

import os
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from domain import zonas_actividad as za
from domain.modelos import Medicion
from services.repositorio_historial import RepositorioHistorial
from ui.barra_zonas import BarraZonas
from ui.main_window import MainWindow
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])
DIA = date.today() - timedelta(days=1)
INICIO = int(datetime(DIA.year, DIA.month, DIA.day, 10, 0).timestamp())


def med(i, ts, bpm, rpm=None):
    return Medicion(i, f"u{i}", ts, bpm, rpm, None, 1, "ACTIVIDAD", 1)


def sesion(minutos=30, paso=10, fallo_min=None, disparo_min=18, bpm0=110, bpm1=172):
    """BPM sube de forma lineal; RPM = 0,14·BPM (cociente constante) y, desde el minuto de disparo,
    la respiración sube 3 RPM por minuto mientras el pulso casi no cambia."""
    ms = []
    n = minutos * 60 // paso
    for i in range(n):
        t = i * paso
        m = t / 60
        bpm = bpm0 + (bpm1 - bpm0) * min(m, disparo_min) / disparo_min if disparo_min else bpm0 + (bpm1 - bpm0) * m / minutos
        rpm = 0.14 * bpm
        if disparo_min is not None and m > disparo_min:
            bpm += 0.3 * (m - disparo_min)
            rpm += 3.0 * (m - disparo_min)
        ms.append(med(i + 1, INICIO + t, bpm, rpm))
    return ms


class TestZonas(unittest.TestCase):

    def test_fronteras_de_zona_con_fcmax_190(self):
        # 60 % = 114, 70 % = 133, 80 % = 152, 90 % = 171
        casos = {100: 0, 113.9: 0, 114: 1, 132.9: 1, 133: 2, 151.9: 2, 152: 3, 170.9: 3, 171: 4, 195: 4}
        for bpm, zona in casos.items():
            self.assertEqual(za.zona_de(bpm, 190), zona, bpm)

    def test_reparto_exacto_de_tiempo(self):
        # 10 s por medición: 3×Z1, 6×Z2, 9×Z3, 12×Z4, 15×Z5 → 30, 60, 90, 120, 150 s
        bpms = [100] * 3 + [120] * 6 + [140] * 9 + [160] * 12 + [180] * 15
        ms = [med(i, INICIO + 10 * i, b) for i, b in enumerate(bpms)]
        r = za.repartir_zonas(ms, 190)
        self.assertEqual(r.segundos, (30, 60, 90, 120, 150))
        self.assertEqual(r.total_s, 450)
        self.assertAlmostEqual(sum(r.porcentajes), 100.0)
        self.assertAlmostEqual(r.porcentajes[4], 100 * 150 / 450)

    def test_fcmax_configurable(self):
        ms = [med(i, INICIO + 10 * i, 150) for i in range(10)]
        self.assertEqual(za.repartir_zonas(ms, 190).porcentajes[2], 100.0)    # 79 % → Z3
        self.assertEqual(za.repartir_zonas(ms, 160).porcentajes[4], 100.0)    # 94 % → Z5

    def test_los_huecos_no_cuentan_como_tiempo(self):
        ms = [med(i, INICIO + 10 * i, 120) for i in range(6)]
        ms += [med(10 + i, INICIO + 1000 + 10 * i, 120) for i in range(6)]    # 950 s sin datos
        self.assertEqual(za.repartir_zonas(ms, 190).total_s, 120)             # 12 mediciones × 10 s

    def test_sin_datos_suficientes(self):
        self.assertIsNone(za.repartir_zonas([], 190))
        self.assertIsNone(za.repartir_zonas([med(1, INICIO, 120)], 190))
        self.assertIsNone(za.repartir_zonas([med(1, INICIO, 120), med(2, INICIO, 125)], 190))   # mismo instante
        self.assertIsNone(za.repartir_zonas([med(i, INICIO + i, 0) for i in range(5)], 190))    # sin BPM válido


class TestUmbralFatiga(unittest.TestCase):

    def test_detecta_el_disparo_de_la_respiracion(self):
        r = za.detectar_umbral_fatiga(sesion(), INICIO)
        u = r.umbral
        self.assertIsNotNone(u, r.motivo)
        self.assertAlmostEqual(u.minuto, 18, delta=2)
        self.assertGreaterEqual(u.bpm, 0.70 * za.FC_MAX_REFERENCIA)           # ya en Z3 o más
        self.assertGreater(u.cociente, 1.25 * u.base)
        self.assertEqual(u.base, u.base)
        self.assertRegex(u.texto, r"^Umbral fatiga: min \d+ · \d+ BPM / \d+ RPM$")

    def test_sin_disparo_no_hay_umbral(self):
        r = za.detectar_umbral_fatiga(sesion(disparo_min=None), INICIO)
        self.assertIsNone(r.umbral)
        self.assertIn("no se aprecia", r.motivo.lower())

    def test_un_pico_aislado_de_respiracion_no_cuenta(self):
        ms = sesion(disparo_min=None)
        for i in (150, 151):                                                  # 20 s de respiración alta
            m = ms[i]
            ms[i] = Medicion(m.id, m.uid, m.ts, m.bpm, m.rpm * 2, None, 1, "ACTIVIDAD", 1)
        self.assertIsNone(za.detectar_umbral_fatiga(ms, INICIO).umbral)

    def test_disparo_en_zona_baja_no_es_umbral(self):
        # La respiración se dispara, pero el pulso se queda por debajo del 70 % (133 BPM)
        ms = sesion(bpm0=100, bpm1=120, disparo_min=10)
        self.assertIsNone(za.detectar_umbral_fatiga(ms, INICIO).umbral)

    def test_actividad_corta(self):
        r = za.detectar_umbral_fatiga(sesion(minutos=5, paso=2), INICIO)
        self.assertIsNone(r.umbral)
        self.assertIn("demasiado corta", r.motivo)

    def test_pocos_datos_o_sin_respiracion(self):
        self.assertIn("suficientes", za.detectar_umbral_fatiga([], INICIO).motivo)
        sin_rpm = [Medicion(m.id, m.uid, m.ts, m.bpm, None, None, 1, "ACTIVIDAD", 1) for m in sesion()]
        r = za.detectar_umbral_fatiga(sin_rpm, INICIO)
        self.assertIsNone(r.umbral)
        self.assertIn("suficientes", r.motivo)

    def test_datos_con_huecos_y_nulos_no_fallan(self):
        ms = [m for i, m in enumerate(sesion()) if not 50 <= i < 70]
        r = za.detectar_umbral_fatiga(ms, INICIO)
        self.assertTrue(r.umbral is not None or r.motivo)


class TestAnalisisConjunto(unittest.TestCase):

    def test_analizar_actividad(self):
        a = za.analizar_actividad(sesion(), INICIO)
        self.assertIsNotNone(a.zonas)
        self.assertIsNotNone(a.umbral.umbral)
        vacio = za.analizar_actividad([], INICIO)
        self.assertIsNone(vacio.zonas)
        self.assertIsNone(vacio.umbral.umbral)


class TestBarraZonas(unittest.TestCase):

    def test_anchos_proporcionales_y_leyenda(self):
        b = BarraZonas()
        b.mostrar(za.ReparticionZonas((60, 120, 0, 0, 60), 190))              # 25 / 50 / 0 / 0 / 25 %
        self.assertEqual(b.anchos, (0.25, 0.5, 0.0, 0.0, 0.25))
        texto = b.lbl_leyenda.text()
        self.assertIn("Z2", texto)
        self.assertIn("50 %", texto)
        self.assertIn("2,0 min", texto)
        self.assertIn("190", texto)

    def test_sin_datos(self):
        b = BarraZonas()
        b.mostrar(None)
        self.assertEqual(b.anchos, ())
        self.assertIn("sin datos", b.lbl_leyenda.text())


class TestPestanaActividades(unittest.TestCase):

    def setUp(self):
        self.repo = RepositorioHistorial(":memory:", usuario_id=1)
        self.vm = VitaBandViewModel(MagicMock(), repositorio=self.repo)
        self.ventana = MainWindow(self.vm, "Ana")
        self.vista = self.ventana.vista_actividades
        self.vista.selector.establecer_rango(DIA, DIA)

    def tearDown(self):
        self.ventana.close()
        self.vm.cerrar()

    def crear(self, medicion_list, fin_min):
        aid = self.repo.guardar_actividad("a1", INICIO, INICIO + fin_min * 60, "carrera")
        for m in medicion_list:
            self.repo.guardar_medicion(m.bpm, datetime.fromtimestamp(m.ts), uid=f"x{m.id}", rpm=m.rpm,
                                       etiqueta="ACTIVIDAD", actividad_id=aid, nivel_actividad=1)
        self.vista.actualizar()

    def test_actividad_con_disparo_muestra_zonas_linea_y_texto(self):
        self.crear(sesion(), 30)
        v = self.vista
        self.assertEqual(len(v.barra_zonas.anchos), 5)
        self.assertAlmostEqual(sum(v.barra_zonas.anchos), 1.0)
        self.assertRegex(v.lbl_umbral.text(), r"^Umbral fatiga: min \d+ · \d+ BPM / \d+ RPM$")
        self.assertIsNotNone(v.grafica_cruce.linea_umbral)
        self.assertEqual(v.grafica_cruce.etiqueta_umbral, v.lbl_umbral.text())
        self.assertGreater(v.grafica_cruce.puntos_bpm, 100)
        self.assertGreater(v.grafica_cruce.puntos_rpm, 100)

    def test_actividad_corta_lo_indica_sin_errores(self):
        self.crear(sesion(minutos=4, paso=5), 4)
        v = self.vista
        self.assertIn("demasiado corta", v.lbl_umbral.text())
        self.assertIsNone(v.grafica_cruce.linea_umbral)
        self.assertIn("demasiado corta", v.grafica_cruce.mensaje)
        self.assertEqual(len(v.barra_zonas.anchos), 5)

    def test_actividad_sin_mediciones(self):
        self.repo.guardar_actividad("a1", INICIO, INICIO + 600, "carrera")
        self.vista.actualizar()
        self.assertEqual(self.vista.barra_zonas.anchos, ())
        self.assertIn("suficientes", self.vista.lbl_umbral.text())

    def test_sin_actividades_limpia_todo(self):
        self.vista.actualizar()
        self.assertEqual(self.vista.barra_zonas.anchos, ())
        self.assertEqual(self.vista.lbl_umbral.text(), "")
        self.assertIsNone(self.vista.grafica_cruce.linea_umbral)

    def test_cambiar_de_actividad_quita_la_linea_anterior(self):
        self.crear(sesion(), 30)
        self.assertIsNotNone(self.vista.grafica_cruce.linea_umbral)
        self.repo.guardar_actividad("a2", INICIO + 7200, INICIO + 7500, "paseo")
        self.vista.actualizar()
        self.vista.tabla.selectRow(0 if self.vista.tabla.item(0, 0).data(256) != 1 else 1)
        self.vista._on_seleccion()
        # sea cual sea la fila elegida, nunca hay más de una línea dibujada
        self.assertLessEqual(sum(1 for i in self.vista.grafica_cruce.items()
                                 if i.__class__.__name__ == "InfiniteLine"), 1)

    def test_las_metricas_anteriores_siguen(self):
        self.crear(sesion(), 30)
        self.assertIn("Frecuencia", self.vista.lbl_estadisticas.text())
        self.assertIsNotNone(self.vista.grafica)


if __name__ == "__main__":
    unittest.main()
