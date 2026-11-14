import json
import logging
import sys

from PySide6.QtWidgets import QApplication, QDialog

from services.repositorio_cuentas import RepositorioCuentas
from services.servicio_auth import ServicioAuth
from ui.login_dialog import LoginDialog
from ui.sesion_activa import SesionActiva


def main() -> int:

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Cargar configuración
    with open("settings.json", "r", encoding="utf-8") as archivo:
        config = json.load(archivo)

    ruta_bd = config.get("persistencia", {}).get("ruta_bd", "vitaband_historial.db")

    app = QApplication(sys.argv)
    # La salida se decide aquí, no por el cierre de la última ventana
    app.setQuitOnLastWindowClosed(False)

    repo_cuentas = RepositorioCuentas(ruta_bd)
    auth = ServicioAuth(repo_cuentas)

    try:
        while True:

            # 1. Acceso: sin sesión autenticada no se abre nada (RF-01, RF-42)
            dialogo = LoginDialog(auth)
            if dialogo.exec() != QDialog.DialogCode.Accepted:
                break

            # 2. Sesión: MQTT, ViewModel y ventana atados a este usuario (RF-03)
            activa = SesionActiva(app, config, auth.requerir_sesion(), ruta_bd)
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
