import json
import logging
import sys

from PySide6.QtWidgets import QApplication

from services.mqtt_client import MqttVitaBandService
from services.repositorio_historial import RepositorioHistorial
from ui.main_window import MainWindow
from viewmodel.vitaband_vm import VitaBandViewModel


def main() -> int:

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Cargar configuración
    with open("settings.json", "r", encoding="utf-8") as archivo:
        config = json.load(archivo)

    app = QApplication(sys.argv)

    # Inicializar servicio MQTT
    mqtt_service = MqttVitaBandService(
        broker_host=config["mqtt"]["broker_host"],
        broker_port=config["mqtt"]["broker_port"],
        device_id=config["mqtt"]["device_id"]
    )

    # Inicializar repositorio local del historial (media de BPM cada 10 s)
    ruta_bd = config.get("persistencia", {}).get(
        "ruta_bd", "vitaband_historial.db"
    )
    repositorio = RepositorioHistorial(ruta_bd)

    # Inicializar ViewModel
    view_model = VitaBandViewModel(
        mqtt_service=mqtt_service,
        ventana_segundos=config["monitorizacion"]["ventana_segundos"],
        repositorio=repositorio,
    )

    # Vincular MQTT con ViewModel
    mqtt_service.vincular_viewmodel(view_model)

    # Inicializar ventana
    window = MainWindow(view_model=view_model)
    window.show()

    # Al salir: primero se cierra MQTT (deja de llegar telemetría) y después
    # la base de datos
    app.aboutToQuit.connect(mqtt_service.cerrar_conexion)
    app.aboutToQuit.connect(view_model.cerrar)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
