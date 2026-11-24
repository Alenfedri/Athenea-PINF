"""Pitido de latido, detector de picos R, fantasma de sesión, piloto de zona y acoplamiento pulso-respiración."""

import io
import math
import os
import unittest
import wave
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication

from domain.calidad_contacto import CalidadContacto
from domain.ui_state import ConexionEstado
from services import funciones_en_vivo as fv
from services.repositorio_historial import RepositorioHistorial
from ui.main_window import MainWindow
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])


class TestPitido(unittest.TestCase):

    def test_buffer_pcm_dura_55_ms_a_880_hz(self):
        pcm = fv.pitido_pcm()
        muestras = np.frombuffer(pcm, dtype="<i2")
        self.assertEqual(len(muestras), int(44100 * 0.055))
        self.assertEqual(len(pcm), 2 * len(muestras))
        self.assertGreater(int(np.abs(muestras).max()), 10_000)
        self.assertLess(int(np.abs(muestras).max()), 32767)
        # frecuencia dominante ≈ 880 Hz
        espectro = np.abs(np.fft.rfft(muestras * np.hanning(len(muestras))))
        f = np.fft.rfftfreq(len(muestras), 1 / 44100)[int(np.argmax(espectro))]
        self.assertAlmostEqual(f, 880.0, delta=40)

    def test_envolvente_suave_sin_chasquidos(self):
        m = np.frombuffer(fv.pitido_pcm(), dtype="<i2").astype(int)
        self.assertLess(abs(int(m[0])), 50)
        self.assertLess(abs(int(m[-1])), 50)
        self.assertLess(int(np.abs(m[:20]).max()), int(np.abs(m).max()) // 5)       # arranque gradual
        self.assertLess(int(np.abs(m[-20:]).max()), int(np.abs(m).max()) // 5)      # final gradual

    def test_volumen_escala_la_amplitud(self):
        a = np.abs(np.frombuffer(fv.pitido_pcm(1.0), dtype="<i2")).max()
        b = np.abs(np.frombuffer(fv.pitido_pcm(0.5), dtype="<i2")).max()
        self.assertAlmostEqual(b / a, 0.5, delta=0.02)
        self.assertEqual(np.abs(np.frombuffer(fv.pitido_pcm(0.0), dtype="<i2")).max(), 0)
        self.assertEqual(fv.pitido_pcm(5.0), fv.pitido_pcm(1.0))                   # se acota a 0–1

    def test_wav_valido_en_memoria(self):
        with wave.open(io.BytesIO(fv.pitido_wav()), "rb") as w:
            self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate()), (1, 2, 44100))
            self.assertEqual(w.getnframes(), int(44100 * 0.055))

    def test_disparo_sin_hardware_de_audio_no_falla(self):
        g = fv.GeneradorPitidoCardiaco(0.5)
        for _ in range(5):
            self.assertIn(g.pitar(), (True, False))            # sin altavoz devuelve False, sin excepción
        self.assertEqual(g.disparos, 5)

    def test_silenciado_y_volumen_cero_no_disparan(self):
        g = fv.GeneradorPitidoCardiaco(0.5, silenciado=True)
        self.assertFalse(g.pitar())
        self.assertEqual(g.disparos, 0)
        g.silenciado = False
        g.volumen = 0.0
        self.assertFalse(g.pitar())
        g.volumen = 7
        self.assertEqual(g.volumen, 1.0)
        g.volumen = -1
        self.assertEqual(g.volumen, 0.0)

    def test_reproduce_con_un_sink_disponible(self):
        g = fv.GeneradorPitidoCardiaco(0.5)
        g._sink, g._buffer, g.disponible = MagicMock(), MagicMock(), True
        self.assertTrue(g.pitar())
        g._buffer.seek.assert_called_with(0)
        g._sink.start.assert_called_once_with(g._buffer)
        g.volumen = 0.25
        g._sink.setVolume.assert_called_with(0.25)

    def test_si_el_sink_falla_se_desactiva_sin_romper(self):
        g = fv.GeneradorPitidoCardiaco(0.5)
        g._sink, g._buffer, g.disponible = MagicMock(), MagicMock(), True
        g._sink.start.side_effect = RuntimeError("sin dispositivo")
        self.assertFalse(g.pitar())
        self.assertFalse(g.disponible)
        self.assertFalse(g.pitar())


def ecg_sintetico(rr_ms, fs=100, ruido=0.02, semilla=1):
    rng = np.random.default_rng(semilla)
    t_picos = np.cumsum([500.0] + list(rr_ms))
    n = int(t_picos[-1] / 1000 * fs) + 100
    x = rng.normal(0, ruido, n) + 3.0                    # con desplazamiento continuo
    k = np.arange(n) * 1000.0 / fs
    for tp in t_picos:
        x += np.exp(-((k - tp) ** 2) / (2 * 15.0 ** 2))
    return x, t_picos


class TestDetectorLatido(unittest.TestCase):

    def test_un_aviso_por_latido_en_el_momento_correcto(self):
        x, picos = ecg_sintetico([800.0] * 40)
        d = fv.DetectorLatido()
        t_det = [i * 10.0 for i, v in enumerate(x) if d.agregar(float(v))]
        esperados = [p for p in picos if p > 2500]
        self.assertAlmostEqual(len(t_det), len(esperados), delta=2)
        for t in t_det[3:]:
            self.assertLess(min(abs(t - p) for p in picos), 40)      # a menos de 40 ms de un pico real
        self.assertEqual(d.latidos, len(t_det))

    def test_sigue_el_ritmo_cuando_cambia_el_pulso(self):
        x, _ = ecg_sintetico([1000.0] * 15 + [500.0] * 30)
        d = fv.DetectorLatido()
        t_det = np.array([i * 10.0 for i, v in enumerate(x) if d.agregar(float(v))])
        rr = np.diff(t_det)
        self.assertAlmostEqual(float(np.median(rr[:8])), 1000.0, delta=60)
        self.assertAlmostEqual(float(np.median(rr[-10:])), 500.0, delta=60)

    def test_periodo_refractario_evita_dobles(self):
        d = fv.DetectorLatido()
        x, _ = ecg_sintetico([800.0] * 20)
        det = [i for i, v in enumerate(x) if d.agregar(float(v))]
        self.assertTrue(all(b - a >= 30 for a, b in zip(det, det[1:])))

    def test_senal_plana_o_no_finita(self):
        d = fv.DetectorLatido()
        self.assertFalse(any(d.agregar(1.0) for _ in range(1000)))
        self.assertFalse(d.agregar(float("nan")))
        self.assertEqual(d.latidos, 0)


class TestFantasma(unittest.TestCase):
    ts0 = int(datetime(2026, 11, 3, 8).timestamp())

    def fantasma(self):
        return fv.SesionFantasma(self.ts0, [(t, 130.0 + t / 60.0) for t in range(0, 600, 10)])     # 130 → 140

    def test_alineacion_temporal(self):
        f = self.fantasma()
        self.assertAlmostEqual(f.bpm_en(0), 130.0, delta=0.6)
        self.assertAlmostEqual(f.bpm_en(300), 135.0, delta=0.6)
        self.assertAlmostEqual(f.bpm_en(590), 139.5, delta=0.6)
        self.assertIsNone(f.bpm_en(700))
        self.assertEqual(f.duracion_s, 590.0)

    def test_delta_bpm_y_textos(self):
        f = self.fantasma()
        c = f.comparar(300, 128.0)
        self.assertAlmostEqual(c.delta, -7.0, delta=0.6)
        self.assertEqual(c.nivel, "mejor")
        self.assertEqual(c.texto, "Vas 7 bpm más bajo que en tu sesión del 03/11/2026")
        self.assertIn("más alto", f.comparar(300, 138).texto)
        self.assertIn("mismo pulso", f.comparar(300, 135.2).texto)

    def test_color_y_eficiencia(self):
        f = self.fantasma()
        self.assertEqual(f.comparar(300, 130).color, "#2ECC40")          # verde: menos pulso
        self.assertEqual(f.comparar(300, 135.0).color, "#2ECC40")        # Δ ≈ 0
        self.assertEqual(f.comparar(300, 138).color, "#FFC20E")          # ámbar: +3
        self.assertEqual(f.comparar(300, 150).color, "#E8231A")          # rojo: +15
        self.assertGreater(f.comparar(300, 120).ratio, 1.0)
        self.assertLess(f.comparar(300, 150).ratio, 1.0)

    def test_sin_datos_validos(self):
        f = self.fantasma()
        self.assertIsNone(f.comparar(300, None))
        self.assertIsNone(f.comparar(300, 0))
        self.assertIsNone(f.comparar(-5, 120))
        self.assertIsNone(f.comparar(5000, 120))
        self.assertIsNone(fv.SesionFantasma(0, []).bpm_en(10))
        self.assertIsNone(fv.SesionFantasma(0, [(0, 0), (5, float("nan"))]).bpm_en(1))

    def test_controlador(self):
        c = fv.ControladorFantasma()
        self.assertFalse(c.activo)
        self.assertIsNone(c.actualizar(10, 120))
        c.cargar(self.fantasma())
        self.assertTrue(c.activo)
        self.assertIsNotNone(c.actualizar(10, 120))
        self.assertFalse(c.terminado(300))
        self.assertTrue(c.terminado(700))
        c.cargar(None)
        self.assertFalse(c.terminado(700))


class Reloj:
    t = 1_000.0

    def __call__(self):
        return self.t


class TestFantasmaEnVm(unittest.TestCase):

    def setUp(self):
        self.reloj = Reloj()
        self.repo = RepositorioHistorial(":memory:", usuario_id=1)
        self.vm = VitaBandViewModel(MagicMock(), repositorio=self.repo, reloj=self.reloj)
        self.v = MainWindow(self.vm, "Ana")
        ini = int(datetime(2026, 11, 3, 8).timestamp())
        self.aid = self.repo.guardar_actividad("g", ini, ini + 1200, "carrera")
        for i in range(120):
            self.repo.guardar_medicion(140.0, datetime.fromtimestamp(ini + i * 10), uid=f"g{i}", rpm=20,
                                       etiqueta="ACTIVIDAD", actividad_id=self.aid, nivel_actividad=1)

    def tearDown(self):
        self.v.close()
        self.vm.cerrar()

    def estado(self, **kw):
        self.vm._emitir_nuevo_estado(conexionEstado=ConexionEstado.CONECTADO,
                                     calidadContacto=CalidadContacto.OPTIMO, **kw)

    def test_selector_lista_las_sesiones_guardadas(self):
        self.vm.historial_actualizado.emit()
        self.assertEqual(self.v.combo_fantasma.itemData(0), None)
        self.assertEqual(self.v.combo_fantasma.itemData(1), self.aid)
        self.assertIn("20 min", self.v.combo_fantasma.itemText(1))

    def test_delta_en_vivo_alineado_con_el_segundo_transcurrido(self):
        self.vm.historial_actualizado.emit()
        self.v.combo_fantasma.setCurrentIndex(1)
        self.assertTrue(self.vm.fantasma.activo)
        self.estado(bpmTexto="133.0 BPM")
        for _ in range(60):                                   # 60 s de sesión efectiva
            self.reloj.t += 1
            self.estado(bpmTexto="133.0 BPM")
        c = self.vm.comparacion_fantasma()
        self.assertAlmostEqual(c.delta, -7.0, delta=0.01)
        self.assertAlmostEqual(self.vm.tiempo_sesion_s(), 60.0, delta=2)
        self.assertIn("Vas 7 bpm más bajo que en tu sesión del 03/11/2026", self.v.lbl_fantasma.text())
        self.assertGreater(self.v.barra_fantasma.value(), 50)
        self.assertIn("2ECC40", self.v.barra_fantasma.styleSheet())
        self.estado(bpmTexto="150.0 BPM")
        self.assertLess(self.v.barra_fantasma.value(), 50)
        self.assertIn("E8231A", self.v.barra_fantasma.styleSheet())

    def test_sin_banda_o_sin_fantasma_no_hay_comparacion(self):
        self.assertIsNone(self.vm.comparacion_fantasma())
        self.vm.seleccionar_fantasma(self.aid)
        self.vm._emitir_nuevo_estado(conexionEstado=ConexionEstado.DESCONECTADO, bpmTexto="133.0 BPM")
        self.assertIsNone(self.vm.comparacion_fantasma())
        self.assertTrue(self.vm.seleccionar_fantasma(None))
        self.assertFalse(self.vm.fantasma.activo)

    def test_sesion_con_poco_pulso_no_sirve_de_fantasma(self):
        corta = self.repo.guardar_actividad("c", 5, 100, "x")
        self.assertFalse(self.vm.seleccionar_fantasma(corta))
        self.assertFalse(self.vm.fantasma.activo)
        self.assertFalse(self.vm.seleccionar_fantasma(99999))


class TestPiloto(unittest.TestCase):
    FC = 190.0

    def test_rangos_segun_fc_max(self):
        self.assertEqual(fv.rango_zona(1, 190), (114.0, 133.0))             # Z2 = 60–70 %
        self.assertEqual(fv.rango_zona(4, 200), (180.0, 200.0))
        self.assertEqual(fv.rango_zona(0, 200)[0], 100.0)
        self.assertEqual(fv.OPCIONES_ZONA, ("Desactivado", "Z1", "Z2", "Z3", "Z4", "Z5"))

    def test_tres_estados(self):
        p = fv.PilotoZonaObjetivo(self.FC, zona=1)                           # Z2: 114–133
        self.assertEqual(p.evaluar(100).texto, "Sube el ritmo")
        self.assertEqual(p.evaluar(100).estado, "sube")
        self.assertAlmostEqual(p.evaluar(100).desviacion_bpm, -14.0)
        self.assertEqual(p.evaluar(120).texto, "Ritmo clavado")
        self.assertEqual(p.evaluar(120).desviacion_bpm, 0.0)
        self.assertEqual(p.evaluar(150).texto, "Frena un poco")
        self.assertAlmostEqual(p.evaluar(150).desviacion_bpm, 17.0)

    def test_limites_exactos(self):
        p = fv.PilotoZonaObjetivo(self.FC, zona=1)
        self.assertEqual(p.evaluar(114.0).estado, "clavado")
        self.assertEqual(p.evaluar(113.9).estado, "sube")
        self.assertEqual(p.evaluar(132.9).estado, "clavado")
        self.assertEqual(p.evaluar(133.0).estado, "frena")

    def test_z5_no_tiene_techo_hasta_la_fc_max(self):
        p = fv.PilotoZonaObjetivo(self.FC, zona=4)
        self.assertEqual(p.evaluar(185).estado, "clavado")
        self.assertEqual(p.evaluar(190).estado, "clavado")
        self.assertEqual(p.evaluar(195).estado, "frena")

    def test_desactivado_y_sin_pulso(self):
        p = fv.PilotoZonaObjetivo(self.FC)
        self.assertEqual(p.evaluar(150).texto, "Desactivado")
        p.zona = 2
        self.assertEqual(p.evaluar(None).estado, "sin_dato")
        self.assertEqual(p.evaluar(0).estado, "sin_dato")

    def test_fc_max_personalizada(self):
        self.assertAlmostEqual(fv.fc_max_usuario(30), 187.0)
        self.assertEqual(fv.fc_max_usuario(None), 190.0)
        self.assertEqual(fv.estado_piloto(150, 1, 160), "frena")             # con FCmáx 160, Z2 = 96–112


class TestAcoplamiento(unittest.TestCase):

    def alimentar(self, a, segundos=60, rpm=12.0, amp=4.0, fase0=0.7, ruido=0.0, f_resp=None, seed=0):
        rng = np.random.default_rng(seed)
        f = (rpm if f_resp is None else f_resp) / 60.0
        for i in range(segundos + 1):
            bpm = 70 + amp * math.sin(2 * math.pi * f * i + fase0) + rng.normal(0, ruido)
            a.agregar(float(i), bpm, rpm)

    def test_pulso_que_sigue_la_respiracion_da_indice_alto(self):
        a = fv.CalculadorAcoplamientoRSA()
        self.alimentar(a, 60, rpm=12)
        r = a.resultado()
        self.assertGreater(r.indice, 90)
        self.assertAlmostEqual(r.amplitud_bpm, 8.0, delta=1.0)
        self.assertIn("clara", r.texto)

    def test_la_onda_respiratoria_se_alinea_con_el_pulso(self):
        a = fv.CalculadorAcoplamientoRSA()
        self.alimentar(a, 60, rpm=12, fase0=2.0)
        t, resp, bpm = a.ondas()
        self.assertEqual(len(t), len(resp))
        self.assertEqual(len(t), len(bpm))
        self.assertAlmostEqual(t[-1], 0.0)
        self.assertGreater(float(np.corrcoef(resp, bpm)[0, 1]), 0.95)

    def test_pulso_que_oscila_a_otra_frecuencia_da_indice_bajo(self):
        a = fv.CalculadorAcoplamientoRSA()
        self.alimentar(a, 60, rpm=12, f_resp=21)
        self.assertLess(a.resultado().indice, 35)

    def test_ruido_sin_oscilacion(self):
        a = fv.CalculadorAcoplamientoRSA()
        self.alimentar(a, 60, rpm=12, amp=0.0, ruido=0.4)
        r = a.resultado()
        self.assertLess(r.indice, 30)
        self.assertIn("Sin acoplamiento", r.texto)

    def test_oscilacion_minima_no_cuenta(self):
        a = fv.CalculadorAcoplamientoRSA()
        self.alimentar(a, 60, rpm=12, amp=0.3)
        self.assertEqual(a.resultado().indice, 0.0)

    def test_pocos_datos_o_sin_respiracion(self):
        a = fv.CalculadorAcoplamientoRSA()
        self.assertIsNone(a.resultado())
        self.assertEqual(a.ondas(), ([], [], []))
        self.alimentar(a, 10, rpm=12)
        self.assertIsNone(a.resultado())
        a.agregar(11.0, 70, 0)                               # RPM 0: se descarta todo
        self.assertEqual(a.ondas(), ([], [], []))

    def test_un_hueco_largo_reinicia_la_fase(self):
        a = fv.CalculadorAcoplamientoRSA()
        self.alimentar(a, 30, rpm=12)
        a.agregar(100.0, 70, 12)
        self.assertEqual(len(a._datos), 1)

    def test_la_ventana_se_limita_a_60_s(self):
        a = fv.CalculadorAcoplamientoRSA()
        self.alimentar(a, 200, rpm=12)
        self.assertLessEqual(a._datos[-1][0] - a._datos[0][0], 60.0)

    def test_visualizador_en_tiempo_real(self):
        vm = VitaBandViewModel(MagicMock(), reloj=Reloj())
        v = MainWindow(vm, "Ana")
        for i in range(60):
            vm._reloj.t += 1
            bpm = 70 + 4 * math.sin(2 * math.pi * 0.2 * i)
            vm._emitir_nuevo_estado(conexionEstado=ConexionEstado.CONECTADO, bpmTexto=f"{bpm:.1f} BPM",
                                    rpmTexto="12.0 RPM")
        self.assertIn("Sincronización pulso-respiración", v.grafica_acoplamiento.lbl.text())
        self.assertGreater(len(v.grafica_acoplamiento.curva_bpm.getData()[0]), 20)
        self.assertGreater(len(v.grafica_acoplamiento.curva_resp.getData()[0]), 20)
        v.close()
        vm.cerrar()


class TestControlesDeSonido(unittest.TestCase):

    def setUp(self):
        self.vm = VitaBandViewModel(MagicMock(), reloj=Reloj())
        self.v = MainWindow(self.vm, "Ana")

    def tearDown(self):
        self.v.close()
        self.vm.cerrar()

    def test_por_defecto_silenciado_y_sin_deteccion(self):
        self.assertTrue(self.v.pitido.silenciado)
        self.assertFalse(self.vm.detectar_latidos)
        self.assertEqual(self.v.slider_volumen.value(), 70)

    def test_activar_dispara_un_pitido_por_latido(self):
        self.v.btn_latido.click()
        self.assertTrue(self.vm.detectar_latidos)
        self.assertFalse(self.v.pitido.silenciado)
        self.assertIn("activado", self.v.btn_latido.text())
        self.vm._emitir_nuevo_estado(conexionEstado=ConexionEstado.CONECTADO)
        x, _ = ecg_sintetico([800.0] * 25)
        n = 0
        for v in x:
            self.vm._ecg_buffer.append(float(v))
            if self.vm.detector_latido.agregar(float(v)):
                self.vm.latido.emit()
                n += 1
        self.assertGreater(n, 15)
        self.assertEqual(self.v.pitido.disparos, n)
        self.v.btn_latido.click()
        self.assertTrue(self.vm.detectar_latidos)                       # sigue detectando: anima la tarjeta de FC (pulso visual)
        self.vm.latido.emit()
        self.assertEqual(self.v.pitido.disparos, n)                     # silenciado: no cuenta

    def test_slider_de_volumen_0_a_100(self):
        self.v.slider_volumen.setValue(35)
        self.assertAlmostEqual(self.v.pitido.volumen, 0.35)
        self.assertIn("35 %", self.v.lbl_volumen.text())
        self.v.slider_volumen.setValue(0)
        self.assertEqual(self.v.pitido.volumen, 0.0)
        self.assertEqual((self.v.slider_volumen.minimum(), self.v.slider_volumen.maximum()), (0, 100))

    def test_el_vm_emite_latido_con_ecg_real(self):
        self.vm.activar_latidos(True)
        recibidos = []
        self.vm.latido.connect(lambda: recibidos.append(1))
        x, _ = ecg_sintetico([800.0] * 25)
        self.vm._emitir_nuevo_estado(conexionEstado=ConexionEstado.CONECTADO)
        for v in x:
            self.vm.detector_latido.agregar(float(v)) and recibidos.append(1)
        self.assertGreater(len(recibidos), 15)


class TestPilotoEnPantalla(unittest.TestCase):

    def setUp(self):
        self.vm = VitaBandViewModel(MagicMock(), reloj=Reloj())
        self.v = MainWindow(self.vm, "Ana")

    def tearDown(self):
        if getattr(self.v, "modo_entrenamiento", None):
            self.v.modo_entrenamiento.close()
        self.v.close()
        self.vm.cerrar()

    def estado(self, bpm):
        self.vm._emitir_nuevo_estado(conexionEstado=ConexionEstado.CONECTADO, bpmTexto=f"{bpm:.1f} BPM")

    def test_selector_y_tres_estados_en_tiempo_real(self):
        self.assertEqual([self.v.combo_zona.itemText(i) for i in range(6)], list(fv.OPCIONES_ZONA))
        self.assertEqual(self.v.indicador_piloto.texto, "Desactivado")
        self.v.combo_zona.setCurrentIndex(2)                                   # Z2
        self.assertEqual(self.vm.zona_objetivo, 1)
        for bpm, texto in ((90, "Sube el ritmo"), (120, "Ritmo clavado"), (160, "Frena un poco")):
            self.estado(bpm)
            self.assertEqual(self.v.indicador_piloto.texto, texto)
        self.assertEqual(self.v.indicador_piloto.estado, "frena")
        self.v.indicador_piloto.grab()                                        # el dibujo no lanza excepciones

    def test_sincronizado_con_modo_entrenamiento(self):
        self.v._abrir_modo_entrenamiento()
        m = self.v.modo_entrenamiento
        self.assertEqual(m.combo_zona.currentIndex(), 0)
        m.combo_zona.setCurrentIndex(4)                                        # Z4 desde el Modo Entrenamiento
        self.assertEqual(self.vm.zona_objetivo, 3)
        self.assertEqual(self.v.combo_zona.currentIndex(), 4)
        self.v.combo_zona.setCurrentIndex(1)                                   # Z1 desde Tiempo real
        self.assertEqual(m.combo_zona.currentIndex(), 1)
        self.estado(100)
        self.assertEqual(m.indicador_piloto.texto, "Ritmo clavado")           # Z1 = 95–114 con FCmáx 190
        self.estado(170)
        self.assertEqual(m.indicador_piloto.texto, "Frena un poco")
        self.v.combo_zona.setCurrentIndex(0)
        self.assertEqual(m.indicador_piloto.texto, "Desactivado")

    def test_usa_la_fc_max_del_perfil(self):
        from services import calculos_fisiologicos as calc
        repo = RepositorioHistorial(":memory:", usuario_id=1)
        vm = VitaBandViewModel(MagicMock(), repositorio=repo, reloj=Reloj())
        vm.guardar_perfil(calc.PerfilFisiologico(60, "Hombre", 70.0))
        self.assertAlmostEqual(vm.fc_max(), 166.0)
        vm.set_zona_objetivo(1)
        self.assertEqual(vm.evaluar_piloto(100).estado, "clavado")            # Z2 con 166 = 99,6–116,2 BPM
        self.assertEqual(fv.estado_piloto(100, 1, 190.0), "sube")             # con la FCmáx de referencia no
        vm.cerrar()

    def test_zona_invalida(self):
        with self.assertRaises(ValueError):
            self.vm.set_zona_objetivo(7)


if __name__ == "__main__":
    unittest.main()
