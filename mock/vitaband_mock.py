#!/usr/bin/env python3
"""
VitaBand Mock - emula el firmware del prototipo (XIAO ESP32-C6, PCB v2) y publica por MQTT.

Dependencia:  pip install paho-mqtt   (>= 2.0)
Uso:          python vitaband_mock.py --host localhost
              python vitaband_mock.py --scenario correr          (escenario fijo)
              python vitaband_mock.py --calib-fail-first 1       (1ª calibración fallida)

TOPICS (prefijo vitaband/)
  vitaband/ecg            JSON, QoS0, 10 Hz   lote de 10 muestras ECG a 100 Hz
  vitaband/vitals         JSON, QoS0, 1 Hz    bpm, rpm, temp_c, activity, warning
  vitaband/hr_avg         JSON, QoS1, cada 10 s   media de BPM de los últimos 10 s
  vitaband/status         JSON, QoS1, retained    calibrating | streaming | offline (LWT)
  vitaband/control        <- app: "0" ECG filtrada, "1" ECG cruda
  vitaband/mock/scenario  <- (solo mock) nombre de escenario o "auto"

Valores especiales (igual que en la trama BLE):
  activity: 0 Baja, 1 Media, 2 Intensa, 255 sin clasificar
  warning : 0 niveles bajos en reposo, 1 FC elevada en reposo,
            2 aviso conjunto elevado en reposo, 255 sin aviso
  bpm / rpm = 0.0 hasta detectar 2 latidos / 2 ciclos tras la calibración.
Durante la calibración (6 s) NO se publica ni ecg ni vitals.
"""
import argparse
import json
import math
import random
import time
from collections import deque

import paho.mqtt.client as mqtt

FS = 100
DT = 1.0 / FS
OFFSET_ECG = 1600
CALIB_S = 6.0

BASE = "vitaband"
T_ECG = f"{BASE}/ecg"
T_VITALS = f"{BASE}/vitals"
T_HR_AVG = f"{BASE}/hr_avg"
T_STATUS = f"{BASE}/status"
T_CONTROL = f"{BASE}/control"
T_SCENARIO = f"{BASE}/mock/scenario"

# Objetivos de cada escenario. El estado real se acerca a ellos con una constante
# de tiempo: mov cae casi al instante, FC y FR tardan -> aparece el 255 en recuperación.
SCENARIOS = {
    "reposo":          dict(hr=70,  rr=14, mov=0.2, temp=36.4),
    "caminar":         dict(hr=95,  rr=17, mov=1.5, temp=36.6),
    "correr":          dict(hr=150, rr=28, mov=4.5, temp=37.0, noisy=True),
    "reposo_bajo":     dict(hr=54,  rr=9,  mov=0.2, temp=36.2),
    "reposo_elevado":  dict(hr=110, rr=14, mov=0.2, temp=36.6),  # aviso 1
    "reposo_agitado":  dict(hr=110, rr=22, mov=0.2, temp=36.7),  # aviso 2
    "inclinado":       dict(hr=72,  rr=14, mov=0.3, temp=36.4, freeze_rr=True),
}
AUTO_SEQUENCE = [
    ("reposo", 40), ("caminar", 30), ("correr", 40), ("reposo", 60),
    ("reposo_elevado", 25), ("reposo_agitado", 25), ("reposo", 30),
    ("reposo_bajo", 25), ("inclinado", 20), ("reposo", 20),
]
TAU = dict(hr=10.0, rr=8.0, mov=0.5, temp=120.0)

# (centro, anchura, amplitud ADC) dentro del ciclo [0,1)
PQRST = [(0.16, 0.025, 80), (0.37, 0.008, -110), (0.40, 0.010, 700),
         (0.43, 0.010, -160), (0.65, 0.045, 160)]


def hysteresis(level, v, up1, dn1, up2, dn2):
    """Clasificación 0/1/2 con histéresis, igual que el firmware."""
    if level == 0:
        if v >= up1:
            level = 1
    elif level == 1:
        if v >= up2:
            level = 2
        elif v < dn1:
            level = 0
    elif level == 2 and v < dn2:
        level = 1
    return level


def activity_code(mov, fc, fr):
    return {(0, 1, 1): 0, (1, 1, 1): 1, (2, 2, 2): 2}.get((mov, fc, fr), 255)


def warning_code(mov, fc, fr):
    if mov == 0 and fc == 0 and fr == 0:
        return 0
    if mov == 0 and fc == 2 and fr in (0, 1):
        return 1
    if mov == 0 and fc == 2 and fr == 2:
        return 2
    return 255


class VitaBandSim:
    """Simulador puro (sin MQTT). step() avanza 10 ms y devuelve la muestra ECG."""

    def __init__(self, scenario="reposo"):
        self.set_scenario(scenario)
        self.raw_mode = False
        self.t = 0.0
        # estado fisiológico suavizado
        self.hr, self.rr = 70.0, 14.0
        self.mov, self.temp = 0.2, 36.4
        self.mov_win = deque(maxlen=25)  # media móvil IMU
        # detectores
        self.beat_phase = random.random()
        self.resp_phase = 0.0
        self.last_beat = None
        self.last_cycle = None
        self.bpm = 0.0
        self.rpm = 0.0
        # niveles con histéresis (FC y FR inician en 1)
        self.l_mov, self.l_fc, self.l_fr = 0, 1, 1

    def set_scenario(self, name):
        self.scenario = name
        self.target = SCENARIOS[name]

    def _lag(self, cur, tgt, tau):
        return cur + (tgt - cur) * (DT / tau)

    def step(self):
        self.t += DT
        g = self.target
        self.hr = self._lag(self.hr, g["hr"], TAU["hr"])
        self.rr = self._lag(self.rr, g["rr"], TAU["rr"])
        self.mov = self._lag(self.mov, g["mov"], TAU["mov"])
        self.temp = self._lag(self.temp, g["temp"], TAU["temp"])

        # IMU: |a| con ruido + media móvil de 25 muestras
        self.mov_win.append(abs(self.mov + random.gauss(0, 0.15 + 0.3 * self.mov / 4.5)))
        i_mov = sum(self.mov_win) / len(self.mov_win)

        # --- latidos ---
        hr_inst = self.hr * (1 + 0.03 * math.sin(2 * math.pi * 0.25 * self.t)) + random.gauss(0, 0.6)
        self.beat_phase += max(hr_inst, 1) * DT / 60.0
        if self.beat_phase >= 1.0:
            self.beat_phase -= 1.0
            if self.last_beat is not None:
                itv = self.t - self.last_beat
                if 0.3 <= itv <= 1.2:  # 50-200 BPM
                    self.bpm = 60.0 / itv
            self.last_beat = self.t

        # --- respiración ---
        self.resp_phase += max(self.rr, 1) * DT / 60.0
        if self.resp_phase >= 1.0:
            self.resp_phase -= 1.0
            if not g.get("freeze_rr") and self.last_cycle is not None:
                itv = self.t - self.last_cycle
                if 1.0 <= itv <= 10.0:  # 6-60 RPM
                    self.rpm = 60.0 / itv
            self.last_cycle = self.t

        # --- clasificación (solo con medidas válidas, como el firmware) ---
        self.l_mov = hysteresis(self.l_mov, i_mov, 0.9, 0.5, 3.0, 2.5)
        if self.bpm > 0:
            self.l_fc = hysteresis(self.l_fc, self.bpm, 62, 58, 102, 98)
        if self.rpm > 0:
            self.l_fr = hysteresis(self.l_fr, self.rpm, 13, 11, 19, 17)

        # --- ECG sintético ---
        ecg = sum(a * math.exp(-((self.beat_phase - c) ** 2) / (2 * w * w)) for c, w, a in PQRST)
        noisy = g.get("noisy", False)
        if self.raw_mode:
            wander = 150 * math.sin(2 * math.pi * 0.2 * self.t) + (120 * math.sin(2 * math.pi * 1.7 * self.t) if noisy else 0)
            val = 2000 + wander + ecg + random.gauss(0, 25 if noisy else 10)
            return int(min(4095, max(0, val)))
        val = OFFSET_ECG + ecg + random.gauss(0, 25 if noisy else 6)
        return int(val)

    def vitals(self):
        return {
            "bpm": round(self.bpm, 2),
            "rpm": round(self.rpm, 2),
            "temp_c": round(self.temp + random.gauss(0, 0.02), 2),
            "activity": activity_code(self.l_mov, self.l_fc, self.l_fr),
            "warning": warning_code(self.l_mov, self.l_fc, self.l_fr),
        }


class Mock:
    def __init__(self, args):
        self.args = args
        self.fixed = args.scenario is not None
        self.sim = VitaBandSim(args.scenario or AUTO_SEQUENCE[0][0])
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="vitaband-mock")
        self.client.will_set(T_STATUS, json.dumps({"state": "offline"}), qos=1, retain=True)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    # ---- MQTT ----
    def on_connect(self, client, userdata, flags, reason_code, properties):
        print(f"[mqtt] conectado ({reason_code})")
        client.subscribe([(T_CONTROL, 1), (T_SCENARIO, 1)])

    def on_message(self, client, userdata, msg):
        payload = msg.payload.decode(errors="ignore").strip()
        if msg.topic == T_CONTROL and payload in ("0", "1"):
            self.sim.raw_mode = payload == "1"
            print(f"[control] ECG {'cruda' if self.sim.raw_mode else 'filtrada'}")
        elif msg.topic == T_SCENARIO:
            if payload == "auto":
                self.fixed = False
            elif payload in SCENARIOS:
                self.fixed = True
                self.sim.set_scenario(payload)
                print(f"[mock] escenario fijo: {payload}")

    def pub(self, topic, obj, qos=0, retain=False):
        self.client.publish(topic, json.dumps(obj, separators=(",", ":")), qos=qos, retain=retain)

    # ---- calibración respiratoria (6 s, se repite si falla) ----
    def calibrate(self):
        fails = self.args.calib_fail_first
        attempt = 0
        while True:
            attempt += 1
            start = time.monotonic()
            while (el := time.monotonic() - start) < CALIB_S:
                self.pub(T_STATUS, {"state": "calibrating", "attempt": attempt,
                                    "remaining_s": round(CALIB_S - el, 1)}, qos=1, retain=True)
                time.sleep(1.0)
            if attempt <= fails:
                print(f"[calib] intento {attempt}: amplitud insuficiente, reinicio")
                continue
            break
        self.pub(T_STATUS, {"state": "streaming"}, qos=1, retain=True)
        print("[calib] OK, empieza el streaming")

    # ---- bucle principal a 100 Hz ----
    def run(self):
        self.client.connect(self.args.host, self.args.port, keepalive=30)
        self.client.loop_start()
        self.calibrate()

        buf, hr_hist = [], deque(maxlen=100)
        n = 0
        seq_i, seq_end = 0, time.monotonic() + AUTO_SEQUENCE[0][1]
        next_t = time.perf_counter()
        try:
            while True:
                if not self.fixed and time.monotonic() >= seq_end:
                    seq_i = (seq_i + 1) % len(AUTO_SEQUENCE)
                    name, dur = AUTO_SEQUENCE[seq_i]
                    self.sim.set_scenario(name)
                    seq_end = time.monotonic() + dur
                    print(f"[mock] escenario: {name} ({dur}s)")

                buf.append(self.sim.step())
                n += 1

                if n % 10 == 0:
                    self.pub(T_ECG, {"ts": int(time.time() * 1000), "fs": FS,
                                     "mode": "raw" if self.sim.raw_mode else "filtered",
                                     "samples": buf})
                    buf = []
                if n % 10 == 5:
                    hr_hist.append(self.sim.bpm)
                if n % 100 == 0:
                    self.pub(T_VITALS, {"ts": int(time.time() * 1000), **self.sim.vitals()})
                if n % 1000 == 0:
                    valid = [b for b in hr_hist if b > 0]
                    if valid:
                        self.pub(T_HR_AVG, {"ts": int(time.time() * 1000),
                                            "bpm_avg": int(round(sum(valid) / len(valid)))}, qos=1)

                next_t += DT
                delay = next_t - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                elif delay < -0.5:  # nos hemos quedado atrás: resincronizar
                    next_t = time.perf_counter()
        except KeyboardInterrupt:
            pass
        finally:
            self.pub(T_STATUS, {"state": "offline"}, qos=1, retain=True)
            self.client.loop_stop()
            self.client.disconnect()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="VitaBand MQTT mock")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--scenario", choices=list(SCENARIOS), default=None,
                    help="escenario fijo (por defecto: ciclo automático)")
    ap.add_argument("--calib-fail-first", type=int, default=0, metavar="N",
                    help="las N primeras calibraciones fallan (reinicio de 6 s)")
    Mock(ap.parse_args()).run()
