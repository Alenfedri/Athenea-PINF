import os
import sys

# Sin consola (--windowed) stdout/stderr son None: las librerías que imprimen romperían en silencio
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import faulthandler
import json
import logging
import traceback
from pathlib import Path

# Registro de cierres nativos (C++) y excepciones sin capturar en crash.log (junto a los datos)
_dir_crash = Path(sys.executable).parent / "datos" if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
try:
    _dir_crash.mkdir(parents=True, exist_ok=True)
    _crash_fh = open(_dir_crash / "crash.log", "a", buffering=1, encoding="utf-8")
    faulthandler.enable(file=_crash_fh, all_threads=True)
except OSError:
    _crash_fh = None


def _excepthook(tipo, valor, tb):
    try:
        if _crash_fh is not None:
            _crash_fh.write("".join(traceback.format_exception(tipo, valor, tb)) + "\n")
    finally:
        sys.__excepthook__(tipo, valor, tb)


sys.excepthook = _excepthook

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from services.ajustes import Ajustes, AjustesInvalidos
from services.repositorio_cuentas import RepositorioCuentas
from services.servicio_auth import ServicioAuth
from ui.login_dialog import LoginDialog
from ui.sesion_activa import SesionActiva
from ui.tema_vitaband import aplicar_tema_global


def get_resource_path(rel_path: str) -> Path:
    """Recurso estático (settings.json, assets, estilos): dentro del paquete congelado o junto al código."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / rel_path


def get_app_data_dir() -> Path:
    """Carpeta persistente y escribible (BD SQLite, exportaciones, intercambio): junto al .exe o al código."""
    if getattr(sys, "frozen", False):
        datos = Path(sys.executable).resolve().parent / "datos"
        datos.mkdir(parents=True, exist_ok=True)
        return datos
    return Path(__file__).resolve().parent


def main() -> int:

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    os.chdir(get_app_data_dir())                        # funciona lance desde donde lance

    # Cargar configuración
    with open(get_resource_path("settings.json"), "r", encoding="utf-8") as archivo:
        config = json.load(archivo)

    ruta_bd = config.get("persistencia", {}).get("ruta_bd", "vitaband_historial.db")

    import pyqtgraph as pg
    pg.setConfigOptions(useOpenGL=False, antialias=False)    # sin OpenGL ni antialias: repintados estables
    app = QApplication(sys.argv)
    aplicar_tema_global(app)
    # La salida se decide aquí, no por el cierre de la última ventana
    app.setQuitOnLastWindowClosed(False)

    # Se validan los ajustes antes del login: un valor erróneo se detecta al arrancar
    try:
        ajustes = Ajustes.desde_config(config)
    except AjustesInvalidos as error:
        logging.error("%s", error)
        QMessageBox.critical(None, "VitaBand: configuración no válida", str(error))
        return 2

    repo_cuentas = RepositorioCuentas(ruta_bd)
    auth = ServicioAuth(repo_cuentas)

    try:
        while True:

            # 1. Acceso: sin sesión autenticada no se abre nada (RF-01, RF-42)
            dialogo = LoginDialog(auth)
            if dialogo.exec() != QDialog.DialogCode.Accepted:
                break

            # 2. Sesión: MQTT, ViewModel y ventana atados a este usuario (RF-03)
            activa = SesionActiva(app, config, auth.requerir_sesion(), ruta_bd, ajustes, auth=auth)
            activa.mostrar()
            app.exec()

            # 3. Cierre: se libera todo y se destruye la sesión (RF-02)
            volver = activa.volver_al_login
            activa.liberar()
            auth.cerrar_sesion()

            if not volver:
                break
    finally:
        auth.cerrar_sesion()
        repo_cuentas.cerrar()

    return 0


if __name__ == "__main__":
    sys.exit(main())
