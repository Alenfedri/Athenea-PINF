import csv
import json
import os
import tempfile
import time
import unittest
from datetime import datetime
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from domain import ecg_historico as ecg
from domain.ui_state import ConexionEstado
from services.repositorio_historial import RepositorioHistorial
from services.servicio_sync import ServicioSync
from viewmodel.vitaband_vm import VitaBandViewModel, texto_sync

_app = QApplication.instance() or QApplication([])


def paquete(vm, n=3, bpm=72.0, ecg=1600.0):
    for _ in range(n):
        vm.on_paquete_telemetria(ecg, bpm, 15.0, 36.5, 0, 255)


def T(dia, h=0, m=0, s=0):
    return int(datetime(2026, 11, dia, h, m, s).timestamp())


AHORA = T(15, 12)
DIA = 86400


def esperar(ms):
    """Deja pasar tiempo real y procesa los temporizadores de Qt."""
    time.sleep(ms / 1000)
    _app.processEvents()


class BaseVm(unittest.TestCase):

    TIMEOUT_MS = 2500  # los tests del watchdog usan uno corto

    def setUp(self):
        self.mqtt = MagicMock()
        self.mqtt.publicar_control_ecg.return_value = True
        self.repo = RepositorioHistorial(":memory:", usuario_id=1)
        self.ahora = AHORA                      # reloj controlable por los tests
        self.vm = self.crear_vm()

    def crear_vm(self, **extra):
        return VitaBandViewModel(
            self.mqtt, ventana_segundos=6, repositorio=self.repo,
            timeout_telemetria_ms=self.TIMEOUT_MS, reloj=lambda: self.ahora, **extra,
        )

    def conectado(self, bpm=72.0, **kw):
        self.vm.conectar()
        paquete(self.vm, bpm=bpm, **kw)
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.CONECTADO)

    def tearDown(self):
        self.vm.cerrar()


class TestViewModel(BaseVm):

    # --- B: reinicio del modo ECG ---

    def test_conectar_y_desconectar_reinician_modo_ecg(self):
        self.vm.conectar()
        self.vm.on_estado_enlace_actualizado(ConexionEstado.CONECTADO)
        self.vm.cambiarModoEcg(True)
        self.assertTrue(self.vm.state.modoEcgCrudo)

        self.vm.desconectar()
        self.assertFalse(self.vm.state.modoEcgCrudo)

        self.vm.conectar()
        self.assertFalse(self.vm.state.modoEcgCrudo)
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.CONECTANDO)

    def test_reconexion_automatica_reinicia_modo_ecg(self):
        self.vm.conectar()
        self.vm.on_estado_enlace_actualizado(ConexionEstado.CONECTADO)
        self.vm.cambiarModoEcg(True)
        self.vm.on_estado_enlace_actualizado(ConexionEstado.ERROR_COMUNICACION)
        self.vm.on_estado_enlace_actualizado(ConexionEstado.CONECTANDO)
        self.assertFalse(self.vm.state.modoEcgCrudo)

    def test_modo_ecg_no_cambia_si_la_publicacion_falla(self):
        self.vm.conectar()
        self.vm.on_estado_enlace_actualizado(ConexionEstado.CONECTADO)
        self.mqtt.publicar_control_ecg.return_value = False
        self.vm.cambiarModoEcg(True)
        self.assertFalse(self.vm.state.modoEcgCrudo)

    # --- C: OFFLINE y telemetría rezagada ---

    def test_offline_limpia_buffer_y_metricas(self):
        self.vm.conectar()
        self.vm.on_estado_enlace_actualizado(ConexionEstado.CONECTADO)
        paquete(self.vm)
        self.assertTrue(self.vm.state.ecgMuestras)
        self.assertEqual(self.vm.state.bpmTexto, "72.0 BPM")

        self.vm.on_estado_enlace_actualizado(ConexionEstado.ERROR_COMUNICACION)
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.ERROR_COMUNICACION)
        self.assertEqual(self.vm.state.ecgMuestras, ())
        self.assertEqual(self.vm.state.bpmTexto, "--")
        self.assertEqual(self.vm.state.tempTexto, "-- °C")

    def test_telemetria_rezagada_no_resucita_tras_desconectar(self):
        self.vm.conectar()
        self.vm.on_estado_enlace_actualizado(ConexionEstado.CONECTADO)
        self.vm.desconectar()
        paquete(self.vm)
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.DESCONECTADO)
        self.assertEqual(self.vm.state.ecgMuestras, ())

    def test_evento_de_enlace_rezagado_tras_desconectar_se_ignora(self):
        self.vm.conectar()
        self.vm.desconectar()
        self.vm.on_estado_enlace_actualizado(ConexionEstado.CONECTADO)
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.DESCONECTADO)

    def test_telemetria_durante_calibracion_no_pisa_el_estado(self):
        self.vm.conectar()
        self.vm.on_estado_enlace_actualizado(ConexionEstado.CALIBRANDO)
        paquete(self.vm)
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.CALIBRANDO)
        self.vm.on_estado_enlace_actualizado(ConexionEstado.CONECTADO)
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.CONECTADO)

    def test_telemetria_sin_status_pasa_de_conectando_a_conectado(self):
        self.vm.conectar()
        paquete(self.vm)
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.CONECTADO)

    def test_telemetria_tras_offline_de_la_pasarela_se_sigue_descartando(self):
        self.vm.conectar()
        paquete(self.vm)
        self.vm.on_estado_enlace_actualizado(ConexionEstado.ERROR_COMUNICACION)
        paquete(self.vm)
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.ERROR_COMUNICACION)

    # --- Consultas de historial a través del ViewModel ---

    def test_consultas_sin_repositorio_devuelven_valores_vacios(self):
        vm = VitaBandViewModel(self.mqtt)
        self.assertIsNone(vm.consultas)
        self.assertIsNone(vm.rango_disponible())
        self.assertIsNone(vm.serie_historica("bpm", 0, 10))
        self.assertEqual(vm.actividades(0, 10), [])
        self.assertIsNone(vm.detalle_actividad(1))
        self.assertIsNone(vm.ecg_historico(0, 10))
        self.assertEqual(vm.observaciones(0, 10), [])
        self.assertEqual(vm.state.syncTexto, "Sin sincronizar")
        self.assertIsNone(vm.sincronizar())
        with self.assertRaises(RuntimeError):
            vm.exportar_csv("x.csv")

    def test_serie_historica(self):
        self.repo.guardar_medicion(60.0, datetime.fromtimestamp(T(13, 9)))
        self.repo.guardar_medicion(80.0, datetime.fromtimestamp(T(13, 9, 10)))
        self.repo.guardar_medicion(100.0, datetime.fromtimestamp(T(14, 8)))
        self.assertEqual(self.vm.rango_disponible(), (T(13, 9), T(14, 8)))

        s = self.vm.serie_historica("bpm", T(13), T(14))
        self.assertEqual([v for _, v in s.pares], [60.0, 80.0])
        self.assertEqual((s.estadisticas.cantidad, s.estadisticas.media, s.estadisticas.minimo,
                          s.estadisticas.maximo), (2, 70.0, 60.0, 80.0))
        self.assertEqual(self.vm.serie_historica("bpm", T(1), T(2)).pares, ())
        with self.assertRaises(ValueError):
            self.vm.serie_historica("bpm", T(14), T(13))       # error de uso: no se silencia

    def test_actividades_ecg_y_observaciones(self):
        a = self.repo.guardar_actividad("a", T(10, 9), T(10, 10), "carrera")
        self.repo.guardar_medicion(130, datetime.fromtimestamp(T(10, 9)), etiqueta="ACTIVIDAD", actividad_id=a)
        self.repo.guardar_ecg_segundos([ecg.SegundoEcg(T(10, 9), 1, 2)])
        self.repo.guardar_observacion("ACTIVIDAD", str(a), "txt", T(10, 9), T(10, 10), AHORA, actividad_id=a)
        self.assertEqual([r.mediciones for r in self.vm.actividades(T(10), T(11))], [1])
        self.assertEqual(self.vm.detalle_actividad(a).observacion.texto, "txt")
        self.assertTrue(self.vm.ecg_historico(T(10, 9), T(10, 9, 30), 5).tiene_datos)
        self.assertEqual(len(self.vm.observaciones(T(10), T(11), "ACTIVIDAD")), 1)

    def test_error_de_bd_en_consulta_no_rompe_la_ui(self):
        import sqlite3
        self.repo.rango_periodico = MagicMock(side_effect=sqlite3.OperationalError("boom"))
        self.assertIsNone(self.vm.rango_disponible())

    # --- Exportación CSV ---

    def leer_csv(self, ruta):
        with open(ruta, encoding="utf-8-sig", newline="") as f:
            return list(csv.reader(f, delimiter=";"))

    def test_exportar_csv(self):
        self.repo.guardar_medicion(60.5, datetime(2026, 11, 13, 9, 0, 0), rpm=15.0, temp_c=36.5, nivel_actividad=0)
        self.repo.guardar_medicion(80.0, datetime(2026, 11, 14, 8, 30, 5))
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "h.csv")
            self.assertEqual(self.vm.exportar_csv(ruta), 2)
            filas = self.leer_csv(ruta)
        self.assertEqual(filas[0], ["fecha", "hora", "bpm", "rpm", "temp_c", "nivel_actividad", "etiqueta"])
        self.assertEqual(filas[1], ["2026-11-13", "09:00:00", "60,5", "15,0", "36,50", "reposo", "PERIODICO"])
        self.assertEqual(filas[2], ["2026-11-14", "08:30:05", "80,0", "", "", "", "PERIODICO"])

    def test_exportar_csv_con_rango_y_ambito(self):
        a = self.repo.guardar_actividad("a", T(13, 9), T(13, 10))
        self.repo.guardar_medicion(60, datetime.fromtimestamp(T(13, 8)), uid="p1")
        self.repo.guardar_medicion(61, datetime.fromtimestamp(T(14, 8)), uid="p2")
        self.repo.guardar_medicion(150, datetime.fromtimestamp(T(13, 9)), uid="a1",
                                   etiqueta="ACTIVIDAD", actividad_id=a)
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "h.csv")
            self.assertEqual(self.vm.exportar_csv(ruta, T(13), T(14)), 2)
            self.assertEqual(self.vm.exportar_csv(ruta, ambito="periodico"), 2)
            self.assertEqual(self.vm.exportar_csv(ruta, desde_ts=T(14)), 1)
            self.assertEqual(self.vm.exportar_csv(ruta, ambito="actividad"), 1)

    # --- Señales en cola (flujo real entre hilos) ---

    def test_senales_en_cola(self):
        self.vm.conectar()
        self.vm.enlace_actualizado.emit(ConexionEstado.CONECTADO)
        for _ in range(3):
            self.vm.telemetria_recibida.emit(1600.0, 70.0, 14.0, 36.4, 1, 255)
        self.vm.media_bpm_recibida.emit(70.0)
        _app.processEvents()
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.CONECTADO)
        self.assertEqual(self.vm.state.nivelActividad, "Media")
        self.assertTrue(self.vm.registrar_medicion())
        self.assertEqual([m.bpm for m in self.repo.todas_las_mediciones()], [70.0])

    def test_parametros_invalidos(self):
        with self.assertRaises(ValueError):
            VitaBandViewModel(self.mqtt, ventana_segundos=0)
        with self.assertRaises(ValueError):
            VitaBandViewModel(self.mqtt, intervalo_registro_ms=0)
        with self.assertRaises(ValueError):
            VitaBandViewModel(self.mqtt, dias_periodico=30, dias_actividades=10)


class TestWatchdogTelemetria(BaseVm):
    """Silencio de telemetría sin que la pasarela alcance a publicar OFFLINE."""

    TIMEOUT_MS = 60

    def conectado_con_datos(self):
        self.vm.conectar()
        paquete(self.vm)
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.CONECTADO)
        self.assertTrue(self.vm.state.ecgMuestras)

    def test_vence_pasa_a_error_y_limpia_datos(self):
        self.conectado_con_datos()
        esperar(150)
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.ERROR_COMUNICACION)
        self.assertEqual(self.vm.state.ecgMuestras, ())
        self.assertEqual(self.vm.state.bpmTexto, "--")
        self.assertEqual(self.vm.state.rpmTexto, "--")
        self.assertEqual(self.vm.state.tempTexto, "-- °C")
        self.assertEqual(self.vm.state.nivelActividad, "Sin datos")

    def test_se_reinicia_con_cada_paquete(self):
        self.conectado_con_datos()
        for _ in range(8):                 # 8 x 30 ms = 240 ms > timeout, pero con vida
            paquete(self.vm, n=1)
            esperar(30)
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.CONECTADO)
        esperar(150)                       # ahora sí: silencio
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.ERROR_COMUNICACION)

    def test_tambien_vigila_la_calibracion(self):
        self.vm.conectar()
        self.vm.on_estado_enlace_actualizado(ConexionEstado.CALIBRANDO)
        paquete(self.vm)
        esperar(150)
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.ERROR_COMUNICACION)

    def test_no_actua_tras_desconectar(self):
        self.conectado_con_datos()
        self.vm.desconectar()
        esperar(150)
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.DESCONECTADO)

    def test_no_actua_si_el_enlace_se_cayo_por_otra_via(self):
        self.conectado_con_datos()
        self.vm.on_estado_enlace_actualizado(ConexionEstado.ERROR_COMUNICACION)
        emitidos = []
        self.vm.state_changed.connect(emitidos.append)
        esperar(150)
        self.assertEqual(emitidos, [])     # el watchdog no vuelve a emitir

    def test_no_arranca_mientras_solo_se_esta_conectando(self):
        self.vm.conectar()
        esperar(150)
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.CONECTANDO)

    def test_se_recupera_si_la_telemetria_vuelve(self):
        self.conectado_con_datos()
        esperar(150)
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.ERROR_COMUNICACION)
        paquete(self.vm)
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.CONECTADO)
        self.assertTrue(self.vm.state.ecgMuestras)

    def test_no_se_recupera_si_la_pasarela_declaro_offline(self):
        self.conectado_con_datos()
        esperar(150)
        self.vm.on_estado_enlace_actualizado(ConexionEstado.ERROR_COMUNICACION)  # OFFLINE explícito
        paquete(self.vm)
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.ERROR_COMUNICACION)

    def test_conectar_manualmente_cancela_la_recuperacion_automatica(self):
        self.conectado_con_datos()
        esperar(150)
        self.vm.desconectar()
        paquete(self.vm)
        self.assertEqual(self.vm.state.conexionEstado, ConexionEstado.DESCONECTADO)

    def test_cerrar_detiene_el_temporizador(self):
        self.conectado_con_datos()
        self.vm.cerrar()
        self.assertFalse(self.vm._watchdog.isActive())


class TestRegistroPeriodico(BaseVm):

    def ultima(self):
        return self.repo.todas_las_mediciones()[-1]

    def test_solo_registra_con_enlace_conectado(self):
        self.assertFalse(self.vm.registrar_medicion())                 # DESCONECTADO
        self.vm.conectar()
        self.assertFalse(self.vm.registrar_medicion())                 # CONECTANDO
        self.vm.on_estado_enlace_actualizado(ConexionEstado.CALIBRANDO)
        paquete(self.vm)
        self.assertFalse(self.vm.registrar_medicion())                 # CALIBRANDO
        self.vm.on_estado_enlace_actualizado(ConexionEstado.CONECTADO)
        self.assertTrue(self.vm.registrar_medicion())
        self.vm.on_estado_enlace_actualizado(ConexionEstado.ERROR_COMUNICACION)
        self.assertFalse(self.vm.registrar_medicion())
        self.assertEqual(self.repo.contar_mediciones(), 1)

    def test_guarda_todos_los_campos_con_fecha_y_hora(self):
        self.conectado()
        self.assertTrue(self.vm.registrar_medicion())
        m = self.ultima()
        self.assertEqual((m.bpm, m.rpm, m.temp_c, m.nivel_actividad, m.etiqueta, m.ts),
                         (72.0, 15.0, 36.5, 0, "PERIODICO", AHORA))

    def test_emite_historial_actualizado(self):
        avisos = []
        self.vm.historial_actualizado.connect(lambda: avisos.append(1))
        self.conectado()
        self.vm.registrar_medicion()
        self.assertEqual(len(avisos), 1)

    def test_usa_la_media_una_vez_y_luego_el_instantaneo(self):
        self.conectado()
        self.vm.on_media_bpm(75.0)
        self.vm.registrar_medicion()
        self.vm.registrar_medicion()           # la media ya se usó: caduca
        self.assertEqual([m.bpm for m in self.repo.todas_las_mediciones()][-2:], [75.0, 72.0])

    def test_media_invalida_se_ignora(self):
        self.conectado()
        for malo in (0.0, float("nan"), 5.0, 900.0):
            self.vm.on_media_bpm(malo)
        self.vm.registrar_medicion()
        self.assertEqual(self.ultima().bpm, 72.0)

    def test_media_sin_enlace_no_se_recuerda(self):
        self.vm.on_media_bpm(75.0)             # DESCONECTADO
        self.conectado()
        self.vm.registrar_medicion()
        self.assertEqual(self.ultima().bpm, 72.0)

    def test_se_pierde_la_media_al_caer_el_enlace(self):
        self.conectado()
        self.vm.on_media_bpm(75.0)
        self.vm.on_estado_enlace_actualizado(ConexionEstado.ERROR_COMUNICACION)
        self.vm.on_estado_enlace_actualizado(ConexionEstado.CONECTANDO)
        paquete(self.vm, bpm=90.0)
        self.vm.registrar_medicion()
        self.assertEqual(self.ultima().bpm, 90.0)

    def test_bpm_invalido_no_se_registra(self):
        self.conectado(bpm=0.0)                # el firmware aún "calcula"
        self.assertFalse(self.vm.registrar_medicion())
        self.assertEqual(self.repo.contar_mediciones(), 0)

    def test_rpm_y_temperatura_invalidas_quedan_vacias(self):
        self.vm.conectar()
        for _ in range(3):
            self.vm.on_paquete_telemetria(1600.0, 70.0, 0.0, float("nan"), 255, 255)
        self.vm.registrar_medicion()
        m = self.ultima()
        self.assertEqual((m.bpm, m.rpm, m.temp_c, m.nivel_actividad), (70.0, None, None, 255))

    def test_codigo_de_actividad_desconocido_queda_vacio(self):
        self.vm.conectar()
        for _ in range(3):
            self.vm.on_paquete_telemetria(1600.0, 70.0, 15.0, 36.5, 9, 255)
        self.vm.registrar_medicion()
        self.assertIsNone(self.ultima().nivel_actividad)

    def test_sin_repositorio_no_hace_nada(self):
        vm = VitaBandViewModel(self.mqtt)
        vm.conectar()
        paquete(vm)
        self.assertFalse(vm.registrar_medicion())

    def test_error_al_guardar_no_rompe(self):
        self.conectado()
        self.repo.guardar_medicion = MagicMock(side_effect=RuntimeError("disco lleno"))
        self.assertFalse(self.vm.registrar_medicion())


class TestEcgHistoricoVm(BaseVm):

    def segundos(self, desde=None, hasta=None):
        return self.repo.ecg_rango(desde or AHORA - 10, hasta or AHORA + 10)

    def test_guarda_la_envolvente_por_segundo(self):
        self.conectado()                                   # 3 muestras de 1600 en AHORA
        self.vm.on_paquete_telemetria(1000.0, 72.0, 15.0, 36.5, 0, 255)
        self.vm.on_paquete_telemetria(2000.0, 72.0, 15.0, 36.5, 0, 255)
        self.ahora += 1
        self.vm.on_paquete_telemetria(1700.0, 72.0, 15.0, 36.5, 0, 255)   # cierra el segundo anterior
        self.vm.registrar_medicion()                       # el temporizador vuelca a disco
        segs = self.segundos()
        self.assertEqual([(s.ts, s.minimo, s.maximo) for s in segs], [(AHORA, 1000, 2000)])

    def test_el_segundo_abierto_se_guarda_al_desconectar(self):
        self.conectado()
        self.vm.desconectar()
        self.assertEqual([(s.ts, s.minimo, s.maximo) for s in self.segundos()], [(AHORA, 1600, 1600)])

    def test_el_segundo_abierto_se_guarda_al_cerrar_sesion(self):
        self.conectado()
        guardar = MagicMock()
        self.repo.guardar_ecg_segundos = guardar
        self.vm.cerrar()
        guardar.assert_called_once()
        self.assertEqual([(s.ts, s.minimo, s.maximo) for s in guardar.call_args.args[0]], [(AHORA, 1600, 1600)])

    def test_el_ecg_crudo_no_se_guarda(self):
        self.conectado()
        self.vm.cambiarModoEcg(True)                       # guarda el segundo filtrado en curso
        self.ahora += 5
        paquete(self.vm, ecg=4000.0)
        self.vm.desconectar()
        self.assertEqual([(s.ts, s.minimo) for s in self.segundos(AHORA, AHORA + 20)], [(AHORA, 1600)])

    def test_volver_a_filtrado_reanuda_el_guardado(self):
        self.conectado()
        self.vm.cambiarModoEcg(True)
        self.vm.cambiarModoEcg(False)
        self.ahora += 5
        paquete(self.vm, ecg=1234.0)
        self.vm.desconectar()
        self.assertIn(1234, [s.minimo for s in self.segundos(AHORA, AHORA + 20)])

    def test_un_silencio_de_telemetria_vuelca_lo_pendiente(self):
        self.conectado()
        self.vm.on_estado_enlace_actualizado(ConexionEstado.ERROR_COMUNICACION)
        self.assertEqual(len(self.segundos()), 1)

    def test_ecg_no_finito_se_ignora(self):
        self.vm.conectar()
        for _ in range(3):
            self.vm.on_paquete_telemetria(float("nan"), 72.0, 15.0, 36.5, 0, 255)
        self.vm.desconectar()
        self.assertEqual(self.segundos(), [])

    def test_sin_repositorio_no_acumula(self):
        vm = VitaBandViewModel(self.mqtt)
        vm.conectar()
        paquete(vm)
        vm.desconectar()
        self.assertEqual(vm._ecg_pendiente, [])


def paquete_json(usuario="ana@correo.com", **cambios):
    base = {
        "version": 1, "usuario": usuario,
        "actividades": [{"uid": "a1", "inicio": T(10, 9), "fin": T(10, 10), "tipo": "carrera"}],
        "mediciones": [
            {"uid": "m1", "ts": T(10, 8), "bpm": 62, "rpm": 14, "temp": 36.4, "actividad": 0},
            {"uid": "m2", "ts": T(10, 9, 5), "bpm": 140, "etiqueta": "ACTIVIDAD", "actividad_uid": "a1"},
        ],
        "ecg": [],
    }
    base.update(cambios)
    return base


class BaseSync(BaseVm):
    def setUp(self):
        super().setUp()
        self.dir = tempfile.TemporaryDirectory()
        self.carpeta = os.path.join(self.dir.name, "intercambio")
        os.mkdir(self.carpeta)
        self.sync = ServicioSync(self.repo, self.carpeta, "ana@correo.com", reloj=lambda: self.ahora)
        self.vm = self.crear_vm(servicio_sync=self.sync, intervalo_sync_ms=0, intervalo_observaciones_ms=0)

    def tearDown(self):
        super().tearDown()
        self.dir.cleanup()

    def escribir(self, nombre, contenido):
        with open(os.path.join(self.carpeta, nombre), "w") as f:
            f.write(contenido if isinstance(contenido, str) else json.dumps(contenido))


class TestSincronizacionVm(BaseSync):

    def test_estado_inicial_y_refresco(self):
        self.assertEqual(self.vm.state.syncTexto, "Sin sincronizar")
        self.vm.refrescar_estado_sync()
        self.assertEqual(self.vm.state.syncTexto, "Sin archivos de intercambio")
        self.escribir("a.json", paquete_json())
        self.vm.refrescar_estado_sync()
        self.assertEqual((self.vm.state.syncPendientes, self.vm.state.syncSincronizados), (1, 0))
        self.assertIn("1 pendientes", self.vm.state.syncTexto)
        self.assertEqual(self.repo.contar_mediciones(), 0)             # refrescar no importa nada

    def test_sincronizar_importa_y_avisa(self):
        historial, obs = [], []
        self.vm.historial_actualizado.connect(lambda: historial.append(1))
        self.vm.observaciones_actualizadas.connect(lambda: obs.append(1))
        self.escribir("a.json", paquete_json())
        r = self.vm.sincronizar()
        self.assertEqual((r.importados, r.mediciones_nuevas), (1, 2))
        self.assertEqual((self.vm.state.syncPendientes, self.vm.state.syncSincronizados,
                          self.vm.state.syncErrores), (0, 1, 0))
        self.assertIn("Nuevos: 2 mediciones, 1 actividades", self.vm.state.syncTexto)
        self.assertIn("última:", self.vm.state.syncTexto)
        self.assertEqual(self.repo.contar_mediciones(), 2)
        self.assertEqual(len(historial), 1)
        self.assertEqual(len(obs), 1)                                  # observación de la actividad creada

    def test_segunda_sincronizacion_no_duplica_ni_emite(self):
        self.escribir("a.json", paquete_json())
        self.vm.sincronizar()
        estados, historial = [], []
        self.vm.state_changed.connect(estados.append)
        self.vm.historial_actualizado.connect(lambda: historial.append(1))
        r = self.vm.sincronizar()
        self.assertEqual((r.importados, r.sin_cambios), (0, 1))
        self.assertEqual(self.repo.contar_mediciones(), 2)
        self.assertEqual(historial, [])
        self.assertEqual(len(estados), 1)                              # solo cambia el texto: "Todo al día"
        self.assertIn("Todo al día", self.vm.state.syncTexto)
        self.vm.sincronizar()
        self.assertEqual(len(estados), 1)                              # sin cambios: no se re-emite

    def test_archivo_con_error(self):
        self.escribir("malo.json", "esto no es json")
        r = self.vm.sincronizar()
        self.assertEqual(r.rechazados, 1)
        self.assertEqual(self.vm.state.syncErrores, 1)
        self.assertIn("1 con error", self.vm.state.syncTexto)
        self.assertEqual(self.repo.contar_mediciones(), 0)

    def test_carpeta_inexistente(self):
        sync = ServicioSync(self.repo, os.path.join(self.dir.name, "nada"), "ana@correo.com")
        vm = self.crear_vm(servicio_sync=sync, intervalo_sync_ms=0)
        vm.sincronizar()
        self.assertEqual(vm.state.syncTexto, "Carpeta de intercambio no encontrada")

    def test_fallo_inesperado_no_rompe(self):
        servicio = MagicMock()
        servicio.sincronizar.side_effect = RuntimeError("boom")
        vm = self.crear_vm(servicio_sync=servicio, intervalo_sync_ms=0)
        self.assertIsNone(vm.sincronizar())
        self.assertEqual(vm.state.syncTexto, "Error al sincronizar")

    def test_el_registro_en_vivo_y_la_sincronizacion_conviven(self):
        self.conectado()
        self.vm.registrar_medicion()
        self.escribir("a.json", paquete_json())
        self.vm.sincronizar()
        self.assertEqual(self.repo.contar_mediciones(), 3)
        self.assertEqual(len(self.vm.actividades(T(10), T(11))), 1)

    def test_texto_sync(self):
        from services.servicio_sync import ArchivoSync, EstadoSync
        e = lambda *a, ultima=None, carpeta=True: EstadoSync(carpeta, tuple(a), ultima)
        self.assertEqual(texto_sync(e(carpeta=False)), "Carpeta de intercambio no encontrada")
        self.assertEqual(texto_sync(e()), "Sin archivos de intercambio")
        self.assertEqual(texto_sync(e(ArchivoSync("a", "SINCRONIZADO"))), "Sin pendientes")
        self.assertEqual(texto_sync(e(ArchivoSync("a", "ERROR"), ArchivoSync("b", "PENDIENTE"))),
                         "1 con error · 1 pendientes")


class TestArranque(BaseSync):

    def test_arrancar_purga_sincroniza_y_genera_observaciones(self):
        self.repo.guardar_medicion(60, datetime.fromtimestamp(AHORA - 100 * DIA), uid="viejo")
        self.repo.guardar_medicion(61, datetime.fromtimestamp(AHORA - DIA), uid="reciente")
        self.escribir("a.json", paquete_json())
        r = self.vm.arrancar()
        self.assertEqual(r.errores, ())
        self.assertEqual(r.purga.mediciones, 1)
        self.assertEqual((r.sync.importados, r.sync.mediciones_nuevas), (1, 2))
        self.assertGreaterEqual(r.observaciones.total, 1)
        self.assertEqual(sorted(m.uid for m in self.repo.todas_las_mediciones() if m.uid in ("viejo", "reciente")),
                         ["reciente"])
        self.assertEqual(self.vm.state.syncSincronizados, 1)

    def test_arrancar_dos_veces_es_idempotente(self):
        self.escribir("a.json", paquete_json())
        self.vm.arrancar()
        r = self.vm.arrancar()
        self.assertEqual((r.sync.importados, r.sync.sin_cambios, r.observaciones.total), (0, 1, 0))
        self.assertEqual(self.repo.contar_mediciones(), 2)

    def test_un_paso_que_falla_no_impide_los_demas(self):
        self.repo.purgar = MagicMock(side_effect=RuntimeError("boom"))
        self.escribir("a.json", paquete_json())
        r = self.vm.arrancar()
        self.assertIsNone(r.purga)
        self.assertEqual(len(r.errores), 1)
        self.assertIn("purga", r.errores[0])
        self.assertEqual(r.sync.importados, 1)

    def test_sin_servicios_arranca_igualmente(self):
        vm = self.crear_vm(intervalo_sync_ms=0)
        r = vm.arrancar()
        self.assertIsNone(r.sync)
        self.assertEqual(r.errores, ())
        self.assertTrue(vm._timer_registro.isActive())
        self.assertFalse(vm._timer_sync.isActive())
        vm._timer_registro.stop()

    def test_los_temporizadores_se_activan_y_cerrar_los_para(self):
        vm = self.crear_vm(servicio_sync=self.sync, intervalo_sync_ms=50_000, intervalo_observaciones_ms=50_000)
        vm.arrancar()
        self.assertTrue(all(t.isActive() for t in (vm._timer_registro, vm._timer_sync, vm._timer_obs)))
        vm._repositorio = None                 # la BD la cierra el tearDown de la base
        vm.cerrar()
        self.assertFalse(any(t.isActive() for t in (vm._timer_registro, vm._timer_sync, vm._timer_obs)))

    def test_el_temporizador_de_registro_guarda_mediciones(self):
        vm = self.crear_vm(intervalo_registro_ms=40, intervalo_sync_ms=0, intervalo_observaciones_ms=0)
        vm.arrancar()
        vm.conectar()
        paquete(vm)
        esperar(150)
        vm._timer_registro.stop()
        self.assertGreaterEqual(self.repo.contar_mediciones(), 1)

    def test_el_temporizador_de_sync_recoge_archivos_nuevos(self):
        vm = self.crear_vm(servicio_sync=self.sync, intervalo_sync_ms=40, intervalo_observaciones_ms=0)
        vm.arrancar()
        self.assertEqual(self.repo.contar_mediciones(), 0)
        self.escribir("tarde.json", paquete_json())
        esperar(150)
        vm._timer_sync.stop()
        vm._timer_registro.stop()
        self.assertEqual(self.repo.contar_mediciones(), 2)


if __name__ == "__main__":
    unittest.main()
