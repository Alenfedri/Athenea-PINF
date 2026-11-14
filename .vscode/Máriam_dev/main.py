import sys
import json

from PySide6.QtWidgets import QApplication

from services.mqtt_client import MqttVitaBandService
from ui.main_window import MainWindow
from viewmodel.vitaband_vm import VitaBandViewModel


def main() -> int:

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

    # Inicializar ViewModel
    view_model = VitaBandViewModel(
        mqtt_service=mqtt_service,
        ventana_segundos=config["monitorizacion"]["ventana_segundos"]
    )

    # Vincular MQTT con ViewModel
    mqtt_service.vincular_viewmodel(view_model)

    # Inicializar ventana
    window = MainWindow(view_model=view_model)
    window.show()

    # Cerrar MQTT al salir
    app.aboutToQuit.connect(mqtt_service.cerrar_conexion)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
