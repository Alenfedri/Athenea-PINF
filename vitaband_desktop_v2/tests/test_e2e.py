"""Flujo completo, con cuenta real y SesionActiva:
paquete demo -> sincronizar -> historial/actividades/ECG -> observaciones -> CSV -> borrados -> cuenta."""

import csv
import os
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from services import totp
from services.repositorio_cuentas import RepositorioCuentas
from services.repositorio_historial import TABLAS_DE_USUARIO
from services.servicio_auth import ServicioAuth
from tools import generar_paquete_demo as demo
from ui.sesion_activa import SesionActiva

_app = QApplication.instance() or QApplication([])
EMAIL, PASSWORD = "ana@correo.com", "Clave-Segura-123"


class TestFlujoCompleto(unittest.TestCase):

    def test_flujo_completo(self):
        with tempfile.TemporaryDirectory() as d, patch("ui.sesion_activa.MqttVitaBandService"):
            ruta, carpeta = os.path.join(d, "t.db"), os.path.join(d, "intercambio")
            cuentas = RepositorioCuentas(ruta)
            auth = ServicioAuth(cuentas)
            auth.registrar("Ana", EMAIL, PASSWORD, PASSWORD)
            sesion = auth.verificar_mfa(totp.codigo_actual(auth.iniciar_sesion(EMAIL, PASSWORD).secreto))
            demo.main(["--usuario", EMAIL, "--salida", carpeta, "--dias", "2", "--actividades", "2"])
            config = {"mqtt": {"broker_host": "localhost", "broker_port": 1883, "device_id": "x"},
                      "monitorizacion": {"ventana_segundos": 6},
                      "intercambio": {"carpeta": carpeta, "intervalo_comprobacion_s": 0},
                      "observaciones": {"intervalo_min": 0}}
            a = SesionActiva(_app, config, sesion, ruta, auth=auth)
            try:
                # 1-2. Arranque: sincroniza el paquete y genera observaciones
                a.mostrar()
                _app.processEvents()
                r = a.resultado_arranque
                self.assertEqual(r.errores, ())
                self.assertEqual(r.sync.importados, 1)
                vm = a.vm
                self.assertEqual(vm.state.syncSincronizados, 1)

                # 3. Consultas
                desde, hasta = vm.rango_disponible()
                serie = vm.serie_historica("bpm", desde, hasta + 1, "auto")
                self.assertGreater(serie.estadisticas.cantidad, 100)
                acts = vm.actividades(desde, hasta + 1)
                self.assertEqual(len(acts), 2)
                det = vm.detalle_actividad(acts[0].actividad.id if hasattr(acts[0], "actividad") else acts[0].id)
                self.assertIsNotNone(det)
                ini, fin = det.actividad.inicio_ts, det.actividad.fin_ts + 1      # el ECG demo cuelga de las actividades
                self.assertTrue(vm.ecg_historico(ini, fin, 300).tiene_datos)

                # 4. Observaciones, siempre con descargo
                obs = vm.observaciones(desde, hasta + 1)
                self.assertGreaterEqual(len(obs), 1)

                # 5. CSV
                csv_ruta = os.path.join(d, "h.csv")
                filas = vm.exportar_csv(csv_ruta)
                with open(csv_ruta, encoding="utf-8-sig", newline="") as f:
                    self.assertEqual(len(list(csv.reader(f, delimiter=";"))) - 1, filas)
                self.assertGreater(filas, 100)

                # 6. Borrar una medición periódica
                antes = a.repositorio.contar_mediciones()
                m = a.repositorio.mediciones_rango(desde, hasta + 1, "periodico")[0]
                self.assertEqual(vm.borrar_mediciones_periodicas([m.id]), 1)
                self.assertEqual(a.repositorio.contar_mediciones(), antes - 1)

                # 7. Borrar la cuenta
                with patch("ui.sesion_activa.QMessageBox"):
                    a.ventana.eliminar_cuenta_solicitada.emit(PASSWORD)
                self.assertTrue(a.volver_al_login)
                a.liberar()
                con = sqlite3.connect(ruta)
                try:
                    self.assertEqual(con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0], 0)
                    for t in TABLAS_DE_USUARIO:
                        self.assertEqual(con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0], 0, t)
                finally:
                    con.close()
            finally:
                a.liberar()
                cuentas.cerrar()


if __name__ == "__main__":
    unittest.main()
