"""Todo lo que existe mientras hay un usuario con la sesión abierta.

Se crea al iniciar sesión y se libera por completo al cerrarla: conexión MQTT,
ViewModel, repositorio del usuario y ventana. Así, el siguiente usuario (o el
mismo tras volver a autenticarse) parte de cero y no hereda datos ni conexiones.
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import QApplication

from services.mqtt_client import MqttVitaBandService
from services.repositorio_historial import RepositorioHistorial
from services.servicio_auth import Sesion
from ui.main_window import MainWindow
from viewmodel.vitaband_vm import VitaBandViewModel

logger = logging.getLogger(__name__)


class SesionActiva:

    def __init__(self, app: QApplication, config: dict, sesion: Sesion, ruta_bd: str):
        self._app = app
        self.sesion = sesion
        self.volver_al_login = False
        self._liberada = False

        self.mqtt = MqttVitaBandService(
            broker_host=config["mqtt"]["broker_host"],
            broker_port=config["mqtt"]["broker_port"],
            device_id=config["mqtt"]["device_id"],
        )

        # RF-03: el repositorio queda atado al usuario autenticado
        self.repositorio = RepositorioHistorial(ruta_bd, usuario_id=sesion.usuario_id)

        self.vm = VitaBandViewModel(
            mqtt_service=self.mqtt,
            ventana_segundos=config["monitorizacion"]["ventana_segundos"],
            repositorio=self.repositorio,
        )
        self.mqtt.vincular_viewmodel(self.vm)

        self.ventana = MainWindow(view_model=self.vm, nombre_usuario=sesion.nombre)
        self.ventana.cerrar_sesion_solicitada.connect(self._cerrar_sesion)
        self.ventana.ventana_cerrada.connect(self._app.quit)

    def mostrar(self) -> None:
        self.ventana.show()

    def _cerrar_sesion(self) -> None:
        self.volver_al_login = True
        self.ventana.close()  # dispara ventana_cerrada -> app.quit()

    def liberar(self) -> None:
        """Corta MQTT y cierra la base de datos. Seguro de llamar más de una vez."""
        if self._liberada:
            return
        self._liberada = True

        try:
            self.mqtt.cerrar_conexion()
        except Exception:
            logger.exception("Error cerrando MQTT al liberar la sesión")
        try:
            self.vm.cerrar()
        except Exception:
            logger.exception("Error cerrando el ViewModel al liberar la sesión")
        self.ventana.deleteLater()
