"""Tests de los opcionales: zoom del ECG (RF-35), borrado de mediciones (RF-38) y de cuenta (RF-39)."""

import os
import sqlite3
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from domain import ecg_historico as ecg
from domain import hrv
from services import totp
from services.repositorio_cuentas import RepositorioCuentas
from services.planificacion_entrenamiento import GestorCalendarioPlanificado
from services.repositorio_historial import RepositorioHistorial, TABLAS_DE_USUARIO
from services.servicio_auth import (
    CredencialesInvalidas, CuentaBloqueada, ServicioAuth, SesionNoIniciada,
)
from ui.dialogo_eliminar_cuenta import DialogoEliminarCuenta, PALABRA_CLAVE
from ui.grafica_ecg import GraficaEcg, MIN_SELECCION_S
from ui.main_window import MainWindow
from ui.panel_ecg_zoom import (
    PanelEcgZoom, acercar, alejar, desplazar, ventana_inicial,
)
from ui.sesion_activa import SesionActiva
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])

AYER = date.today() - timedelta(days=1)
PASSWORD = "Clave-Segura-123"
EMAIL = "ana@correo.com"


def ts(h, m=0, s=0, dia=AYER):
    return int(datetime(dia.year, dia.month, dia.day, h, m, s).timestamp())


def dt(t):
    return datetime.fromtimestamp(t)


def reducido(desde, hasta, n=50):
    segundos = [ecg.SegundoEcg(t, 1000, 2000) for t in range(desde, hasta)]
    return ecg.reducir(segundos, desde, hasta, n)


# ======================================================================
# RF-35: zoom
# ======================================================================

class TestAritmeticaZoom(unittest.TestCase):

    def test_ventana_inicial_centrada_y_dentro_del_rango(self):
        a, b = ventana_inicial(0, 1000)
        self.assertEqual((a, b), (400, 600))
        a, b = ventana_inicial(0, 100)                      # mínimo 60 s
        self.assertEqual(b - a, 60)
        self.assertEqual(ventana_inicial(10, 40), (10, 40))  # rango menor que el mínimo: todo

    def test_acercar_reduce_a_la_mitad_con_minimo(self):
        self.assertEqual(acercar(400, 600, 0, 1000), (450, 550))
        a, b = acercar(500, 508, 0, 1000)
        self.assertEqual(b - a, MIN_SELECCION_S)

    def test_alejar_duplica_y_no_se_sale(self):
        self.assertEqual(alejar(450, 550, 0, 1000), (400, 600))
        self.assertEqual(alejar(0, 600, 0, 1000), (0, 1000))

    def test_desplazar_respeta_los_limites(self):
        self.assertEqual(desplazar(400, 600, 0, 1000, 1), (500, 700))
        self.assertEqual(desplazar(400, 600, 0, 1000, -1), (300, 500))
        self.assertEqual(desplazar(0, 200, 0, 1000, -1), (0, 200))
        self.assertEqual(desplazar(800, 1000, 0, 1000, 1), (800, 1000))


class TestGraficaEcgSeleccion(unittest.TestCase):

    def test_sin_seleccion_por_defecto(self):
        self.assertIsNone(GraficaEcg().seleccion())

    def test_fijar_no_emite_y_soltar_si(self):
        g = GraficaEcg(con_seleccion=True)
        g.mostrar(reducido(1000, 2000), 1000, 2000)
        emitidos = []
        g.region_cambiada.connect(lambda a, b: emitidos.append((a, b)))
        g.fijar_seleccion(1200, 1400)
        self.assertEqual(emitidos, [])
        self.assertEqual(g.seleccion(), (1200, 1400))
        g._on_region_soltada()
        self.assertEqual(emitidos, [(1200, 1400)])

    def test_seleccion_minima(self):
        g = GraficaEcg(con_seleccion=True)
        g.mostrar(reducido(1000, 2000), 1000, 2000)
        emitidos = []
        g.region_cambiada.connect(lambda a, b: emitidos.append((a, b)))
        g.fijar_seleccion(1500, 1501)
        g._on_region_soltada()
        a, b = emitidos[0]
        self.assertEqual(b - a, MIN_SELECCION_S)

    def test_sin_datos_oculta_la_region(self):
        g = GraficaEcg(con_seleccion=True)
        g.mostrar(reducido(1000, 2000), 1000, 2000)
        g.mostrar(None, 1000, 2000)
        self.assertFalse(g.region.isVisible())
        self.assertIn("sin datos", g.getPlotItem().titleLabel.text)


class TestPanelEcgZoom(unittest.TestCase):

    def setUp(self):
        self.llamadas = []

        def proveedor(a, b, n):
            self.llamadas.append((a, b, n))
            return reducido(a, b, n)

        self.panel = PanelEcgZoom(proveedor)

    def botones(self):
        p = self.panel
        return (p.btn_acercar, p.btn_alejar, p.btn_izquierda, p.btn_derecha, p.btn_restablecer)

    def test_sin_datos_botones_deshabilitados(self):
        self.assertTrue(all(not b.isEnabled() for b in self.botones()))
        self.panel.mostrar(None, 0, 100)
        self.assertTrue(all(not b.isEnabled() for b in self.botones()))
        self.assertIn("no hay señal", self.panel.vista_detalle.getPlotItem().titleLabel.text)

    def test_con_datos_ventana_inicial_y_detalle(self):
        self.panel.mostrar(reducido(1000, 2000), 1000, 2000)
        self.assertEqual(self.panel.seleccion(), (1400, 1600))
        self.assertTrue(all(b.isEnabled() for b in self.botones()))
        self.assertEqual(self.llamadas[-1][:2], (1400, 1600))
        self.assertGreater(self.panel.vista_detalle.intervalos_dibujados, 0)
        self.assertIn("200 s", self.panel.lbl_detalle.text())

    def test_botones_mueven_el_intervalo(self):
        self.panel.mostrar(reducido(1000, 2000), 1000, 2000)
        self.panel.btn_acercar.click()
        self.assertEqual(self.panel.seleccion(), (1450, 1550))
        self.panel.btn_derecha.click()
        self.assertEqual(self.panel.seleccion(), (1500, 1600))
        self.panel.btn_izquierda.click()
        self.assertEqual(self.panel.seleccion(), (1450, 1550))
        self.panel.btn_alejar.click()
        self.assertEqual(self.panel.seleccion(), (1400, 1600))
        self.panel.btn_restablecer.click()
        self.assertEqual(self.panel.seleccion(), (1400, 1600))
        self.assertEqual(self.llamadas[-1][:2], (1400, 1600))

    def test_arrastrar_la_region_recarga_el_detalle(self):
        self.panel.mostrar(reducido(1000, 2000), 1000, 2000)
        self.panel.vista_general.fijar_seleccion(1100, 1300)
        self.panel.vista_general._on_region_soltada()
        self.assertEqual(self.llamadas[-1][:2], (1100, 1300))

    def test_actualizar_conserva_la_seleccion(self):
        self.panel.mostrar(reducido(1000, 2000), 1000, 2000)
        self.panel.vista_general.fijar_seleccion(1100, 1300)
        self.panel.mostrar(reducido(1000, 2000), 1000, 2000)
        self.assertEqual(self.panel.seleccion(), (1100, 1300))

    def test_cambio_de_rango_no_deja_seleccion_degenerada(self):
        self.panel.mostrar(reducido(1000, 2000), 1000, 2000)
        self.panel.mostrar(reducido(5000, 5600), 5000, 5600)     # rango distinto: nueva ventana
        a, b = self.panel.seleccion()
        self.assertTrue(5000 <= a < b <= 5600)

    def test_rango_diminuto_no_rompe(self):
        self.panel.mostrar(reducido(1000, 1001), 1000, 1001)
        self.panel.mostrar(reducido(1000, 1001), 1000, 1001)
        self.assertTrue(self.panel.btn_acercar.isEnabled())

    def test_la_vista_general_tiene_region_y_el_detalle_no(self):
        self.assertIsNotNone(self.panel.vista_general.region)
        self.assertIsNone(self.panel.vista_detalle.region)


# ======================================================================
# RF-38: repositorio y ViewModel
# ======================================================================

class BaseRepo(unittest.TestCase):
    def setUp(self):
        self.repo = RepositorioHistorial(":memory:", usuario_id=1)

    def tearDown(self):
        self.repo.cerrar()

    def med(self, hora, minuto=0, etiqueta="PERIODICO", uid=None, actividad_id=None, dia=AYER):
        return self.repo.guardar_medicion(70, dt(ts(hora, minuto, dia=dia)), uid=uid or f"u{hora}{minuto}{dia}",
                                          etiqueta=etiqueta, actividad_id=actividad_id)


class TestBorradoRepositorio(BaseRepo):

    def test_quitar_del_periodico_borra_periodicas_y_degrada_ambos(self):
        a = self.repo.guardar_actividad("a1", ts(9), ts(10), "carrera")
        p = self.med(8)
        mixta = self.med(9, 5, "AMBOS", actividad_id=a)
        solo_act = self.med(9, 6, "ACTIVIDAD", actividad_id=a)
        n = self.repo.quitar_del_periodico([p, mixta, solo_act])
        self.assertEqual(n, 2)                                   # la ACTIVIDAD no cuenta ni se toca
        etiquetas = {m.id: m.etiqueta for m in self.repo.todas_las_mediciones()}
        self.assertNotIn(p, etiquetas)
        self.assertEqual(etiquetas[mixta], "ACTIVIDAD")
        self.assertEqual(etiquetas[solo_act], "ACTIVIDAD")
        self.assertEqual(len(self.repo.mediciones_de_actividad(a)), 2)

    def test_ids_ajenos_o_inexistentes_se_ignoran(self):
        self.med(8)
        self.assertEqual(self.repo.quitar_del_periodico([9999]), 0)
        self.assertEqual(self.repo.borrar_mediciones([9999]), 0)
        self.assertEqual(self.repo.contar_mediciones(), 1)

    def test_no_toca_las_de_otro_usuario(self):
        otro = RepositorioHistorial(":memory:", usuario_id=2)
        # misma conexión no se comparte: se comprueba con el filtro de usuario sobre un id ajeno
        self.repo.guardar_medicion(70, dt(ts(8)), uid="x")
        ajeno = otro.guardar_medicion(70, dt(ts(8)), uid="x")
        self.assertEqual(otro.quitar_del_periodico([ajeno]), 1)
        self.assertEqual(self.repo.contar_mediciones(), 1)
        otro.cerrar()

    def test_lotes_grandes(self):
        ids = [self.med(h, m, uid=f"g-{h}-{m}") for h in range(24) for m in range(0, 60, 2)]
        ids += [self.repo.guardar_medicion(70, dt(ts(h, m, 30)), uid=f"h-{h}-{m}") for h in range(24)
                for m in range(0, 60, 2)]
        self.assertGreater(len(ids), 1000)                       # más de dos lotes de 500
        self.assertEqual(self.repo.quitar_del_periodico(ids), len(ids))
        self.assertEqual(self.repo.contar_mediciones(), 0)

    def test_borrar_mediciones_es_borrado_total(self):
        a = self.repo.guardar_actividad("a1", ts(9), ts(10), "carrera")
        m = self.med(9, 5, "AMBOS", actividad_id=a)
        self.assertEqual(self.repo.borrar_mediciones([m]), 1)
        self.assertEqual(self.repo.contar_mediciones(), 0)

    def test_se_limpian_las_observaciones_diarias_huerfanas(self):
        otro_dia = AYER - timedelta(days=1)
        m1 = self.med(8)
        self.med(8, 0, dia=otro_dia)
        for dia in (AYER, otro_dia):
            self.repo.guardar_observacion("DIARIA", dia.isoformat(), "texto", ts(0, dia=dia),
                                          ts(0, dia=dia) + 86400, int(time.time()))
        self.repo.quitar_del_periodico([m1])
        claves = [o.clave for o in self.repo.observaciones_rango(0, 2**31 - 1, "DIARIA")]
        self.assertEqual(claves, [otro_dia.isoformat()])          # la del día vaciado desaparece

    def test_observacion_diaria_se_conserva_si_quedan_mediciones(self):
        m1 = self.med(8)
        self.med(9)
        self.repo.guardar_observacion("DIARIA", AYER.isoformat(), "texto", ts(0), ts(0) + 86400, int(time.time()))
        self.repo.quitar_del_periodico([m1])
        self.assertEqual(len(self.repo.observaciones_rango(0, 2**31 - 1, "DIARIA")), 1)


class TestBorradoViewModel(BaseRepo):

    def setUp(self):
        super().setUp()
        self.vm = VitaBandViewModel(MagicMock(), repositorio=self.repo)
        self.avisos = []
        self.vm.historial_actualizado.connect(lambda: self.avisos.append(1))

    def tearDown(self):
        self.vm.cerrar()
        self.repo = RepositorioHistorial(":memory:", usuario_id=1)      # el vm ya cerró el suyo
        super().tearDown()

    def test_borrar_mediciones_periodicas_emite_y_borra(self):
        ids = [self.med(8, m, uid=f"k{m}") for m in range(0, 30, 10)]
        self.assertEqual(self.vm.borrar_mediciones_periodicas(ids[:2]), 2)
        self.assertEqual(len(self.avisos), 1)
        self.assertEqual(self.vm._repositorio.contar_mediciones(), 1)

    def test_borrar_periodo_solo_dentro_del_rango(self):
        for h in (8, 9, 10):
            self.med(h)
        n = self.vm.borrar_periodo(ts(9), ts(10))
        self.assertEqual(n, 1)
        horas = [dt(m.ts).hour for m in self.vm._repositorio.todas_las_mediciones()]
        self.assertEqual(horas, [8, 10])

    def test_borrar_actividad(self):
        a = self.repo.guardar_actividad("a1", ts(9), ts(10), "carrera")
        self.med(9, 1, "ACTIVIDAD", uid="aa", actividad_id=a)
        self.med(9, 2, "AMBOS", uid="bb", actividad_id=a)
        self.assertTrue(self.vm.borrar_actividad(a))
        quedan = self.vm._repositorio.todas_las_mediciones()
        self.assertEqual([m.etiqueta for m in quedan], ["PERIODICO"])
        self.assertFalse(self.vm.borrar_actividad(a))

    def test_sin_repositorio_falla_claro(self):
        vm = VitaBandViewModel(MagicMock())
        with self.assertRaises(RuntimeError):
            vm.borrar_periodo(0, 10)
        with self.assertRaises(RuntimeError):
            vm.borrar_actividad(1)

    def test_cerrar_sin_volcar_descarta_el_ecg_y_suelta_el_repositorio(self):
        self.vm._ecg_pendiente.append(ecg.SegundoEcg(ts(8), 1, 2))
        self.vm.cerrar(volcar_ecg=False)
        self.assertIsNone(self.vm._repositorio)
        self.assertEqual(len(self.vm._ecg_pendiente), 0)


# ======================================================================
# RF-39: cuenta
# ======================================================================

class BaseCuentas(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.ruta = os.path.join(self.dir.name, "t.db")
        self.cuentas = RepositorioCuentas(self.ruta)

    def tearDown(self):
        self.cuentas.cerrar()
        self.dir.cleanup()

    def crear(self, email=EMAIL):
        return self.cuentas.crear(email, "Ana", PASSWORD, totp.generar_secreto(), 1_700_000_000.0)

    def sembrar(self, usuario_id):
        h = RepositorioHistorial(self.ruta, usuario_id=usuario_id)
        a = h.guardar_actividad(f"a{usuario_id}", ts(9), ts(10), "carrera")
        h.guardar_medicion(70, dt(ts(8)), uid=f"m{usuario_id}")
        h.guardar_medicion(120, dt(ts(9, 5)), uid=f"n{usuario_id}", etiqueta="ACTIVIDAD", actividad_id=a)
        h.guardar_ecg_segundos([ecg.SegundoEcg(ts(9, 0, i), 1, 2) for i in range(5)])
        h.guardar_observacion("DIARIA", AYER.isoformat(), "t", ts(0), ts(0) + 86400, int(time.time()))
        h.guardar_hrv(hrv.ResultadoHrv(ts(8), 42.0, 70.0, 60))
        h.guardar_marcador(ts(8), "Café")
        h.guardar_vuelta(ts(8), 1)
        h.guardar_test_ortostatico(ts(8), 60.0, 40.0, 85.0, 70.0, 35.0, 25.0, "Normal")
        h.guardar_nota_sesion(1, 6, "ok")
        h.guardar_perfil(30, "Mujer", 60.0, 150)
        h.guardar_rr(1_700_000_000, [800.0, 810.0, 790.0])
        h.guardar_disciplina(1, "Carrera")
        GestorCalendarioPlanificado(h).agendar(AYER, "Rodaje", 45)
        return h

    def filas(self, tabla, usuario_id):
        con = sqlite3.connect(self.ruta)
        try:
            return con.execute(f"SELECT COUNT(*) FROM {tabla} WHERE usuario_id = ?", (usuario_id,)).fetchone()[0]
        finally:
            con.close()


class TestEliminarCuentaRepositorio(BaseCuentas):

    def test_borra_la_cuenta_y_todos_sus_datos_sin_tocar_a_otro_usuario(self):
        u1, u2 = self.crear(), self.crear("otro@correo.com")
        h1, h2 = self.sembrar(u1), self.sembrar(u2)
        for t in TABLAS_DE_USUARIO:
            self.assertGreater(self.filas(t, u1) if t != "sync_archivos" else 1, 0)

        self.assertTrue(self.cuentas.eliminar(u1))

        self.assertIsNone(self.cuentas.obtener_por_id(u1))
        self.assertIsNotNone(self.cuentas.obtener_por_id(u2))
        for t in TABLAS_DE_USUARIO:
            self.assertEqual(self.filas(t, u1), 0, t)
        self.assertGreater(self.filas("mediciones", u2), 0)
        self.assertGreater(self.filas("ecg_bloques", u2), 0)
        h1.cerrar()
        h2.cerrar()

    def test_funciona_con_la_conexion_del_historial_abierta(self):
        u = self.crear()
        h = self.sembrar(u)
        self.assertTrue(self.cuentas.eliminar(u))
        self.assertEqual(h.contar_mediciones(), 0)
        h.cerrar()

    def test_cuenta_inexistente_devuelve_false(self):
        self.assertFalse(self.cuentas.eliminar(12345))

    def test_sin_tablas_de_datos_solo_borra_la_cuenta(self):
        u = self.crear()                                         # nunca se creó un historial
        self.assertTrue(self.cuentas.eliminar(u))
        self.assertIsNone(self.cuentas.obtener_por_id(u))

    def test_se_puede_volver_a_registrar_el_mismo_correo(self):
        u = self.crear()
        self.cuentas.eliminar(u)
        self.assertNotEqual(self.crear(), u)


class TestEliminarCuentaServicio(unittest.TestCase):

    def setUp(self):
        self.t = [1_700_000_000.0]
        self.repo = RepositorioCuentas(":memory:")
        self.auth = ServicioAuth(self.repo, reloj=lambda: self.t[0], max_intentos=3, bloqueo_s=300)
        self.auth.registrar("Ana", EMAIL, PASSWORD, PASSWORD)
        d = self.auth.iniciar_sesion(EMAIL, PASSWORD)
        self.sesion = self.auth.verificar_mfa(totp.codigo_actual(d.secreto, self.t[0]))

    def tearDown(self):
        self.repo.cerrar()

    def test_contrasena_correcta_elimina_y_cierra_sesion(self):
        self.auth.eliminar_cuenta(PASSWORD)
        self.assertIsNone(self.repo.obtener_por_id(self.sesion.usuario_id))
        with self.assertRaises(SesionNoIniciada):
            self.auth.requerir_sesion()

    def test_contrasena_incorrecta_no_elimina_y_cuenta_para_el_bloqueo(self):
        for _ in range(2):
            with self.assertRaises(CredencialesInvalidas):
                self.auth.eliminar_cuenta("mala")
        self.assertIsNotNone(self.repo.obtener_por_id(self.sesion.usuario_id))
        self.auth.requerir_sesion()                              # la sesión sigue abierta
        with self.assertRaises(CredencialesInvalidas):
            self.auth.eliminar_cuenta("mala")                    # tercer fallo: bloquea
        with self.assertRaises(CuentaBloqueada):
            self.auth.eliminar_cuenta(PASSWORD)                  # ni la buena vale bloqueada
        self.assertIsNotNone(self.repo.obtener_por_id(self.sesion.usuario_id))

    def test_requiere_sesion(self):
        self.auth.cerrar_sesion()
        with self.assertRaises(SesionNoIniciada):
            self.auth.eliminar_cuenta(PASSWORD)


# ======================================================================
# Interfaz
# ======================================================================

class TestDialogoEliminarCuenta(unittest.TestCase):

    def test_boton_habilitado_solo_con_palabra_y_contrasena(self):
        d = DialogoEliminarCuenta("Ana")
        self.assertFalse(d.btn_eliminar.isEnabled())
        d.campo_palabra.setText(PALABRA_CLAVE)
        self.assertFalse(d.btn_eliminar.isEnabled())
        d.campo_password.setText("x")
        self.assertTrue(d.btn_eliminar.isEnabled())
        d.campo_palabra.setText("eliminar")                      # distingue la palabra exacta
        self.assertFalse(d.btn_eliminar.isEnabled())
        d.campo_palabra.setText(PALABRA_CLAVE)
        self.assertEqual(d.password(), "x")

    def test_cancelar_es_el_valor_por_defecto(self):
        d = DialogoEliminarCuenta("Ana")
        self.assertTrue(d.btn_cancelar.isDefault())


class BaseUi(unittest.TestCase):
    def setUp(self):
        self.repo = RepositorioHistorial(":memory:", usuario_id=1)
        self.vm = VitaBandViewModel(MagicMock(), repositorio=self.repo)
        self.ventana = MainWindow(self.vm, "Ana")
        self.hist = self.ventana.vista_historial
        self.act = self.ventana.vista_actividades
        self.hist.selector.establecer_rango(AYER, AYER)

    def tearDown(self):
        self.ventana.close()
        self.vm.cerrar()
        self.ventana.deleteLater()


class TestBorradoEnVistas(BaseUi):

    def sembrar(self):
        for m in (0, 10, 20, 30):
            self.repo.guardar_medicion(70, dt(ts(8, m)), uid=f"p{m}")
        self.hist.actualizar()

    def test_boton_deshabilitado_sin_seleccion(self):
        self.sembrar()
        self.assertEqual(self.hist.tabla.rowCount(), 4)
        self.assertFalse(self.hist.btn_eliminar_seleccion.isEnabled())

    def test_los_ids_viajan_en_la_tabla(self):
        self.sembrar()
        ids = [self.hist.tabla.item(i, 0).data(Qt.ItemDataRole.UserRole) for i in range(4)]
        self.assertEqual(sorted(ids), sorted(m.id for m in self.repo.todas_las_mediciones()))

    def test_eliminar_seleccion_confirma_y_borra(self):
        self.sembrar()
        self.hist.tabla.selectRow(1)
        self.assertTrue(self.hist.btn_eliminar_seleccion.isEnabled())
        with patch("ui.vista_historial.confirmar", return_value=True) as c:
            self.hist.btn_eliminar_seleccion.click()
        self.assertIn("no se puede deshacer", c.call_args.args[2])
        self.assertEqual(self.repo.contar_mediciones(), 3)
        self.assertEqual(self.hist.tabla.rowCount(), 3)

    def test_cancelar_la_confirmacion_no_borra(self):
        self.sembrar()
        self.hist.tabla.selectRow(0)
        with patch("ui.vista_historial.confirmar", return_value=False):
            self.hist.btn_eliminar_seleccion.click()
        self.assertEqual(self.repo.contar_mediciones(), 4)

    def test_eliminar_periodo_cuenta_y_borra(self):
        self.sembrar()
        with patch("ui.vista_historial.confirmar", return_value=True) as c:
            self.hist.btn_eliminar_periodo.click()
        self.assertIn("4 registros", c.call_args.args[2])
        self.assertEqual(self.repo.contar_mediciones(), 0)
        self.assertIn("4", self.hist.lbl_info.text())

    def test_eliminar_periodo_cancelado_o_vacio(self):
        self.sembrar()
        with patch("ui.vista_historial.confirmar", return_value=False):
            self.hist.btn_eliminar_periodo.click()
        self.assertEqual(self.repo.contar_mediciones(), 4)
        self.repo.borrar_todo()
        with patch("ui.vista_historial.confirmar") as c:
            self.hist.btn_eliminar_periodo.click()
        c.assert_not_called()                                    # nada que borrar: ni se pregunta

    def test_en_vista_agrupada_no_se_puede_elegir_filas(self):
        self.sembrar()
        self.hist.tabla.selectRow(0)
        self.hist.selector.combo_resolucion.setCurrentIndex(self.hist.selector.combo_resolucion.count() - 1)
        self.assertFalse(self.hist.btn_eliminar_seleccion.isEnabled())

    def test_error_al_borrar_avisa_sin_romper(self):
        self.sembrar()
        self.hist.tabla.selectRow(0)
        with patch("ui.vista_historial.confirmar", return_value=True), \
                patch.object(self.vm, "borrar_mediciones_periodicas", side_effect=RuntimeError("fallo")), \
                patch("ui.vista_historial.QMessageBox.warning") as aviso:
            self.hist.btn_eliminar_seleccion.click()
        aviso.assert_called_once()
        self.assertEqual(self.repo.contar_mediciones(), 4)

    def test_eliminar_actividad(self):
        a = self.repo.guardar_actividad("a1", ts(9), ts(9, 10), "carrera")
        self.repo.guardar_medicion(120, dt(ts(9, 1)), uid="x", etiqueta="ACTIVIDAD", actividad_id=a)
        self.repo.guardar_medicion(80, dt(ts(9, 2)), uid="y", etiqueta="AMBOS", actividad_id=a)
        self.act.selector.establecer_rango(AYER, AYER)
        self.act.actualizar()
        self.act.tabla.selectRow(0)
        self.assertTrue(self.act.btn_eliminar.isEnabled())
        with patch("ui.vista_actividades.confirmar", return_value=False):
            self.act.btn_eliminar.click()
        self.assertEqual(len(self.repo.mediciones_de_actividad(a)), 2)
        with patch("ui.vista_actividades.confirmar", return_value=True) as c:
            self.act.btn_eliminar.click()
        self.assertIn("no se puede deshacer", c.call_args.args[2])
        self.assertEqual([m.etiqueta for m in self.repo.todas_las_mediciones()], ["PERIODICO"])
        self.assertEqual(self.act.tabla.rowCount(), 0)
        self.assertFalse(self.act.btn_eliminar.isEnabled())

    def test_el_panel_ecg_es_la_vista_general(self):
        self.assertIs(self.hist.grafica_ecg, self.hist.panel_ecg.vista_general)
        self.assertIs(self.act.grafica_ecg, self.act.panel_ecg.vista_general)

    def test_ecg_con_datos_activa_el_zoom_en_el_historial(self):
        self.repo.guardar_medicion(70, dt(ts(8)), uid="z")
        self.repo.guardar_ecg_segundos([ecg.SegundoEcg(ts(8) + i, 1000 + i, 2000 + i) for i in range(300)])
        self.hist.actualizar()
        self.assertTrue(self.hist.panel_ecg.btn_acercar.isEnabled())
        self.assertIsNotNone(self.hist.panel_ecg.seleccion())


class TestEliminarCuentaVentana(BaseUi):

    def test_doble_confirmacion_emite_la_senal(self):
        recibido = []
        self.ventana.eliminar_cuenta_solicitada.connect(recibido.append)
        dlg = MagicMock()
        dlg.exec.return_value = DialogoEliminarCuenta.DialogCode.Accepted
        dlg.password.return_value = "secreta"
        with patch("ui.main_window.confirmar", return_value=True) as c, \
                patch("ui.main_window.DialogoEliminarCuenta", return_value=dlg) as cls:
            cls.DialogCode = DialogoEliminarCuenta.DialogCode
            self.ventana.btn_eliminar_cuenta.click()
        c.assert_called_once()
        self.assertEqual(recibido, ["secreta"])

    def test_cancelar_el_primer_aviso_no_abre_el_dialogo(self):
        recibido = []
        self.ventana.eliminar_cuenta_solicitada.connect(recibido.append)
        with patch("ui.main_window.confirmar", return_value=False), \
                patch("ui.main_window.DialogoEliminarCuenta") as cls:
            self.ventana.btn_eliminar_cuenta.click()
        cls.assert_not_called()
        self.assertEqual(recibido, [])

    def test_cancelar_el_segundo_dialogo_no_emite(self):
        recibido = []
        self.ventana.eliminar_cuenta_solicitada.connect(recibido.append)
        dlg = MagicMock()
        dlg.exec.return_value = DialogoEliminarCuenta.DialogCode.Rejected
        with patch("ui.main_window.confirmar", return_value=True), \
                patch("ui.main_window.DialogoEliminarCuenta", return_value=dlg) as cls:
            cls.DialogCode = DialogoEliminarCuenta.DialogCode
            self.ventana.btn_eliminar_cuenta.click()
        self.assertEqual(recibido, [])


class TestEliminarCuentaSesionActiva(unittest.TestCase):

    CONFIG = {
        "mqtt": {"broker_host": "localhost", "broker_port": 1883, "device_id": "vitaband-01"},
        "monitorizacion": {"ventana_segundos": 6},
    }

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.ruta = os.path.join(self.dir.name, "t.db")
        self.config = dict(self.CONFIG, intercambio={"carpeta": os.path.join(self.dir.name, "i"),
                                                     "intervalo_comprobacion_s": 0},
                           observaciones={"intervalo_min": 0})
        self.cuentas = RepositorioCuentas(self.ruta)
        self.auth = ServicioAuth(self.cuentas)
        self.auth.registrar("Ana", EMAIL, PASSWORD, PASSWORD)
        d = self.auth.iniciar_sesion(EMAIL, PASSWORD)
        self.sesion = self.auth.verificar_mfa(totp.codigo_actual(d.secreto))
        self.parche = patch("ui.sesion_activa.MqttVitaBandService")
        self.parche.start()
        self.activa = None

    def tearDown(self):
        if self.activa:
            self.activa.liberar()
        self.parche.stop()
        self.cuentas.cerrar()
        self.dir.cleanup()

    def crear(self, con_auth=True):
        self.activa = SesionActiva(_app, self.config, self.sesion, self.ruta,
                                   auth=self.auth if con_auth else None)
        return self.activa

    def filas(self, tabla):
        con = sqlite3.connect(self.ruta)
        try:
            return con.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
        finally:
            con.close()

    def test_eliminacion_completa_de_extremo_a_extremo(self):
        a = self.crear()
        a.repositorio.guardar_medicion(70, dt(ts(8)), uid="m1")
        a.repositorio.guardar_ecg_segundos([ecg.SegundoEcg(ts(8, 0, i), 1, 2) for i in range(5)])
        a.vm._ecg_pendiente.append(ecg.SegundoEcg(ts(8, 1), 5, 6))       # pendiente de volcar
        a.vm._timer_registro.start()

        with patch("ui.sesion_activa.QMessageBox") as caja:
            # Cualquier cuadro de diálogo debe encontrar ya el ViewModel parado y sin repositorio
            caja.information.side_effect = lambda *x: self.assertIsNone(a.vm._repositorio)
            a.ventana.eliminar_cuenta_solicitada.emit(PASSWORD)
            _app.processEvents()
        caja.information.assert_called_once()

        self.assertTrue(a.volver_al_login)
        self.assertFalse(a.vm._timer_registro.isActive())
        self.assertIsNone(a.vm._repositorio)
        a.liberar()                                                       # no vuelve a escribir
        self.assertEqual(self.filas("usuarios"), 0)
        for t in TABLAS_DE_USUARIO:
            self.assertEqual(self.filas(t), 0, t)                         # sin filas huérfanas
        with self.assertRaises(SesionNoIniciada):
            self.auth.requerir_sesion()

    def test_contrasena_incorrecta_avisa_y_no_borra(self):
        a = self.crear()
        a.repositorio.guardar_medicion(70, dt(ts(8)), uid="m1")
        with patch("ui.sesion_activa.QMessageBox") as caja:
            a.ventana.eliminar_cuenta_solicitada.emit("equivocada")
        caja.warning.assert_called_once()
        caja.information.assert_not_called()
        self.assertFalse(a.volver_al_login)
        self.assertEqual(self.filas("usuarios"), 1)
        self.assertEqual(self.filas("mediciones"), 1)
        self.assertIsNotNone(a.vm._repositorio)

    def test_sin_servicio_de_auth_no_hace_nada(self):
        a = self.crear(con_auth=False)
        a.ventana.eliminar_cuenta_solicitada.emit(PASSWORD)
        self.assertFalse(a.volver_al_login)
        self.assertEqual(self.filas("usuarios"), 1)


if __name__ == "__main__":
    unittest.main()
