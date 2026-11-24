"""Informe PDF: archivo válido, contenido completo, rangos vacíos y disparo desde la UI."""

import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from domain import ecg_historico as ecg, hrv
from services import exportar_pdf as pdf
from services.repositorio_historial import RepositorioHistorial
from services.servicio_observaciones import ServicioObservaciones
from ui.main_window import MainWindow
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])
HOY = date.today()


def ts(dia, h=8, m=0, s=0):
    return int(datetime(dia.year, dia.month, dia.day, h, m, s).timestamp())


def rango(dias=8):
    return ts(HOY - timedelta(days=dias)), ts(HOY)


def sembrar(repo, dias=8, con_ecg=True):
    for k in range(dias, 0, -1):
        d = HOY - timedelta(days=k)
        for i in range(30):
            repo.guardar_medicion(60 + (i % 7) + (8 if k < 3 else 0), datetime.fromtimestamp(ts(d, 7) + i * 10),
                                  uid=f"{d}-{i}", rpm=14 + i % 3, nivel_actividad=0)
        for j in range(hrv.UmbralesHrv.min_ventanas):
            repo.guardar_hrv(hrv.ResultadoHrv(ts(d, 7, j), 45.0, 62.0, 60))
        if k < 3:
            repo.guardar_marcador(ts(d, 9), "Mal descanso")
    if con_ecg:
        d = HOY - timedelta(days=1)
        repo.guardar_ecg_segundos([ecg.SegundoEcg(ts(d, 7) + i, 1500 + i % 9, 1700 - i % 5) for i in range(200)])
    repo.guardar_actividad("a1", ts(HOY - timedelta(days=2), 18), ts(HOY - timedelta(days=2), 19), "carrera")
    ServicioObservaciones(repo, reloj=lambda: ts(HOY, 23)).actualizar_todo()


class Base(unittest.TestCase):
    def setUp(self):
        self.repo = RepositorioHistorial(":memory:", usuario_id=1)
        self.dir = tempfile.mkdtemp()
        self.ruta = os.path.join(self.dir, "informe.pdf")

    def generar(self, **kw):
        d, h = rango()
        pdf.generar_informe_pdf(self.ruta, self.repo, d, h, pdf.PerfilInforme(nombre="Ana", **kw))
        with open(self.ruta, "rb") as f:
            return f.read()


class TestGeneracion(Base):

    def test_pdf_valido_con_datos_completos(self):
        sembrar(self.repo)
        datos = self.generar(correo="ana@correo.com", edad=30, sexo="Mujer", fc_max=185, fc_max_configurada=True)
        self.assertTrue(datos.startswith(b"%PDF-"))
        self.assertGreater(len(datos), 5000)
        self.assertIn(b"%%EOF", datos[-64:])

    def test_pagina_extra_cuando_hay_muchas_observaciones(self):
        sembrar(self.repo, dias=40)
        datos = self.generar()
        self.assertGreaterEqual(datos.count(b"/Type /Page\n") + datos.count(b"/Type /Page "), 2)

    def test_contenido_con_datos_incluye_secciones(self):
        """Sin extractor de texto: se comprueba lo que el generador decide imprimir."""
        sembrar(self.repo)
        d, h = rango()
        impresos = []
        original = pdf._Pagina.texto
        with patch.object(pdf._Pagina, "texto",
                          lambda self, t, *a, **k: (impresos.append(t), original(self, t, *a, **k))[1]):
            pdf.generar_informe_pdf(self.ruta, self.repo, d, h, pdf.PerfilInforme(nombre="Ana", edad=30))
        todo = "\n".join(impresos)
        for esperado in ("Informe Biométrico VitaBand", "banda pectoral", "Estadísticas del periodo",
                         "Frecuencia cardíaca", "Frecuencia respiratoria", "Recorte ampliado del ECG",
                         "Observaciones automáticas", "Contexto: «Mal descanso»", "Marcadores de contexto"):
            self.assertIn(esperado, todo)
        self.assertNotIn("No hay ECG guardado", todo)
        self.assertNotIn("No hay observaciones generadas", todo)

    def test_perfil_no_registrado_se_dice_asi(self):
        impresos = []
        d, h = rango()
        with patch.object(pdf._Pagina, "tabla", lambda self, filas: impresos.extend(filas)):
            pdf.generar_informe_pdf(self.ruta, self.repo, d, h, pdf.PerfilInforme(nombre="Ana"))
        tabla = dict(impresos)
        self.assertEqual(tabla["Edad"], "no registrada")
        self.assertEqual(tabla["Sexo"], "no registrado")
        self.assertIn("referencia", tabla["FC máx."])
        self.assertEqual(tabla["Registros periódicos"], "0")

    def test_estadisticas_con_valores_correctos(self):
        sembrar(self.repo)
        impresos = []
        d, h = rango()
        with patch.object(pdf._Pagina, "tabla", lambda self, filas: impresos.extend(filas)):
            pdf.generar_informe_pdf(self.ruta, self.repo, d, h)
        t = dict(impresos)
        self.assertEqual(t["Registros periódicos"], str(len(self.repo.mediciones_rango(d, h, "periodico"))))
        self.assertGreater(int(t["Registros periódicos"]), 100)
        self.assertEqual(t["Sesiones de actividad"], "1")
        self.assertIn("45 ms", t["Último HRV (RMSSD)"])

    def test_rango_invalido(self):
        with self.assertRaises(ValueError):
            pdf.generar_informe_pdf(self.ruta, self.repo, 100, 100)


class TestVacio(Base):

    def test_sin_ningun_dato(self):
        datos = self.generar()
        self.assertTrue(datos.startswith(b"%PDF-"))
        self.assertGreater(len(datos), 1000)

    def test_mensajes_informativos_sin_ecg_ni_observaciones(self):
        impresos = []
        original = pdf._Pagina.texto
        d, h = rango()
        with patch.object(pdf._Pagina, "texto",
                          lambda self, t, *a, **k: (impresos.append(t), original(self, t, *a, **k))[1]):
            pdf.generar_informe_pdf(self.ruta, self.repo, d, h)
        todo = "\n".join(impresos)
        self.assertIn("No hay mediciones periódicas", todo)
        self.assertIn("No hay ECG guardado", todo)
        self.assertIn("No hay observaciones generadas", todo)

    def test_datos_pero_sin_ecg(self):
        sembrar(self.repo, con_ecg=False)
        self.assertTrue(self.generar().startswith(b"%PDF-"))

    def test_sin_respiracion_ni_temperatura(self):
        for i in range(20):
            self.repo.guardar_medicion(70, datetime.fromtimestamp(ts(HOY - timedelta(days=1)) + i * 10),
                                       uid=f"x{i}", nivel_actividad=0)
        self.assertTrue(self.generar().startswith(b"%PDF-"))

    def test_rango_de_un_dia_y_valores_constantes(self):
        d = HOY - timedelta(days=1)
        for i in range(20):
            self.repo.guardar_medicion(70, datetime.fromtimestamp(ts(d) + i * 10), uid=f"c{i}", rpm=15, nivel_actividad=0)
        pdf.generar_informe_pdf(self.ruta, self.repo, ts(d, 0), ts(d, 0) + 86400)
        self.assertTrue(open(self.ruta, "rb").read().startswith(b"%PDF-"))

    def test_escala_de_ejes(self):
        self.assertEqual(pdf._escala(5, 5)[0] <= 5 <= pdf._escala(5, 5)[-1], True)
        t = pdf._escala(60, 142)
        self.assertLessEqual(t[0], 60)
        self.assertGreaterEqual(t[-1], 142)


class TestUI(unittest.TestCase):

    def setUp(self):
        self.repo = RepositorioHistorial(":memory:", usuario_id=1)
        sembrar(self.repo)
        self.vm = VitaBandViewModel(MagicMock(), repositorio=self.repo)
        self.v = MainWindow(self.vm, "Ana")
        self.v.vista_historial.selector.establecer_rango(HOY - timedelta(days=8), HOY - timedelta(days=1))
        self.ruta = os.path.join(tempfile.mkdtemp(), "informe.pdf")

    def tearDown(self):
        self.v.close()
        self.vm.cerrar()

    def test_el_boton_esta_junto_al_csv(self):
        self.assertEqual(self.v.btn_exportar_pdf.text(), "Exportar informe PDF")
        textos = [a.text() for a in self.v.menu_cuenta.actions()]                # ahora vive en «Cuenta y datos ▾»
        self.assertIn("Exportar informe PDF", textos)
        self.assertLess(textos.index("Exportar informe PDF"), textos.index("Exportar historial (CSV)"))

    def test_boton_genera_el_pdf_y_confirma(self):
        with patch("ui.main_window.QFileDialog.getSaveFileName", return_value=(self.ruta, "")) as dlg, \
             patch("ui.animations.show_toast") as info:
            self.v.btn_exportar_pdf.click()
        self.assertIn("*.pdf", dlg.call_args.args[3])
        self.assertTrue(open(self.ruta, "rb").read().startswith(b"%PDF-"))
        info.assert_called_once()

    def test_anade_la_extension_si_falta(self):
        base = self.ruta[:-4]
        with patch("ui.main_window.QFileDialog.getSaveFileName", return_value=(base, "")), \
             patch("ui.main_window.QMessageBox.information"):
            self.v.btn_exportar_pdf.click()
        self.assertTrue(os.path.exists(base + ".pdf"))

    def test_cancelar_no_escribe_nada(self):
        with patch("ui.main_window.QFileDialog.getSaveFileName", return_value=("", "")), \
             patch("ui.animations.show_toast") as info:
            self.v.btn_exportar_pdf.click()
        info.assert_not_called()
        self.assertFalse(os.path.exists(self.ruta))

    def test_error_al_escribir_avisa_sin_lanzar(self):
        ruta_mala = os.path.join(self.ruta, "no", "existe.pdf")
        with patch("ui.main_window.QFileDialog.getSaveFileName", return_value=(ruta_mala, "")), \
             patch("ui.main_window.QMessageBox.warning") as aviso, \
             patch("ui.animations.show_toast") as info:
            self.v.btn_exportar_pdf.click()
        aviso.assert_called_once()
        info.assert_not_called()


if __name__ == "__main__":
    unittest.main()
