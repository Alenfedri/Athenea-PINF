"""TRIMP, carga aguda:crónica, HRR-60, deriva cardíaca, tarjetas semanales y su integración en la UI."""

import os
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from domain.modelos import Medicion
from services import metricas_avanzadas as ma
from services.repositorio_historial import RepositorioHistorial
from services.servicio_observaciones import ServicioObservaciones
from ui.main_window import MainWindow
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])
HOY = date.today()
DIA = HOY - timedelta(days=1)
AHORA = int(datetime(HOY.year, HOY.month, HOY.day, 12).timestamp())
D = 86400


def ts(dia, h=8, m=0):
    return int(datetime(dia.year, dia.month, dia.day, h, m).timestamp())


def serie(n, bpm, rpm=20.0, temp=None, t0=0, paso=10, id0=1):
    f = lambda v, i: v(i) if callable(v) else v
    return [Medicion(id0 + i, f"m{id0}-{i}", t0 + i * paso, f(bpm, i), f(rpm, i), f(temp, i), 1, "ACTIVIDAD", 1)
            for i in range(n)]


class TestTrimp(unittest.TestCase):

    def test_pesos_por_zona(self):
        self.assertAlmostEqual(ma.trimp(serie(36, 140)), 18.0)                    # 6 min en Z3 · 3
        self.assertAlmostEqual(ma.trimp(serie(36, 100) + serie(36, 180, t0=360, id0=100)), 6 * 1 + 6 * 5)

    def test_cada_zona(self):
        for bpm, peso in ((100, 1), (120, 2), (140, 3), (160, 4), (180, 5)):
            self.assertAlmostEqual(ma.trimp(serie(36, bpm)), 6 * peso, msg=bpm)

    def test_fc_max_distinta_cambia_la_zona(self):
        self.assertAlmostEqual(ma.trimp(serie(36, 140), fc_max=150), 6 * 5)

    def test_sin_datos(self):
        self.assertIsNone(ma.trimp([]))
        self.assertIsNone(ma.trimp(serie(1, 140)))


class TestEstadoCarga(unittest.TestCase):

    def semanal(self, trimps, dias):
        return [(AHORA - d * D, t) for d, t in zip(dias, trimps)]

    def test_clasificacion_por_ratio_y_bordes(self):
        self.assertEqual(ma.clasificar_ratio(0.79), "Carga baja")
        self.assertEqual(ma.clasificar_ratio(0.8), "Carga óptima")
        self.assertEqual(ma.clasificar_ratio(1.3), "Carga óptima")
        self.assertEqual(ma.clasificar_ratio(1.31), "Riesgo de sobreentrenamiento")

    def test_optima(self):
        e = ma.estado_carga(self.semanal([100] * 4, [1, 8, 15, 22]), AHORA)
        self.assertEqual((e.estado, e.umbrales_fijos), ("Carga óptima", False))
        self.assertAlmostEqual(e.ratio, 1.0)
        self.assertEqual((e.aguda, e.cronica), (100, 100))

    def test_riesgo(self):
        e = ma.estado_carga(self.semanal([100, 150, 100, 100, 100], [1, 2, 9, 16, 23]), AHORA)
        self.assertEqual(e.estado, "Riesgo de sobreentrenamiento")
        self.assertGreater(e.ratio, 1.3)

    def test_baja_sin_sesiones_esta_semana(self):
        e = ma.estado_carga(self.semanal([100] * 4, [8, 15, 22, 27]), AHORA)
        self.assertEqual(e.estado, "Carga baja")
        self.assertEqual(e.aguda, 0)

    def test_poco_historial_usa_umbrales_fijos(self):
        for trimp, esperado in ((50, "Carga baja"), (200, "Carga óptima"), (400, "Riesgo de sobreentrenamiento")):
            e = ma.estado_carga([(AHORA - 3 * D, trimp)], AHORA)
            self.assertEqual(e.estado, esperado)
            self.assertTrue(e.umbrales_fijos)
            self.assertIsNone(e.ratio)
            self.assertIn("umbrales fijos", e.texto)

    def test_sin_sesiones_o_fuera_de_ventana(self):
        self.assertEqual(ma.estado_carga([], AHORA).estado, "Sin datos")
        self.assertEqual(ma.estado_carga([(AHORA - 40 * D, 300)], AHORA).estado, "Sin datos")
        self.assertIn("sin sesiones", ma.estado_carga([], AHORA).texto)

    def test_ignora_sesiones_futuras(self):
        e = ma.estado_carga([(AHORA + D, 900), (AHORA - 2 * D, 100)], AHORA)
        self.assertEqual(e.aguda, 100)


class TestHrr60(unittest.TestCase):

    def test_caida_en_un_minuto(self):
        ms = serie(10, lambda i: [120, 140, 170, 165, 160, 150, 145, 140, 130, 128][i])
        self.assertEqual(ma.hrr60(ms), 40)                          # pico 170 en t=20; t=80 → 130
        self.assertEqual(ma.texto_hrr60(40), "40 BPM")

    def test_sesion_termina_antes_del_minuto(self):
        ms = serie(6, lambda i: [120, 140, 170, 165, 160, 150][i])         # pico en t=20, termina en t=50
        self.assertIsNone(ma.hrr60(ms))
        self.assertEqual(ma.texto_hrr60(None), "N/D")

    def test_pico_al_final_y_huecos_y_vacio(self):
        self.assertIsNone(ma.hrr60(serie(10, lambda i: 100 + i * 5)))
        self.assertIsNone(ma.hrr60([]))
        self.assertIsNone(ma.hrr60(serie(1, 150)))
        con_hueco = serie(3, lambda i: [150, 170, 160][i]) + serie(1, 120, t0=200, id0=50)    # siguiente muestra a +180 s
        self.assertIsNone(ma.hrr60(con_hueco))

    def test_empate_toma_el_primer_maximo(self):
        ms = serie(10, lambda i: [120, 170, 170, 160, 150, 150, 140, 140, 130, 130][i])
        self.assertEqual(ma.hrr60(ms), 170 - 140)                   # pico en t=10 → t=70


class TestDeriva(unittest.TestCase):

    def sesion(self, bpm=(140, 150), rpm=(20, 20), temp=(36.8, 37.4), minutos=30):
        n = minutos * 6
        mitad = n // 2
        pick = lambda par, i: par[0] if i < mitad else par[1]
        ms = serie(n, lambda i: pick(bpm, i), (lambda i: pick(rpm, i)) if rpm else None,
                   (lambda i: pick(temp, i)) if temp else None)
        return ms, 0, minutos * 60

    def test_detecta_con_delta_de_temperatura(self):
        d = ma.deriva_cardiaca(*self.sesion())
        self.assertIsNotNone(d)
        self.assertAlmostEqual(d.subida_pct, 7.14, places=1)
        self.assertIn("Deriva cardíaca", d.texto)
        self.assertIn("deshidratación", d.texto)

    def test_detecta_con_temperatura_alta_aunque_no_suba(self):
        self.assertIsNotNone(ma.deriva_cardiaca(*self.sesion(temp=(37.9, 37.9))))

    def test_no_detecta_si_falta_una_condicion(self):
        self.assertIsNone(ma.deriva_cardiaca(*self.sesion(bpm=(140, 144))))             # +2,9 %
        self.assertIsNone(ma.deriva_cardiaca(*self.sesion(rpm=(20, 24))))               # respiración +20 %
        self.assertIsNone(ma.deriva_cardiaca(*self.sesion(temp=(36.8, 37.0))))          # +0,2 °C y < 37,8
        self.assertIsNone(ma.deriva_cardiaca(*self.sesion(minutos=15)))                 # < 20 min

    def test_sin_respiracion_o_sin_temperatura_no_se_afirma_nada(self):
        self.assertIsNone(ma.deriva_cardiaca(*self.sesion(rpm=None)))
        self.assertIsNone(ma.deriva_cardiaca(*self.sesion(temp=None)))

    def test_bordes_exactos(self):
        self.assertIsNotNone(ma.deriva_cardiaca(*self.sesion(bpm=(100, 105))))          # +5 % justo
        self.assertIsNotNone(ma.deriva_cardiaca(*self.sesion(temp=(36.0, 36.4))))       # +0,4 °C justo
        self.assertIsNone(ma.deriva_cardiaca(*self.sesion(rpm=(20, 22))))               # +10 % no es < 10 %

    def test_sin_datos(self):
        self.assertIsNone(ma.deriva_cardiaca([], 0, 3600))

    def test_el_servicio_de_observaciones_la_registra(self):
        repo = RepositorioHistorial(":memory:", usuario_id=1)
        ini = ts(DIA)
        aid = repo.guardar_actividad("a1", ini, ini + 1800, "carrera")
        for i in range(180):
            repo.guardar_medicion(140 if i < 90 else 150, datetime.fromtimestamp(ini + i * 10), uid=f"d{i}",
                                  rpm=20, temp_c=36.8 if i < 90 else 37.4, etiqueta="ACTIVIDAD",
                                  actividad_id=aid, nivel_actividad=1)
        ServicioObservaciones(repo, reloj=lambda: AHORA).actualizar_todo()
        texto = repo.observacion_actividad(aid).texto
        self.assertIn("Deriva cardíaca", texto)
        self.assertTrue(texto.rstrip().endswith("diagnóstico médico."))           # el descargo sigue al final


class TestTarjetas(unittest.TestCase):

    def test_variacion_flecha_y_color(self):
        t = ma.Tarjeta("HRV media (RMSSD)", "ms", 50.0, 40.0, True)
        self.assertEqual((t.delta, t.pct, t.flecha, t.color), (10.0, 25.0, "▲", "#1e8e3e"))
        t = ma.Tarjeta("FC en reposo media", "BPM", 60.0, 65.0, False)
        self.assertEqual((t.flecha, t.color), ("▼", "#1e8e3e"))                       # bajar la FC en reposo es bueno
        self.assertEqual(ma.Tarjeta("x", "", 70.0, 65.0, False).color, "#c0392b")
        self.assertEqual(ma.Tarjeta("Minutos activos", "min", 70.0, 65.0, None).color, "#777777")

    def test_sin_datos_o_anterior_cero(self):
        t = ma.Tarjeta("x", "", None, 5.0, True)
        self.assertEqual((t.delta, t.pct, t.flecha), (None, None, "–"))
        self.assertIsNone(ma.Tarjeta("x", "", 5.0, 0.0, True).pct)

    def test_con_repositorio(self):
        repo = RepositorioHistorial(":memory:", usuario_id=1)
        ini1, ini2 = ts(HOY - timedelta(days=2)), ts(HOY - timedelta(days=10))
        for ini, minutos, bpm in ((ini1, 60, 140), (ini2, 30, 120)):
            aid = repo.guardar_actividad(f"a{ini}", ini, ini + minutos * 60, "carrera")
            for i in range(minutos * 6):
                repo.guardar_medicion(bpm, datetime.fromtimestamp(ini + i * 10), uid=f"{ini}-{i}",
                                      etiqueta="ACTIVIDAD", actividad_id=aid, nivel_actividad=1)
        from domain import hrv
        repo.guardar_hrv(hrv.ResultadoHrv(ts(HOY - timedelta(days=3)), 50.0, 60.0, 60))
        repo.guardar_hrv(hrv.ResultadoHrv(ts(HOY - timedelta(days=9)), 40.0, 60.0, 60))
        minutos, carga, hrv_m, reposo = ma.tarjetas_semanales(repo, AHORA)
        self.assertEqual((minutos.actual, minutos.anterior), (60.0, 30.0))
        self.assertAlmostEqual(carga.actual, 60 * 3)
        self.assertAlmostEqual(carga.anterior, 30 * 2)
        self.assertEqual((hrv_m.actual, hrv_m.anterior), (50.0, 40.0))
        self.assertIsNone(reposo.actual)                      # sin mediciones periódicas en reposo

    def test_repositorio_vacio(self):
        tarjetas = ma.tarjetas_semanales(RepositorioHistorial(":memory:", usuario_id=1), AHORA)
        self.assertEqual(len(tarjetas), 4)
        self.assertTrue(all(t.actual is None and t.delta is None for t in tarjetas))


class TestUI(unittest.TestCase):

    def setUp(self):
        self.repo = RepositorioHistorial(":memory:", usuario_id=1)
        ini = ts(DIA)
        self.aid = self.repo.guardar_actividad("a1", ini, ini + 1800, "carrera")
        for i in range(180):
            self.repo.guardar_medicion(
                [120, 150, 175, 170, 160, 150, 145, 140, 135][i % 9] if i < 9 else 140, datetime.fromtimestamp(ini + i * 10),
                uid=f"u{i}", rpm=20, temp_c=36.8, etiqueta="ACTIVIDAD", actividad_id=self.aid, nivel_actividad=1)
        self.vm = VitaBandViewModel(MagicMock(), repositorio=self.repo)
        self.ventana = MainWindow(self.vm, "Ana")
        self.v = self.ventana.vista_actividades
        self.v.selector.establecer_rango(DIA, DIA)
        self.v.actualizar()

    def tearDown(self):
        self.ventana.close()
        self.vm.cerrar()

    def test_actividades_muestra_carga_trimp_y_hrr(self):
        self.assertIn("TRIMP 7 días", self.v.lbl_carga.text()) if self.vm.carga_entrenamiento().estado != "Sin datos" \
            else None
        self.assertIn("Carga", self.v.lbl_carga.text())
        texto = self.v.lbl_estadisticas.text()
        self.assertIn("TRIMP:", texto)
        self.assertIn("HRR-60", texto)
        self.assertIn("HRR-60): 40 BPM", texto)                    # pico 175 en t=20 → 135 a t=80

    def test_hrr_nd_si_la_sesion_termina_antes(self):
        self.repo.borrar_actividad(self.aid)
        ini = ts(DIA, 10)
        aid = self.repo.guardar_actividad("a2", ini, ini + 50, "carrera")
        for i, b in enumerate((120, 140, 170, 160, 150)):
            self.repo.guardar_medicion(b, datetime.fromtimestamp(ini + i * 10), uid=f"c{i}",
                                       etiqueta="ACTIVIDAD", actividad_id=aid, nivel_actividad=1)
        self.v.actualizar()
        self.assertIn("HRR-60): N/D", self.v.lbl_estadisticas.text())

    def test_boton_tcx_segun_estado(self):
        self.assertTrue(self.v.btn_tcx.isEnabled())
        self.v.chk_comparar.setChecked(True)
        self.assertFalse(self.v.btn_tcx.isEnabled())
        self.v.chk_comparar.setChecked(False)
        self.assertTrue(self.v.btn_tcx.isEnabled())

    def test_exportar_tcx_desde_la_ui(self):
        import tempfile
        import xml.etree.ElementTree as ET
        ruta = os.path.join(tempfile.mkdtemp(), "a.tcx")
        with patch("ui.vista_actividades.QFileDialog.getSaveFileName", return_value=(ruta, "")) as dlg, \
             patch("ui.vista_actividades.QMessageBox.information") as info:
            self.v.btn_tcx.click()
        self.assertIn("*.tcx", dlg.call_args.args[3])
        self.assertEqual(len(ET.parse(ruta).getroot().findall(".//{*}Trackpoint")), 180)
        self.assertIn(ruta, info.call_args.args[2])
        with patch("ui.vista_actividades.QFileDialog.getSaveFileName", return_value=("", "")), \
             patch("ui.vista_actividades.QMessageBox.information") as info:
            self.v.btn_tcx.click()
        info.assert_not_called()

    def test_dashboard_semanal_en_historial(self):
        h = self.ventana.vista_historial
        h.actualizar()
        nombres = [w.lbl_nombre.text() for w in h.tarjetas.tarjetas]
        self.assertEqual(nombres, ["Minutos activos", "Carga acumulada (TRIMP)", "HRV media (RMSSD)",
                                   "FC en reposo media"])
        self.assertIn("Carga", h.tarjetas.lbl_carga.text())
        self.assertIn("min", h.tarjetas.tarjetas[0].lbl_valor.text())

    def test_dashboard_sin_datos_no_falla(self):
        vm = VitaBandViewModel(MagicMock(), repositorio=RepositorioHistorial(":memory:", usuario_id=1))
        v = MainWindow(vm, "Ana")
        for w in v.vista_historial.tarjetas.tarjetas:
            self.assertEqual(w.lbl_valor.text(), "—")
            self.assertIn("sin datos", w.lbl_cambio.text())
        v.close(); vm.cerrar()
        sin_repo = VitaBandViewModel(MagicMock())
        self.assertEqual(sin_repo.tarjetas_semanales(), [])
        self.assertEqual(sin_repo.carga_entrenamiento().estado, "Sin datos")
        sin_repo.cerrar()


if __name__ == "__main__":
    unittest.main()
