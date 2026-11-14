# Contrato MQTT de VitaBand

`{id}` = `device_id` de `settings.json` (por defecto `vitaband-01`).

| Tópico | Sentido | QoS | Retain | Payload |
|---|---|---|---|---|
| `vitaband/{id}/telemetry` | pasarela → app | 0 | no | JSON, ver abajo |
| `vitaband/{id}/status` | pasarela → app | **1** | **sí** | `{"state": "CALIBRATING" \| "READY" \| "OFFLINE"}` |
| `vitaband/{id}/control` | app → pasarela | 1 | no | `"0"` (ECG filtrada) o `"1"` (ECG cruda) |

## Telemetría

```json
{"ecg": 1603.0, "bpm": 72.0, "rpm": 15.0, "temp": 36.52, "activity": 0, "alert": 255}
```

Cada ~10 s la pasarela añade la media temporal de BPM del paquete ampliado de
12 bytes:

```json
{"ecg": 1603.0, "bpm": 72.0, "rpm": 15.0, "temp": 36.52, "activity": 0, "alert": 255, "media_bpm": 71.4}
```

> Supuesto: el nombre de la clave (`media_bpm`) no está en el código recibido.
> Si la pasarela usa otro, se cambia solo en `CLAVE_MEDIA_BPM`
> (`domain/interprete_biometrico.py`).

## Estados de `/status`

| Estado | Significado | `ConexionEstado` en la app |
|---|---|---|
| `CALIBRATING` | La pulsera está en la ventana inicial de 6 s de respiración | `CALIBRANDO` |
| `READY` | Calibración terminada, datos válidos | `CONECTADO` |
| `OFFLINE` | La pasarela perdió la pulsera o cayó | `ERROR_COMUNICACION` (se vacían ECG y métricas) |

Como el mensaje es *retained*, al suscribirse la app recibe siempre el último
estado conocido. Se acepta también el texto plano (`OFFLINE`) por si el Last
Will se publica sin JSON.

Mientras está en `CALIBRANDO`, la telemetría no cambia el estado a `CONECTADO`:
solo lo hace `READY`. (Si una pasarela antigua no publica `READY`, la app se
quedaría en `CALIBRANDO`.)

## Lado pasarela: Last Will y estado retenido

La pasarela debe registrar el Last Will **antes** de conectar y publicar su
estado siempre con `retain=True`:

```python
import json
import paho.mqtt.client as mqtt

TOPIC = "vitaband/vitaband-01/status"
cliente = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)

# Si la pasarela cae de golpe, el broker publica esto por ella
cliente.will_set(TOPIC, json.dumps({"state": "OFFLINE"}), qos=1, retain=True)
cliente.connect("localhost", 1883, keepalive=30)

def publicar_estado(estado: str) -> None:
    cliente.publish(TOPIC, json.dumps({"state": estado}), qos=1, retain=True)

# Al conectar con la pulsera:   publicar_estado("CALIBRATING")
# Al terminar la calibración:   publicar_estado("READY")
# Si se pierde el BLE:          publicar_estado("OFFLINE")
```

## Reinicio del modo ECG

El firmware vuelve a `modoECG = 0` (filtrada) en cada conexión. La app lo
refleja forzando `modoEcgCrudo = False` en `conectar()`, `desconectar()`,
en cada reconexión (`CONECTANDO`) y en cualquier caída (`OFFLINE`).
