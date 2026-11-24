"""Todo lo que existe mientras hay un usuario con la sesión abierta.

Se crea al iniciar sesión y se libera por completo al cerrarla: conexión MQTT,
ViewModel, repositorio del usuario y ventana. Así, el siguiente usuario (o el
mismo tras volver a autenticarse) parte de cero y no hereda datos ni conexiones.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from services.ajustes import Ajustes
from services.mqtt_client import MqttVitaBandService
from services.repositorio_historial import RepositorioHistorial
from services.servicio_auth import ErrorAuth, Sesion, ServicioAuth
from services.servicio_observaciones import ServicioObservaciones
from services.servicio_sync import ServicioSync
from ui.main_window import MainWindow
from viewmodel.vitaband_vm import ResultadoArranque, VitaBandViewModel

logger = logging.getLogger(__name__)


class SesionActiva:

    def __init__(
        self,
        app: QApplication,
        config: dict,
        sesion: Sesion,
        ruta_bd: str,
        ajustes: Optional[Ajustes] = None,
        auth: Optional[ServicioAuth] = None,
    ):
        self._app = app
        self.sesion = sesion
        self.ajustes = ajustes or Ajustes.desde_config(config)
        self.volver_al_login = False
        self.resultado_arranque: Optional[ResultadoArranque] = None
        self._liberada = False
        self._auth = auth
        self._cuenta_eliminada = False

        self.mqtt = MqttVitaBandService(
            broker_host=config["mqtt"]["broker_host"],
            broker_port=config["mqtt"]["broker_port"],
            device_id=config["mqtt"]["device_id"],
        )

        # RF-03: el repositorio queda atado al usuario autenticado
        self.repositorio = RepositorioHistorial(ruta_bd, usuario_id=sesion.usuario_id)

        # Sincronización por archivos (RF-18, 21, 36) y observaciones (RF-23, 29)
        self._preparar_carpeta_intercambio()
        self.sync = ServicioSync(self.repositorio, self.ajustes.carpeta_intercambio, sesion.email)
        self.observaciones = ServicioObservaciones(self.repositorio, self.ajustes.registro_intervalo_s)

        self.vm = VitaBandViewModel(
            mqtt_service=self.mqtt,
            ventana_segundos=config["monitorizacion"]["ventana_segundos"],
            repositorio=self.repositorio,
            servicio_sync=self.sync,
            servicio_observaciones=self.observaciones,
            intervalo_registro_ms=self.ajustes.registro_intervalo_ms,
            intervalo_sync_ms=self.ajustes.sync_intervalo_ms,
            intervalo_observaciones_ms=self.ajustes.observaciones_intervalo_ms,
            dias_periodico=self.ajustes.periodico_dias,
            dias_actividades=self.ajustes.actividades_dias,
        )
        self.mqtt.vincular_viewmodel(self.vm)

        self.ventana = MainWindow(view_model=self.vm, nombre_usuario=sesion.nombre, correo_usuario=sesion.email)
        self.ventana.cerrar_sesion_solicitada.connect(self._cerrar_sesion)
        self.ventana.eliminar_cuenta_solicitada.connect(self._eliminar_cuenta)
        self.ventana.ventana_cerrada.connect(self._app.quit)

    def _preparar_carpeta_intercambio(self) -> None:
        """Crea la carpeta de intercambio si no existe; si no se puede, la sincronización
        avisa en pantalla pero la aplicación sigue funcionando."""
        carpeta = self.ajustes.carpeta_intercambio
        try:
            os.makedirs(carpeta, exist_ok=True)
        except OSError:
            logger.exception("No se pudo crear la carpeta de intercambio %s", carpeta)
        else:
            logger.info("Carpeta de intercambio: %s", os.path.abspath(carpeta))

    def mostrar(self) -> None:
        self.ventana.show()
        # El arranque (purga, sincronización, observaciones) se hace con la ventana ya
        # visible, para que no parezca colgada mientras se importan paquetes grandes.
        QTimer.singleShot(0, self._arrancar)

    def _arrancar(self) -> None:
        if self._liberada:                      # la sesión se cerró antes de que llegara el aviso
            return
        self.resultado_arranque = self.vm.arrancar()
        r = self.resultado_arranque
        logger.info("Arranque: purga=%s sincronización=%s observaciones=%s",
                    r.purga, r.sync, r.observaciones)
        for error in r.errores:
            logger.warning("Fallo en el arranque (%s); se continúa sin ese paso", error)

    def _cerrar_sesion(self) -> None:
        self.volver_al_login = True
        self.ventana.close()  # dispara ventana_cerrada -> app.quit()

    def _eliminar_cuenta(self, password: str) -> None:
        """RF-39: borra la cuenta y sus datos y vuelve al login."""
        if self._auth is None or self._cuenta_eliminada:
            return
        try:
            self._auth.eliminar_cuenta(password)
        except ErrorAuth as error:
            QMessageBox.warning(self.ventana, "No se pudo eliminar la cuenta", str(error))
            return
        except Exception:
            logger.exception("Error eliminando la cuenta")
            QMessageBox.warning(self.ventana, "No se pudo eliminar la cuenta",
                                "Ocurrió un error inesperado y la cuenta no se eliminó.")
            return

        # Los datos ya no existen: se detiene todo YA, antes de cualquier diálogo (que procesaría
        # los temporizadores y escribiría filas huérfanas).
        self._cuenta_eliminada = True
        try:
            self.vm.cerrar(volcar_ecg=False)
        except Exception:
            logger.exception("Error cerrando el ViewModel tras eliminar la cuenta")
        QMessageBox.information(self.ventana, "Cuenta eliminada",
                                "Tu cuenta y todos sus datos se han eliminado de este equipo.")
        self.volver_al_login = True
        self.ventana.close()

    def liberar(self) -> None:
        """Corta MQTT, vuelca el ECG pendiente y cierra la base de datos (vía ``vm.cerrar``).

        Seguro de llamar más de una vez."""
        if self._liberada:
            return
        self._liberada = True

        try:
            self.mqtt.cerrar_conexion()
        except Exception:
            logger.exception("Error cerrando MQTT al liberar la sesión")
        try:
            self.vm.cerrar(volcar_ecg=not self._cuenta_eliminada)
        except Exception:
            logger.exception("Error cerrando el ViewModel al liberar la sesión")
        self.ventana.deleteLater()
