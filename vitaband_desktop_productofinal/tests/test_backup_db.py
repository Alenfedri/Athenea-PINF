"""Copia de seguridad (.zip) y restauración de la base de datos."""

import json
import os
import shutil
import sqlite3
import tempfile
import unittest
import zipfile
from datetime import datetime
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from services import backup_db
from services.repositorio_cuentas import RepositorioCuentas
from services.repositorio_historial import RepositorioHistorial
from ui.main_window import MainWindow
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])


def crear_bd(carpeta, nombre="a.db", n=5, usuarios=1):
    ruta = os.path.join(carpeta, nombre)
    cuentas = RepositorioCuentas(ruta)
    ids = [cuentas.crear(f"u{i}@correo.com", f"U{i}", "x" * 12, "y" * 32) for i in range(usuarios)]
    repo = RepositorioHistorial(ruta, usuario_id=ids[-1])
    for i in range(n):
        repo.guardar_medicion(70 + i, datetime(2026, 11, 10, 8, 0, i), uid=f"m{i}")
    return ruta, repo, ids[-1]


def contar(ruta, tabla="mediciones"):
    con = sqlite3.connect(ruta)
    try:
        return con.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
    finally:
        con.close()


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.ruta, self.repo, self.uid = crear_bd(self.dir)
        self.zip = os.path.join(self.dir, "copia.zip")

    def tearDown(self):
        self.repo.cerrar()


class TestExportar(Base):

    def test_zip_con_bd_integra_y_manifest(self):
        backup_db.exportar_backup(self.repo.conexion, self.zip, ahora=datetime(2026, 11, 18, 12, 0))
        with zipfile.ZipFile(self.zip) as z:
            self.assertEqual(sorted(z.namelist()), ["manifest.json", "vitaband.db"])
            manifest = json.loads(z.read("manifest.json"))
            z.extract("vitaband.db", self.dir)
        self.assertEqual(manifest["version_backup"], 1)
        self.assertEqual(manifest["fecha"], "2026-11-18T12:00:00")
        copia = os.path.join(self.dir, "vitaband.db")
        con = sqlite3.connect(copia)
        self.assertEqual(con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        con.close()
        self.assertEqual(contar(copia), 5)
        self.assertEqual(contar(copia, "usuarios"), 1)

    def test_en_caliente_no_altera_el_original_ni_deja_temporales(self):
        antes = contar(self.ruta)
        backup_db.exportar_backup(self.repo.conexion, self.zip)
        self.repo.guardar_medicion(99, datetime(2026, 11, 11), uid="nuevo")             # la conexión sigue usable
        self.assertEqual(contar(self.ruta), antes + 1)
        self.assertEqual([f for f in os.listdir(self.dir) if f.startswith("vitaband_bk_")], [])

    def test_ruta_de_la_bd(self):
        self.assertEqual(os.path.realpath(backup_db.ruta_de(self.repo.conexion)), os.path.realpath(self.ruta))
        self.assertEqual(backup_db.ruta_de(sqlite3.connect(":memory:")), "")


class TestRestaurar(Base):

    def test_restaura_el_estado_anterior_y_deja_bak(self):
        backup_db.exportar_backup(self.repo.conexion, self.zip)
        for i in range(5, 9):
            self.repo.guardar_medicion(80, datetime(2026, 11, 12, 8, 0, i), uid=f"extra{i}")
        self.assertEqual(contar(self.ruta), 9)
        bak = backup_db.restaurar_backup(self.repo.conexion, self.zip, self.uid)
        self.assertEqual(contar(self.ruta), 5)
        self.assertEqual(bak, self.ruta + ".bak")
        self.assertEqual(contar(bak), 9)                                        # el .bak es la BD de antes de restaurar
        self.assertEqual(len(self.repo.todas_las_mediciones()), 5)              # la conexión abierta ve lo restaurado

    def _zip_manual(self, destino, bd=None, manifest=None, extra=None):
        with zipfile.ZipFile(destino, "w") as z:
            if bd is not None:
                z.writestr("vitaband.db", bd)
            if manifest is not None:
                z.writestr("manifest.json", manifest)
            for n, c in (extra or {}).items():
                z.writestr(n, c)
        return destino

    def assert_rechaza_sin_cambios(self, ruta_zip, mensaje=None):
        antes = contar(self.ruta)
        with self.assertRaises(backup_db.BackupInvalido) as cm:
            backup_db.restaurar_backup(self.repo.conexion, ruta_zip, self.uid)
        if mensaje:
            self.assertIn(mensaje, str(cm.exception))
        self.assertEqual(contar(self.ruta), antes)
        self.assertFalse(os.path.exists(self.ruta + ".bak"))

    def test_rechaza_archivos_invalidos_sin_tocar_nada(self):
        basura = os.path.join(self.dir, "x.zip")
        open(basura, "wb").write(b"no soy un zip")
        self.assert_rechaza_sin_cambios(basura, "no es un .zip")
        self.assert_rechaza_sin_cambios(self._zip_manual(os.path.join(self.dir, "a.zip"), bd=b"x"), "faltan")
        self.assert_rechaza_sin_cambios(
            self._zip_manual(os.path.join(self.dir, "b.zip"), bd=b"esto no es sqlite", manifest='{"version_backup": 1}'),
            "SQLite")
        self.assert_rechaza_sin_cambios(
            self._zip_manual(os.path.join(self.dir, "c.zip"), bd=b"", manifest="{roto"), "manifest")
        self.assert_rechaza_sin_cambios(
            self._zip_manual(os.path.join(self.dir, "d.zip"), bd=b"", manifest='{"version_backup": 99}'), "versión")

    def test_rechaza_una_bd_ajena_sin_tablas_de_vitaband(self):
        ajena = os.path.join(self.dir, "otra.db")
        con = sqlite3.connect(ajena); con.execute("CREATE TABLE t (a)"); con.commit(); con.close()
        z = self._zip_manual(os.path.join(self.dir, "e.zip"), bd=open(ajena, "rb").read(),
                             manifest='{"version_backup": 1}')
        self.assert_rechaza_sin_cambios(z, "tablas")

    def test_rechaza_una_bd_corrupta(self):
        backup_db.exportar_backup(self.repo.conexion, self.zip)
        with zipfile.ZipFile(self.zip) as z:
            bd = bytearray(z.read("vitaband.db"))
            manifest = z.read("manifest.json")
        for i in range(4096, min(len(bd), 4096 * 3)):
            bd[i] = 0xFF                                                         # destroza páginas de datos
        roto = self._zip_manual(os.path.join(self.dir, "f.zip"), bd=bytes(bd), manifest=manifest)
        self.assert_rechaza_sin_cambios(roto)

    def test_rechaza_una_copia_sin_la_cuenta_actual(self):
        otra, repo2, _ = crear_bd(self.dir, "b.db", n=2, usuarios=1)
        backup_db.exportar_backup(repo2.conexion, self.zip)
        repo2.cerrar()
        ruta3, repo3, uid3 = crear_bd(self.dir, "c.db", n=3, usuarios=2)          # usuario actual = id 2
        try:
            with self.assertRaises(backup_db.BackupInvalido) as cm:
                backup_db.restaurar_backup(repo3.conexion, self.zip, uid3)
            self.assertIn("tu cuenta", str(cm.exception))
            self.assertEqual(contar(ruta3), 3)
        finally:
            repo3.cerrar()


class TestVmYUi(Base):

    def setUp(self):
        super().setUp()
        self.vm = VitaBandViewModel(MagicMock(), repositorio=self.repo)
        self.ventana = MainWindow(self.vm, "Ana")

    def tearDown(self):
        self.ventana.close()
        super().tearDown()

    def test_botones_visibles(self):
        self.assertEqual(self.ventana.btn_backup.text(), "Exportar Backup (.zip)")
        self.assertEqual(self.ventana.btn_restaurar.text(), "Restaurar Backup (.zip)")

    def test_exportar_desde_la_ui(self):
        with patch("ui.main_window.QFileDialog.getSaveFileName", return_value=(self.zip, "")), \
             patch("ui.main_window.QMessageBox.information") as info:
            self.ventana.btn_backup.click()
        self.assertTrue(zipfile.is_zipfile(self.zip))
        self.assertIn("cuentas", info.call_args.args[2])                          # avisa de que incluye las cuentas

    def test_restaurar_desde_la_ui_recarga_y_confirma(self):
        backup_db.exportar_backup(self.repo.conexion, self.zip)
        for i in range(10, 13):
            self.repo.guardar_medicion(90, datetime(2026, 11, 12, 9, 0, i), uid=f"z{i}")
        señales = []
        self.vm.historial_actualizado.connect(lambda: señales.append(1))
        with patch("ui.main_window.QFileDialog.getOpenFileName", return_value=(self.zip, "")), \
             patch("ui.main_window.confirmar", return_value=True) as conf, \
             patch("ui.main_window.QMessageBox.information") as info:
            self.ventana.btn_restaurar.click()
        self.assertIn("TODA la base de datos", conf.call_args.args[2])
        self.assertEqual(contar(self.ruta), 5)
        self.assertTrue(señales)
        self.assertIn(".bak", info.call_args.args[2])

    def test_cancelar_o_rechazar_no_cambia_nada(self):
        backup_db.exportar_backup(self.repo.conexion, self.zip)
        self.repo.guardar_medicion(90, datetime(2026, 11, 12, 9), uid="solo")
        with patch("ui.main_window.QFileDialog.getOpenFileName", return_value=(self.zip, "")), \
             patch("ui.main_window.confirmar", return_value=False):
            self.ventana.btn_restaurar.click()
        self.assertEqual(contar(self.ruta), 6)
        basura = os.path.join(self.dir, "mal.zip")
        open(basura, "wb").write(b"zzz")
        with patch("ui.main_window.QFileDialog.getOpenFileName", return_value=(basura, "")), \
             patch("ui.main_window.confirmar", return_value=True), \
             patch("ui.main_window.QMessageBox.warning") as aviso:
            self.ventana.btn_restaurar.click()
        aviso.assert_called_once()
        self.assertEqual(contar(self.ruta), 6)

    def test_restaurar_una_copia_de_version_anterior_recrea_las_tablas_nuevas(self):
        backup_db.exportar_backup(self.repo.conexion, self.zip)
        vieja = os.path.join(self.dir, "vieja.zip")
        with zipfile.ZipFile(self.zip) as z:
            z.extract("vitaband.db", self.dir)
            manifest = z.read("manifest.json")
        con = sqlite3.connect(os.path.join(self.dir, "vitaband.db"))
        con.execute("DROP TABLE marcadores_contexto"); con.commit(); con.close()
        with zipfile.ZipFile(vieja, "w") as z:
            z.write(os.path.join(self.dir, "vitaband.db"), "vitaband.db")
            z.writestr("manifest.json", manifest)
        self.vm.restaurar_backup(vieja)
        self.repo.guardar_marcador(100, "Café")                                  # la tabla se volvió a crear
        self.assertEqual(self.repo.marcadores_rango(0, 200), [(100, "Café")])


if __name__ == "__main__":
    unittest.main()
