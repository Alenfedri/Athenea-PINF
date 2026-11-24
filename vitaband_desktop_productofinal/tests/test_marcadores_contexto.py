"""Marcadores de contexto en el historial periódico y su cruce en las observaciones."""

import os
import sqlite3
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from domain import hrv, marcadores_contexto as ctx
from services.repositorio_cuentas import RepositorioCuentas
from services.repositorio_historial import RepositorioHistorial, TABLAS_DE_USUARIO
from services.servicio_observaciones import ServicioObservaciones
from ui.main_window import MainWindow
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])
HOY = date.today()


def ts(dia: date, h=8, m=0) -> int:
    return int(datetime(dia.year, dia.month, dia.day, h, m).timestamp())


def sembrar_dia(repo, dia, bpm, rmssd=None, n=12):
    for i in range(n):
        repo.guardar_medicion(bpm, datetime.fromtimestamp(ts(dia, 7, 0) + i * 10), uid=f"{dia}-{i}",
                              rpm=15, nivel_actividad=0)
    if rmssd is not None:
        for k in range(hrv.UmbralesHrv.min_ventanas):
            repo.guardar_hrv(hrv.ResultadoHrv(ts(dia, 7, k), rmssd, bpm, 60))


def servicio(repo):
    return ServicioObservaciones(repo, reloj=lambda: ts(HOY, 23, 0))


class TestPersistencia(unittest.TestCase):

    def setUp(self):
        self.repo = RepositorioHistorial(":memory:", usuario_id=1)

    def test_guardar_leer_y_quitar(self):
        a, b = ts(HOY, 9), ts(HOY, 15)
        self.repo.guardar_marcador(a, "Café")
        self.repo.guardar_marcador(b, "Estrés")
        self.assertEqual(self.repo.marcadores_rango(ts(HOY, 0), ts(HOY, 23)), [(a, "Café"), (b, "Estrés")])
        self.assertTrue(self.repo.quitar_marcador(a))
        self.assertFalse(self.repo.quitar_marcador(a))
        self.assertEqual(self.repo.marcadores_rango(0, 2 ** 31), [(b, "Estrés")])

    def test_mismo_instante_reemplaza_la_etiqueta_y_vacia_se_rechaza(self):
        self.repo.guardar_marcador(100, "Café")
        self.repo.guardar_marcador(100, "Mareo")
        self.assertEqual(self.repo.marcadores_rango(0, 200), [(100, "Mareo")])
        with self.assertRaises(ValueError):
            self.repo.guardar_marcador(101, "  ")

    def test_aislados_por_usuario(self):
        d = tempfile.mkdtemp()
        r1 = RepositorioHistorial(os.path.join(d, "h.db"), usuario_id=1)
        r2 = RepositorioHistorial(os.path.join(d, "h.db"), usuario_id=2)
        r1.guardar_marcador(100, "Café")
        self.assertEqual(r2.marcadores_rango(0, 200), [])
        r1.cerrar(); r2.cerrar()

    def test_retrocompatible_con_una_base_anterior(self):
        ruta = os.path.join(tempfile.mkdtemp(), "vieja.db")
        RepositorioHistorial(ruta, usuario_id=1).cerrar()
        con = sqlite3.connect(ruta)
        con.execute("DROP TABLE marcadores_contexto")                        # como una base de antes de esta versión
        con.commit(); con.close()
        r = RepositorioHistorial(ruta, usuario_id=1)
        r.guardar_marcador(5, "Café")
        self.assertEqual(r.marcadores_rango(0, 10), [(5, "Café")])
        r.cerrar()

    def test_borrar_todo_y_purga_los_eliminan(self):
        self.assertIn("marcadores_contexto", TABLAS_DE_USUARIO)
        ahora = int(time.time())
        self.repo.guardar_marcador(ahora - 400 * 86400, "Café")
        self.repo.guardar_marcador(ahora - 86400, "Mareo")
        self.repo.purgar(ahora, 90, 365)
        self.assertEqual([e for _, e in self.repo.marcadores_rango(0, ahora + 10)], ["Mareo"])
        self.repo.borrar_todo()
        self.assertEqual(self.repo.marcadores_rango(0, ahora + 10), [])

    def test_eliminar_cuenta_limpia_los_marcadores(self):
        ruta = os.path.join(tempfile.mkdtemp(), "c.db")
        cuentas = RepositorioCuentas(ruta)
        uid = cuentas.crear("ana@correo.com", "Ana", "x" * 32, "y" * 32) if hasattr(cuentas, "crear") else None
        if uid is None:
            self.skipTest("API de cuentas distinta")
        h = RepositorioHistorial(ruta, usuario_id=uid)
        h.guardar_marcador(100, "Café")
        cuentas.eliminar(uid)
        con = sqlite3.connect(ruta)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM marcadores_contexto").fetchone()[0], 0)
        con.close(); h.cerrar()


class TestCruceDominio(unittest.TestCase):

    def dias(self, n=8):
        return [HOY - timedelta(days=k) for k in range(n)]

    def test_subida_de_fc_reposo(self):
        d = self.dias()
        m = {x: ctx.MetricasDia(fc_reposo=60.0) for x in d}
        for x in d[:2]:
            m[x] = ctx.MetricasDia(fc_reposo=67.2)                    # +12 %
        self.assertEqual(
            ctx.lineas_cruce("Mal descanso", d[:2], m),
            ["Los días marcados con 'Mal descanso' tu FC en reposo subió un 12 % respecto a tu media habitual "
             "(2 días marcados frente a 6 sin marcar)."])

    def test_caida_de_hrv(self):
        d = self.dias()
        m = {x: ctx.MetricasDia(rmssd=50.0) for x in d}
        for x in d[:3]:
            m[x] = ctx.MetricasDia(rmssd=40.0)
        (linea,) = ctx.lineas_cruce("Estrés", d[:3], m)
        self.assertIn("HRV (RMSSD) bajó un 20 %", linea)

    def test_variacion_pequena_o_muestra_insuficiente_no_genera_nada(self):
        d = self.dias()
        m = {x: ctx.MetricasDia(fc_reposo=60.0) for x in d}
        m[d[0]] = m[d[1]] = ctx.MetricasDia(fc_reposo=61.0)           # +1,7 % < 5 %
        self.assertEqual(ctx.lineas_cruce("Café", d[:2], m), [])
        m[d[0]] = ctx.MetricasDia(fc_reposo=80.0)
        self.assertEqual(ctx.lineas_cruce("Café", d[:1], m), [])      # un solo día marcado
        self.assertEqual(ctx.lineas_cruce("Café", d[:2], {x: m[x] for x in d[:3]}), [])   # poca referencia

    def test_sin_metricas_no_falla(self):
        self.assertEqual(ctx.lineas_cruce("Café", [HOY], {}), [])


class TestObservacionCruzada(unittest.TestCase):

    def setUp(self):
        self.repo = RepositorioHistorial(":memory:", usuario_id=1)
        self.dias = [HOY - timedelta(days=k) for k in range(8, 0, -1)]
        self.malos = self.dias[-2:]
        for d in self.dias:
            sembrar_dia(self.repo, d, 70 if d in self.malos else 60, rmssd=30 if d in self.malos else 50)
        self.svc = servicio(self.repo)

    def contexto(self):
        return self.repo.observaciones_rango(0, 2 ** 31, "CONTEXTO")

    def test_etiqueta_con_subida_de_fc_y_caida_de_hrv(self):
        for d in self.malos:
            self.repo.guardar_marcador(ts(d, 8), "Mal descanso")
        self.svc.actualizar_todo()
        (o,) = self.contexto()
        self.assertEqual(o.clave, "Mal descanso")
        self.assertIn("tu FC en reposo subió un 17 % respecto a tu media habitual", o.texto)
        self.assertIn("tu HRV (RMSSD) bajó un 40 %", o.texto)

    def test_sin_muestra_suficiente_no_hay_observacion(self):
        self.repo.guardar_marcador(ts(self.malos[0], 8), "Mal descanso")      # un solo día
        self.svc.actualizar_todo()
        self.assertEqual(self.contexto(), [])

    def test_quitar_el_marcador_retira_la_observacion(self):
        for d in self.malos:
            self.repo.guardar_marcador(ts(d, 8), "Mal descanso")
        self.svc.actualizar_todo()
        self.assertEqual(len(self.contexto()), 1)
        self.repo.quitar_marcador(ts(self.malos[0], 8))
        self.svc.actualizar_todo()
        self.assertEqual(self.contexto(), [])

    def test_dos_marcadores_el_mismo_dia_cuentan_un_dia(self):
        self.repo.guardar_marcador(ts(self.malos[0], 8), "Café")
        self.repo.guardar_marcador(ts(self.malos[0], 9), "Café")
        self.svc.actualizar_todo()
        self.assertEqual(self.contexto(), [])


class TestVista(unittest.TestCase):

    def setUp(self):
        self.repo = RepositorioHistorial(":memory:", usuario_id=1)
        self.dias = [HOY - timedelta(days=k) for k in range(8, 0, -1)]
        self.malos = self.dias[-2:]
        for d in self.dias:
            sembrar_dia(self.repo, d, 70 if d in self.malos else 60)
        self.vm = VitaBandViewModel(MagicMock(), repositorio=self.repo)
        self.ventana = MainWindow(self.vm, "Ana")
        self.h = self.ventana.vista_historial
        self.h.selector.establecer_rango(self.dias[0], HOY)
        self.h.actualizar()

    def tearDown(self):
        self.ventana.close()
        self.vm.cerrar()

    def test_poner_marcadores_dibuja_y_refresca_observaciones(self):
        self.assertEqual(self.h.grafica.marcadores, 0)
        for d in self.malos:
            self.h._poner_marcador(ts(d, 8), "Estrés")
        self.assertEqual(self.h.grafica.marcadores, 2)
        self.assertIn("Contexto: «Estrés»", self.h.observaciones.texto())
        self.assertIn("tu FC en reposo subió", self.h.observaciones.texto())

    def test_quitar_marcador_refresca(self):
        for d in self.malos:
            self.h._poner_marcador(ts(d, 8), "Estrés")
        self.h._quitar_marcador(ts(self.malos[0], 8))
        self.assertEqual(self.h.grafica.marcadores, 1)
        self.assertNotIn("Contexto: «Estrés»", self.h.observaciones.texto())

    def test_marcador_cercano_distingue_clic_sobre_marcador(self):
        t = ts(self.malos[0], 8)
        self.h._poner_marcador(t, "Café")
        self.assertEqual(self.h.grafica.marcador_cercano(t + 1), t)
        self.assertIsNone(self.h.grafica.marcador_cercano(t + 3 * 86400))

    def test_el_menu_ofrece_las_cuatro_etiquetas_o_quitar(self):
        capturados = []
        from unittest.mock import patch
        with patch("ui.vista_historial.QMenu") as Menu:
            Menu.return_value.addAction.side_effect = lambda txt, *_: capturados.append(txt)
            self.h._on_clic_grafica(float(ts(self.malos[0], 8)), QPointF(0, 0))
            self.assertEqual(capturados, list(ctx.ETIQUETAS_RAPIDAS))
            self.h._poner_marcador(ts(self.malos[0], 8), "Café")
            capturados.clear()
            self.h._on_clic_grafica(float(ts(self.malos[0], 8)), QPointF(0, 0))
            self.assertEqual(capturados, ["Quitar marcador"])

    def test_vm_sin_historial_no_falla(self):
        vm = VitaBandViewModel(MagicMock())
        self.assertEqual(vm.marcadores(0, 10), [])
        vm.cerrar()


if __name__ == "__main__":
    unittest.main()
