"""Tests de la interfaz (sin pantalla): instanciación, integración con el ViewModel y componentes."""

import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from domain import ecg_historico as ecg
from domain.analisis import Interrupcion
from domain.modelos import ObservacionGuardada
from domain.observaciones import DESCARGO
from services.consultas_historial import ConsultasHistorial
from services.repositorio_historial import RepositorioHistorial
from services.servicio_sync import EstadoSync, ResultadoSync
from ui.formato import texto_interrupciones
from ui.grafica_ecg import GraficaEcg
from ui.main_window import MainWindow
from ui.panel_observaciones import PanelObservaciones
from ui.selector_rango import SelectorRango
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])

AYER = date.today() - timedelta(days=1)


def ts(h, m=0, s=0, dia=AYER):
    return int(datetime(dia.year, dia.month, dia.day, h, m, s).timestamp())


def dt(t):
    return datetime.fromtimestamp(t)


class BaseUi(unittest.TestCase):
    def setUp(self):
        self.mqtt = MagicMock()
        self.repo = RepositorioHistorial(":memory:", usuario_id=1)
        self.vm = VitaBandViewModel(self.mqtt, repositorio=self.repo)
        self.ventana = MainWindow(self.vm, "ana@correo.com")
        self.hist = self.ventana.vista_historial
        self.act = self.ventana.vista_actividades
        self.hist.selector.establecer_rango(AYER, AYER)

    def tearDown(self):
        self.ventana.close()
        self.vm.cerrar()
        self.ventana.deleteLater()

    def sembrar_con_hueco(self):
        # cada 10 min entre 8:00-8:30 y 10:30-11:00: interrupción de 2 h en medio
        for h, m in [(8, 0), (8, 10), (8, 20), (8, 30), (10, 30), (10, 40), (10, 50), (11, 0)]:
            self.repo.guardar_medicion(60 + m, dt(ts(h, m)), rpm=14, temp_c=36.5, nivel_actividad=0,
                                       uid=f"s{h}{m}")

    def sembrar_actividad(self):
        a = self.repo.guardar_actividad("a1", ts(9), ts(9, 10), "carrera")
        for i, bpm in enumerate((110, 130, 150)):
            self.repo.guardar_medicion(bpm, dt(ts(9, i * 3)), uid=f"x{i}", etiqueta="ACTIVIDAD",
                                       actividad_id=a, rpm=22, nivel_actividad=1)
        self.repo.guardar_ecg_segundos([ecg.SegundoEcg(ts(9, 0, i), 1000 + i, 2000 + i) for i in range(30)])
        self.repo.guardar_observacion("ACTIVIDAD", str(a), f"Resumen de carrera\n{DESCARGO}",
                                      ts(9), ts(9, 10), int(datetime.now().timestamp()), actividad_id=a)
        return a


class TestVentana(BaseUi):

    def test_pestanas_y_controles(self):
        p = self.ventana.pestanas
        self.assertEqual([p.tabText(i) for i in range(p.count())],
                         ["Tiempo real", "Historial periódico", "Actividades", "Análisis avanzado", "Planificación", "Modo Entrenador", "Coach IA"])
        self.assertEqual(self.ventana.btn_sincronizar.text(), "Sincronizar ahora")
        self.assertEqual(self.ventana.lbl_sync.text(), "Sincronización: Sin sincronizar")

    def test_el_estado_de_sync_se_pinta(self):
        self.vm._emitir_nuevo_estado(syncTexto="Todo al día", syncSincronizados=2, syncPendientes=1, syncErrores=3)
        self.assertEqual(self.ventana.lbl_sync.text(), "Sincronización: Todo al día")
        self.assertIn("Sincronizados: 2", self.ventana.lbl_sync.toolTip())
        self.assertIn("Con error: 3", self.ventana.lbl_sync.toolTip())

    def test_boton_sincronizar_llama_al_servicio(self):
        servicio = MagicMock()
        servicio.sincronizar.return_value = ResultadoSync(True)
        servicio.estado.return_value = EstadoSync(True, ())
        self.vm._sync = servicio
        self.ventana.btn_sincronizar.click()
        servicio.sincronizar.assert_called_once()
        self.assertEqual(self.ventana.lbl_sync.text(), "Sincronización: Todo al día")

    def test_cambiar_de_pestana_actualiza_la_vista(self):
        self.sembrar_actividad()
        self.ventana.pestanas.setCurrentWidget(self.act)
        self.assertEqual(self.act.tabla.rowCount(), 1)

    def test_exportar_csv_desde_la_ventana(self):
        self.sembrar_con_hueco()
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "x.csv")
            with patch("ui.main_window.QFileDialog.getSaveFileName", return_value=(ruta, "")), \
                 patch("ui.animations.show_toast") as info:
                self.ventana.btn_exportar_csv.click()
            self.assertTrue(os.path.exists(ruta))
            self.assertIn("8 registros", info.call_args.args[1])


class TestHistorialPeriodico(BaseUi):

    def test_datos_resumen_tabla_y_huecos(self):
        self.sembrar_con_hueco()
        self.hist.actualizar()
        self.assertIn("8 registros", self.hist.lbl_resumen.text())
        self.assertIn("sin agrupar", self.hist.lbl_resumen.text())
        self.assertEqual(self.hist.tabla.rowCount(), 8)
        self.assertEqual(self.hist.tabla.horizontalHeaderItem(0).text(), "Fecha y hora")
        self.assertGreaterEqual(self.hist.grafica.puntos, 8)
        self.assertGreaterEqual(self.hist.grafica.regiones, 1)              # la interrupción se sombrea
        self.assertIn("interrupción", self.hist.lbl_interrupciones.text())
        self.assertFalse(self.hist.grafica.tiene_barras)

    def test_agrupar_por_hora_muestra_huecos_como_sin_datos(self):
        self.sembrar_con_hueco()
        self.hist.selector.combo_resolucion.setCurrentIndex(
            self.hist.selector.combo_resolucion.findData("hora"))
        t = self.hist.tabla
        self.assertEqual(t.horizontalHeaderItem(0).text(), "Periodo")
        self.assertEqual(t.rowCount(), 24)
        textos = {t.item(i, 0).text()[-5:]: t.item(i, 1).text() for i in range(t.rowCount())}
        self.assertEqual(textos["08:00"], "4")
        self.assertEqual(textos["09:00"], "Sin datos")
        self.assertEqual(textos["10:00"], "3")
        self.assertTrue(self.hist.grafica.tiene_barras)
        self.assertIn("por hora", self.hist.lbl_resumen.text())

    def test_cambiar_variable(self):
        self.sembrar_con_hueco()
        s = self.hist.selector
        s.combo_variable.setCurrentIndex(s.combo_variable.findData("temp"))
        self.assertIn("°C", self.hist.lbl_resumen.text())
        self.assertIn("36.50", self.hist.lbl_resumen.text())

    def test_periodo_sin_datos(self):
        self.hist.selector.establecer_rango(AYER - timedelta(days=40), AYER - timedelta(days=39))
        self.assertEqual(self.hist.lbl_resumen.text(), "Sin registros en este periodo.")
        self.assertEqual(self.hist.tabla.rowCount(), 0)
        self.assertEqual(self.hist.grafica.regiones, 0)
        self.assertIn("sin datos", self.hist.grafica_ecg.getPlotItem().titleLabel.text)

    def test_ecg_historico_compacto(self):
        self.repo.guardar_ecg_segundos([ecg.SegundoEcg(ts(9, 0, i), 1000 + i, 2000 + i) for i in range(30)])
        self.hist.actualizar()
        self.assertGreater(self.hist.grafica_ecg.intervalos_dibujados, 0)

    def test_ecg_rango_demasiado_largo_avisa(self):
        self.hist.selector.establecer_ultimos_dias(30)
        self.assertEqual(self.hist.grafica_ecg.intervalos_dibujados, 0)
        self.assertIn("hasta 7 días", self.hist.grafica_ecg.getPlotItem().titleLabel.text)

    def test_observaciones_diarias(self):
        self.repo.guardar_observacion("DIARIA", AYER.isoformat(), f"Registros: 8\n{DESCARGO}",
                                      ts(0), ts(0) + 86400, 1)
        self.repo.guardar_observacion("ACTIVIDAD", "1", "de actividad", ts(9), ts(10), 1)
        self.hist.actualizar()
        texto = self.hist.observaciones.texto()
        self.assertIn(f"{AYER:%d/%m/%Y}", texto)
        self.assertIn("• Registros: 8", texto)
        self.assertNotIn("de actividad", texto)                  # las de actividad van en su pestaña
        self.assertNotIn(DESCARGO, texto)                        # el descargo es fijo, no se repite
        self.assertEqual(self.hist.observaciones.lbl_descargo.text(), DESCARGO)

    def test_solo_muestra_el_historial_periodico(self):
        a = self.repo.guardar_actividad("a", ts(9), ts(10))
        self.repo.guardar_medicion(70, dt(ts(8)), uid="p")
        self.repo.guardar_medicion(150, dt(ts(9)), uid="a", etiqueta="ACTIVIDAD", actividad_id=a)
        self.hist.actualizar()
        self.assertEqual(self.hist.tabla.rowCount(), 1)

    def test_llega_dato_nuevo_con_la_vista_visible(self):
        hoy = date.today()
        self.hist.selector.establecer_rango(hoy, hoy)
        self.ventana.pestanas.setCurrentWidget(self.hist)
        self.ventana.show()
        self.assertEqual(self.hist.tabla.rowCount(), 0)
        self.repo.guardar_medicion(70, datetime.now())
        self.vm.historial_actualizado.emit()
        self.assertEqual(self.hist.tabla.rowCount(), 1)

    def test_error_de_consulta_no_rompe_la_vista(self):
        self.vm._consultas = None
        self.hist.actualizar()
        self.assertEqual(self.hist.lbl_resumen.text(), "No se pudo consultar el historial.")


class TestActividades(BaseUi):

    def test_lista_y_detalle(self):
        self.sembrar_actividad()
        self.act.actualizar()
        t = self.act.tabla
        self.assertEqual(t.rowCount(), 1)
        self.assertEqual(t.item(0, 1).text(), "carrera")
        self.assertEqual(t.item(0, 2).text(), "10 min 00 s")
        self.assertEqual((t.item(0, 3).text(), t.item(0, 4).text(), t.item(0, 5).text()), ("3", "130.0", "150.0"))
        self.assertIsNotNone(self.act.actividad_seleccionada())
        self.assertIn("carrera", self.act.lbl_titulo.text())
        self.assertIn("Frecuencia cardíaca: media 130.0 BPM", self.act.lbl_estadisticas.text())
        self.assertGreaterEqual(self.act.grafica.puntos, 3)
        self.assertGreater(self.act.grafica_ecg.intervalos_dibujados, 0)
        self.assertIn("Resumen de carrera", self.act.observacion.texto())

    def test_cambiar_variable_redibuja(self):
        self.sembrar_actividad()
        self.act.actualizar()
        self.act.combo_variable.setCurrentIndex(self.act.combo_variable.findData("temp"))
        self.assertEqual(self.act.grafica.puntos, 0)                   # la actividad no tiene temperatura
        self.act.combo_variable.setCurrentIndex(self.act.combo_variable.findData("rpm"))
        self.assertGreaterEqual(self.act.grafica.puntos, 3)

    def test_sin_actividades(self):
        self.act.actualizar()
        self.assertEqual(self.act.tabla.rowCount(), 0)
        self.assertIsNone(self.act.actividad_seleccionada())
        self.assertIn("No hay actividades", self.act.lbl_titulo.text())
        self.assertEqual(self.act.grafica.puntos, 0)

    def test_se_conserva_la_seleccion_al_actualizar(self):
        self.sembrar_actividad()
        b = self.repo.guardar_actividad("a0", ts(7), ts(7, 5))
        self.act.actualizar()
        self.act.tabla.selectRow(1)                                    # la más antigua (orden: reciente primero)
        elegida = self.act.actividad_seleccionada()
        self.act.actualizar()
        self.assertEqual(self.act.actividad_seleccionada(), elegida)

    def test_actividad_sin_observacion_ni_ecg(self):
        self.repo.guardar_actividad("a", ts(9), ts(9, 5))
        self.act.actualizar()
        self.assertIn("aún no tiene observación", self.act.observacion.texto())
        self.assertEqual(self.act.grafica_ecg.intervalos_dibujados, 0)

    def test_rango_sin_actividades(self):
        self.sembrar_actividad()
        self.act.selector.establecer_rango(AYER - timedelta(days=60), AYER - timedelta(days=50))
        self.assertEqual(self.act.tabla.rowCount(), 0)


class TestComponentes(unittest.TestCase):

    def test_selector_mantiene_desde_menor_o_igual_que_hasta(self):
        s = SelectorRango()
        avisos = []
        s.cambiado.connect(lambda: avisos.append(1))
        s.establecer_rango(date(2026, 11, 10), date(2026, 11, 12))
        self.assertEqual(len(avisos), 1)
        s.establecer_rango(date(2026, 11, 12), date(2026, 11, 10))       # invertido: se reordena
        self.assertEqual(s.rango_dias(), (date(2026, 11, 10), date(2026, 11, 12)))
        s.fecha_desde.setDate(s.fecha_desde.date().addDays(5))            # desde > hasta: arrastra a hasta
        self.assertEqual(s.rango_dias()[0], s.rango_dias()[1])
        d, h = s.rango_ts()
        self.assertEqual(h - d, 86400)

    def test_selector_atajos_y_opciones(self):
        s = SelectorRango(rango_disponible=lambda: (int(datetime(2026, 1, 5, 10).timestamp()),
                                                    int(datetime(2026, 1, 9, 10).timestamp())))
        s.btn_7.click()
        d, h = s.rango_dias()
        self.assertEqual((h - d).days, 6)
        self.assertTrue(s.termina_hoy())
        s.btn_todo.click()
        self.assertEqual(s.rango_dias(), (date(2026, 1, 5), date(2026, 1, 9)))
        self.assertEqual(s.variable(), "bpm")
        self.assertEqual(s.resolucion(), "auto")
        simple = SelectorRango(con_variable=False, con_resolucion=False)
        self.assertEqual((simple.variable(), simple.resolucion(), simple.btn_todo), ("bpm", "auto", None))

    def test_panel_observaciones(self):
        p = PanelObservaciones()
        p.mostrar([])
        self.assertEqual(p.texto(), "Sin observaciones para este periodo.")
        o = ObservacionGuardada(1, "DIARIA", "2026-11-10", None, 0, 1, f"A\nB\n{DESCARGO}", 0)
        p.mostrar([o])
        self.assertIn("Día 10/11/2026", p.texto())
        self.assertIn("  • A\n  • B", p.texto())
        self.assertNotIn(DESCARGO, p.texto())

    def test_grafica_ecg(self):
        g = GraficaEcg()
        g.mostrar(None, 0, 10)
        self.assertEqual(g.intervalos_dibujados, 0)
        red = ecg.reducir([ecg.SegundoEcg(100 + i, 10, 20) for i in range(5)], 100, 110, 5)
        g.mostrar(red, 100, 110)
        self.assertEqual(g.intervalos_dibujados, 3)        # 5 s con señal en intervalos de 2 s: 3 con datos
        g.mostrar(red, 100, 110, "mensaje")
        self.assertEqual(g.intervalos_dibujados, 0)

    def test_texto_interrupciones(self):
        self.assertIn("Sin interrupciones", texto_interrupciones([]))
        huecos = [Interrupcion(1000 * i, 1000 * i + 600) for i in range(1, 8)]
        t = texto_interrupciones(huecos)
        self.assertIn("7 interrupción(es)", t)
        self.assertIn("… y 2 más", t)


if __name__ == "__main__":
    unittest.main()
