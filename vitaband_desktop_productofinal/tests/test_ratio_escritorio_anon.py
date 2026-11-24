"""Cociente pulso/respiración, Modo Escritorio (pausa activa por estrés) y exportación anonimizada."""

import csv
import hashlib
import os
import re
import tempfile
import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from domain.hrv import ResultadoHrv
from domain.modelos import NIVEL_REPOSO
from domain.ui_state import ConexionEstado
from services import anonimizar as an
from services import estres_escritorio as es
from services import exportar_pdf as pdf
from services import ratio_pulso_resp as rt
from services.exportacion_csv import exportar_historial_csv
from services.repositorio_historial import RepositorioHistorial
from ui.dialogo_coherencia import DialogoCoherencia
from ui.main_window import MainWindow
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])
CORREO, NOMBRE = "ana.garcia@correo.es", "Ana García"


class TestRatio(unittest.TestCase):

    def test_formato_y_nd(self):
        self.assertEqual(rt.texto_ratio(rt.ratio(72, 18)), "4.0 : 1")
        self.assertEqual(rt.texto_ratio(rt.ratio(100, 16)), "6.2 : 1")
        for bpm, rpm in ((72, 0), (72, -3), (72, None), (0, 18), (None, 18)):
            self.assertIsNone(rt.ratio(bpm, rpm), (bpm, rpm))
            self.assertEqual(rt.texto_ratio(rt.ratio(bpm, rpm)), "N/D")

    def test_estados(self):
        self.assertEqual(rt.estado(None), "")
        self.assertEqual(rt.estado(2.9), "bajo")
        self.assertEqual(rt.estado(3.0), "aceptable")
        self.assertEqual(rt.estado(4.0), "óptimo")
        self.assertEqual(rt.estado(6.5), "aceptable")

    def test_ratio_medio_de_mediciones(self):
        ms = [SimpleNamespace(bpm=120, rpm=50), SimpleNamespace(bpm=120, rpm=10), SimpleNamespace(bpm=120, rpm=0)]
        r, bajos = rt.ratio_medio(ms)
        self.assertAlmostEqual(r, 4.0)                    # 120 / 30
        self.assertAlmostEqual(bajos, 50.0)               # 120/50 = 2,4 < 3:1; 120/10 no
        self.assertEqual(rt.ratio_medio([]), (None, 0.0))
        self.assertEqual(rt.ratio_medio([SimpleNamespace(bpm=90, rpm=0)]), (None, 0.0))


class TestMonitorRatio(unittest.TestCase):

    def correr(self, m, segundos, bpm, rpm, t0=0.0):
        for i in range(segundos + 1):
            m.actualizar(t0 + i, bpm, rpm)
        return t0 + segundos

    def test_alerta_solo_si_es_sostenido_60_s(self):
        m = rt.MonitorRatio()
        self.correr(m, 59, 60, 24)                        # 2,5 : 1
        self.assertFalse(m.alerta)
        m.actualizar(60, 60, 24)
        self.assertTrue(m.alerta)

    def test_un_valor_normal_reinicia_la_cuenta(self):
        m = rt.MonitorRatio()
        t = self.correr(m, 50, 60, 24)
        m.actualizar(t + 1, 72, 16)                       # 4,5 : 1
        self.assertFalse(m.alerta)
        self.correr(m, 40, 60, 24, t0=t + 2)
        self.assertFalse(m.alerta)

    def test_sin_respiracion_no_cuenta_ni_alerta(self):
        m = rt.MonitorRatio()
        self.correr(m, 120, 60, 0)
        self.assertFalse(m.alerta)
        self.assertIsNone(m.ratio)

    def test_el_limite_3_a_1_no_es_bajo(self):
        m = rt.MonitorRatio()
        self.correr(m, 120, 60, 20)                       # exactamente 3,0
        self.assertFalse(m.alerta)


class Reloj:
    t = 1_000.0

    def __call__(self):
        return self.t


class Base(unittest.TestCase):
    def setUp(self):
        self.reloj = Reloj()
        self.repo = RepositorioHistorial(":memory:", usuario_id=1)
        self.vm = VitaBandViewModel(MagicMock(), repositorio=self.repo, reloj=self.reloj)
        self.v = MainWindow(self.vm, NOMBRE, CORREO)

    def tearDown(self):
        for d in ("dialogo_coherencia",):
            if getattr(self.v, d, None):
                getattr(self.v, d).close()
        self.v.close()
        self.vm.cerrar()

    def estado(self, **kw):
        self.vm._emitir_nuevo_estado(conexionEstado=ConexionEstado.CONECTADO, **kw)

    def tic(self, s, **kw):
        for _ in range(s):
            self.reloj.t += 1
            self.estado(**kw)


class TestRatioEnPantalla(Base):

    def test_tiempo_real_muestra_el_ratio_y_la_alerta_sostenida(self):
        self.tic(5, bpmTexto="72.0 BPM", rpmTexto="18.0 RPM")
        self.assertIn("4.0 : 1", self.v.lbl_ratio.text())
        self.assertIn("óptimo", self.v.lbl_ratio.text())
        self.assertTrue(self.v.lbl_alerta_ratio.isHidden())
        self.tic(70, bpmTexto="60.0 BPM", rpmTexto="24.0 RPM")
        self.assertIn("2.5 : 1", self.v.lbl_ratio.text())
        self.assertFalse(self.v.lbl_alerta_ratio.isHidden())
        self.assertIn("hiperventilación", self.v.lbl_alerta_ratio.text())
        self.tic(1, bpmTexto="72.0 BPM", rpmTexto="18.0 RPM")
        self.assertTrue(self.v.lbl_alerta_ratio.isHidden())

    def test_rpm_cero_o_sin_banda_es_nd(self):
        self.tic(3, bpmTexto="72.0 BPM", rpmTexto="0.0 RPM")
        self.assertIn("N/D", self.v.lbl_ratio.text())
        self.vm._emitir_nuevo_estado(conexionEstado=ConexionEstado.DESCONECTADO, bpmTexto="72.0 BPM",
                                     rpmTexto="18.0 RPM")
        self.assertIn("N/D", self.v.lbl_ratio.text())

    def sesion(self, bpm, rpm):
        ini = int(datetime(2026, 11, 10, 8).timestamp())
        aid = self.repo.guardar_actividad("x", ini, ini + 1800)
        for i in range(180):
            self.repo.guardar_medicion(bpm, datetime.fromtimestamp(ini + i * 10), uid=f"m{i}", rpm=rpm,
                                       etiqueta="ACTIVIDAD", actividad_id=aid, nivel_actividad=1)
        return aid

    def texto_actividad(self, aid):
        return self.v.vista_actividades._texto_metricas(self.vm.detalle_actividad(aid))

    def test_actividades_resume_el_ratio(self):
        t = self.texto_actividad(self.sesion(140, 20))
        self.assertIn("Pulso/respiración medio: 7.0 : 1", t)
        self.assertNotIn("por debajo de 3:1", t)

    def test_actividades_alerta_si_pasa_mucho_tiempo_bajo_3(self):
        t = self.texto_actividad(self.sesion(60, 30))
        self.assertIn("2.0 : 1", t)
        self.assertIn("por debajo de 3:1", t)

    def test_actividades_sin_rpm_es_nd(self):
        self.assertIn("Pulso/respiración medio: N/D", self.texto_actividad(self.sesion(140, 0)))


class TestDetectorEstres(unittest.TestCase):
    """Un RMSSD por minuto y la respiración cada 5 s, durante ``minutos`` minutos."""

    def simular(self, rmssd, rpm, minutos=21, ventana=20, reposo=lambda t: True, d=None):
        d = d or es.DetectorEstres(ventana)
        avisos = []
        for seg in range(0, minutos * 60 + 1, 5):
            r = rmssd(seg / 60) if seg % 60 == 0 else None
            if d.actualizar(float(seg), reposo(seg / 60), r, rpm(seg / 60)):
                avisos.append(seg / 60)
        return avisos

    caida = staticmethod(lambda m: 50.0 - 1.2 * m)               # 50 → ~25 ms
    sube = staticmethod(lambda m: 14.0 + 0.2 * m)                # 14 → 18 RPM
    plano_rmssd = staticmethod(lambda m: 50.0)
    plano_rpm = staticmethod(lambda m: 14.0)

    def test_avisa_con_caida_de_rmssd_y_subida_de_rpm(self):
        avisos = self.simular(self.caida, self.sube)
        self.assertEqual(len(avisos), 1)
        self.assertGreaterEqual(avisos[0], 16)               # exige ≥ 80 % de la ventana

    def test_no_avisa_solo_con_rmssd_a_la_baja(self):
        self.assertEqual(self.simular(self.caida, self.plano_rpm), [])

    def test_no_avisa_solo_con_respiracion_al_alza(self):
        self.assertEqual(self.simular(self.plano_rmssd, self.sube), [])

    def test_no_avisa_con_caida_pequena(self):
        self.assertEqual(self.simular(lambda m: 50.0 - 0.2 * m, self.sube), [])      # ≈ 8 %

    def test_un_pico_de_ejercicio_reinicia_la_ventana(self):
        avisos = self.simular(self.caida, self.sube, reposo=lambda m: not (9 <= m < 10))
        self.assertEqual(avisos, [])                          # tras el esfuerzo hay <16 min de reposo

    def test_sin_banda_o_fuera_de_reposo_no_acumula(self):
        self.assertEqual(self.simular(self.caida, self.sube, reposo=lambda m: False), [])

    def test_ventana_configurable(self):
        avisos = self.simular(self.caida, self.sube, minutos=13, ventana=12)
        self.assertEqual(len(avisos), 1)
        self.assertLess(avisos[0], 13)
        self.assertEqual(self.simular(self.caida, self.sube, minutos=13, ventana=20), [])

    def test_espera_tras_un_aviso(self):
        d = es.DetectorEstres(20)
        avisos = self.simular(self.caida, self.sube, minutos=45, d=d)
        self.assertEqual(len(avisos), 1)

    def test_datos_insuficientes(self):
        d = es.DetectorEstres(20)
        self.assertFalse(d.actualizar(0.0, True, 50.0, 14.0))
        self.assertFalse(d.actualizar(1300.0, True, 20.0, 18.0))      # sin puntos suficientes en cada tercio


class TestModoEscritorio(Base):

    def setUp(self):
        super().setUp()
        self.avisos = []
        self.vm.aviso_estres.connect(self.avisos.append)

    def minuto_con_rmssd(self, rmssd, rpm):
        for _ in range(12):
            self.tic(5, rpmTexto=f"{rpm:.1f} RPM", bpmTexto="65.0 BPM")
        self.vm._acum_hrv = SimpleNamespace(
            agregar=lambda t, v: ResultadoHrv(int(t), rmssd, 65.0, 60), reiniciar=lambda: None)
        self.vm._acumular_hrv(0.0, NIVEL_REPOSO)

    def estresar(self, minutos=21):
        for m in range(minutos):
            self.minuto_con_rmssd(50.0 - 1.2 * m, 14.0 + 0.2 * m)

    def test_desactivado_no_avisa(self):
        self.estresar()
        self.assertEqual(self.avisos, [])

    def test_activado_avisa_con_caida_de_rmssd_y_subida_de_rpm(self):
        self.v.chk_escritorio.setChecked(True)
        self.estresar()
        self.assertEqual(len(self.avisos), 1)
        self.assertIn("Coherencia", self.avisos[0])
        self.assertFalse(self.v.lbl_estres.isHidden())
        self.assertFalse(self.v.btn_estres_coherencia.isHidden())

    def test_ventana_por_defecto_20_y_configurable(self):
        self.assertEqual(self.v.spin_escritorio.value(), 20)
        self.assertEqual(self.vm.detector_estres.ventana_min, 20)
        self.v.spin_escritorio.setValue(30)
        self.assertEqual(self.vm.detector_estres.ventana_min, 30)
        self.assertTrue(self.v.chk_escritorio.text() == "Modo Escritorio")

    def test_el_aviso_abre_la_coherencia_y_se_oculta(self):
        self.v.chk_escritorio.setChecked(True)
        self.estresar()
        self.v.btn_estres_coherencia.click()
        self.assertIsInstance(self.v.dialogo_coherencia, DialogoCoherencia)
        self.assertTrue(self.v.lbl_estres.isHidden())

    def test_desactivar_oculta_el_aviso(self):
        self.v.chk_escritorio.setChecked(True)
        self.estresar()
        self.v.chk_escritorio.setChecked(False)
        self.assertTrue(self.v.lbl_estres.isHidden())
        self.assertFalse(self.vm.modo_escritorio)

    def test_con_esfuerzo_no_avisa(self):
        self.v.chk_escritorio.setChecked(True)
        for m in range(21):
            self.minuto_con_rmssd(50.0 - 1.2 * m, 14.0 + 0.2 * m)
            self.vm._acum_hrv = SimpleNamespace(agregar=lambda t, v: None, reiniciar=lambda: None)
            self.vm._acumular_hrv(0.0, 2)                       # un segundo de actividad cada minuto
        self.assertEqual(self.avisos, [])


class TestSeudonimo(unittest.TestCase):

    def test_formato_y_determinismo(self):
        s = an.seudonimo(CORREO, NOMBRE)
        self.assertRegex(s, r"^SUJETO-[0-9a-f]{6}$")
        self.assertEqual(s, "SUJETO-" + hashlib.sha256(CORREO.encode()).hexdigest()[:6])
        self.assertEqual(s, an.seudonimo(CORREO, "Otro nombre"))
        self.assertEqual(s, an.seudonimo("  ANA.GARCIA@correo.es ", NOMBRE))

    def test_distintos_usuarios_distinto_seudonimo(self):
        self.assertNotEqual(an.seudonimo("a@x.es"), an.seudonimo("b@x.es"))

    def test_sin_correo_usa_el_nombre(self):
        self.assertEqual(an.seudonimo("", "Ana"), "SUJETO-" + hashlib.sha256(b"ana").hexdigest()[:6])

    def test_el_seudonimo_no_contiene_datos_personales(self):
        s = an.seudonimo(CORREO, NOMBRE).lower()
        self.assertNotIn("ana", s.replace("sujeto-", ""))


class TestExportacionAnonima(Base):

    def setUp(self):
        super().setUp()
        self.dir = tempfile.mkdtemp()
        self.sujeto = an.seudonimo(CORREO, NOMBRE)
        base = datetime(2026, 11, 10, 9)
        for i in range(5):
            self.repo.guardar_medicion(70 + i, base + timedelta(minutes=i), uid=f"m{i}", rpm=15)

    def exportar_csv(self, anonimo):
        ruta = os.path.join(self.dir, f"h{int(anonimo)}.csv")
        self.v.chk_anonimizar.setChecked(anonimo)
        with patch("ui.main_window.QFileDialog.getSaveFileName", return_value=(ruta, "")), \
             patch("ui.main_window.QMessageBox.information"):
            self.v._exportar_csv()
        with open(ruta, encoding="utf-8-sig", newline="") as f:
            return f.read(), list(csv.reader(open(ruta, encoding="utf-8-sig", newline=""), delimiter=";"))

    def test_casilla_junto_a_los_botones_de_exportacion(self):
        self.assertEqual(self.v.chk_anonimizar.text(), "Anonimizar datos personales")
        self.assertFalse(self.v.chk_anonimizar.isChecked())

    def test_csv_anonimo_lleva_el_seudonimo_en_cada_fila(self):
        texto, filas = self.exportar_csv(True)
        self.assertEqual(filas[0][-1], "sujeto")
        self.assertEqual({f[-1] for f in filas[1:]}, {self.sujeto})
        self.assertEqual(len(filas) - 1, 5)
        for dato in (NOMBRE, CORREO, "Ana", "garcia"):
            self.assertNotIn(dato.lower(), texto.lower())

    def test_csv_normal_no_cambia(self):
        _, filas = self.exportar_csv(False)
        self.assertEqual(len(filas[0]), 7)
        self.assertNotIn("sujeto", filas[0])

    def test_funcion_csv_directa(self):
        ruta = os.path.join(self.dir, "d.csv")
        n = exportar_historial_csv(self.repo.todas_las_mediciones(), ruta, "SUJETO-abcdef")
        self.assertEqual(n, 5)
        self.assertIn("SUJETO-abcdef", open(ruta, encoding="utf-8-sig").read())

    def cabecera_pdf(self, anonimo):
        ruta = os.path.join(self.dir, "i.pdf")
        self.v.chk_anonimizar.setChecked(anonimo)
        filas = []
        with patch("ui.main_window.QFileDialog.getSaveFileName", return_value=(ruta, "")), \
             patch("ui.main_window.QMessageBox.information"), \
             patch.object(pdf._Pagina, "tabla", lambda self, f: filas.extend(f)):
            self.v._exportar_pdf()
        self.assertTrue(os.path.exists(ruta))
        return dict(filas)

    def test_pdf_anonimo_sustituye_nombre_y_correo(self):
        c = self.cabecera_pdf(True)
        self.assertEqual(c["Usuario"], self.sujeto)
        self.assertNotIn(CORREO, c["Correo"])
        self.assertNotIn("Ana", " ".join(c.values()))
        self.assertIn("anonimizados", c["Correo"])

    def test_pdf_normal_mantiene_los_datos(self):
        c = self.cabecera_pdf(False)
        self.assertEqual(c["Usuario"], NOMBRE)
        self.assertEqual(c["Correo"], CORREO)

    def test_el_vm_tambien_anonimiza(self):
        ruta = os.path.join(self.dir, "vm.pdf")
        filas = []
        d = int(datetime(2026, 11, 1).timestamp())
        with patch.object(pdf._Pagina, "tabla", lambda self, f: filas.extend(f)):
            self.vm.exportar_pdf(ruta, d, d + 86400 * 30, NOMBRE, CORREO, True)
        self.assertEqual(dict(filas)["Usuario"], self.sujeto)

    def test_mismo_sujeto_en_pdf_y_csv(self):
        self.assertEqual(self.cabecera_pdf(True)["Usuario"], self.exportar_csv(True)[1][1][-1])


if __name__ == "__main__":
    unittest.main()
