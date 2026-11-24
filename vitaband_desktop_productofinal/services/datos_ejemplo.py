"""Datos de EJEMPLO (sintéticos) para ver todas las gráficas y el contexto del Coach sin banda real.

Genera ~12 semanas de entrenamientos con carga creciente, una semana de descarga, fatiga reciente,
un registro periódico de la última semana, HRV en reposo, ventanas R-R (Poincaré), ECG en forma de
envolvente, RPE y disciplina. Todo es ficticio: no representa a ninguna persona.

Es idempotente: los ``uid`` son deterministas (prefijo ``ejemplo-``), así que cargarlo dos veces
no duplica nada. Se importa con el mismo camino que el móvil (``importar_paquete``).
"""

from __future__ import annotations

import json
import math
import random
import time
from datetime import datetime, timedelta
from typing import Optional

from domain.paquete_sync import parsear_paquete
from services.repositorio_historial import RepositorioHistorial

PREFIJO = "ejemplo"
SEMANAS = 12
_TIPOS = {  # tipo -> (disciplina, FC media esfuerzo suave, FC media esfuerzo duro)
    "carrera": ("Carrera", 138, 164),
    "bicicleta": ("Rodillo/Ciclismo", 125, 150),
    "caminata rápida": ("Caminata", 100, 118),
}


def _plan_actividades(ahora: int, rng: random.Random) -> list[dict]:
    """Calendario de sesiones: 3-4 por semana, rampa de carga y semanas de descarga (5.ª y 10.ª)."""
    hoy = datetime.fromtimestamp(ahora).replace(hour=0, minute=0, second=0, microsecond=0)
    acts = []
    for dia in range(SEMANAS * 7, 0, -1):                       # del pasado hacia ayer
        fecha = hoy - timedelta(days=dia)
        semana = (SEMANAS * 7 - dia) // 7                       # 0 = la más antigua
        descarga = semana in (4, 9)
        if fecha.weekday() == 1:
            tipo, base = "carrera", 32
        elif fecha.weekday() == 3:
            tipo, base = "bicicleta", 40
        elif fecha.weekday() == 5:
            tipo, base = "carrera", 45
        elif fecha.weekday() == 6 and semana % 2 == 0:
            tipo, base = "caminata rápida", 50
        else:
            continue
        minutos = int((base + semana * 1.8) * (0.6 if descarga else 1.0)) + rng.randint(-3, 3)
        duro = (not descarga) and (fecha.weekday() in (1, 5)) and semana >= 5
        if dia in (1, 2):                                       # fatiga reciente: dos sesiones duras seguidas
            tipo, minutos, duro = "carrera", 52 + rng.randint(0, 6), True
        ini = int(fecha.replace(hour=rng.choice((7, 8, 18, 19)), minute=rng.choice((0, 15, 30))).timestamp())
        acts.append({"uid": f"{PREFIJO}-act-{dia}", "inicio": ini, "fin": ini + minutos * 60,
                     "tipo": tipo, "duro": duro, "rpe": 8 if duro else rng.choice((4, 5, 6))})
    return acts


def _bpm_actividad(act: dict, ts: int, rng: random.Random) -> float:
    _, suave, duro = _TIPOS[act["tipo"]]
    objetivo = duro if act["duro"] else suave
    dur = act["fin"] - act["inicio"]
    u = (ts - act["inicio"]) / dur
    calentar = min(1.0, (ts - act["inicio"]) / 480)             # 8 min de entrada en calor
    enfriar = min(1.0, (act["fin"] - ts) / 240)                 # 4 min de vuelta a la calma
    nivel = 95 + (objetivo - 95) * calentar * (0.35 + 0.65 * enfriar)
    deriva = 6 * u                                              # deriva cardíaca
    return round(max(70, min(185, nivel + deriva + 4 * math.sin(ts / 55) + rng.gauss(0, 1.6))), 1)


def _bloque_ecg(t0: int, t1: int, rng: random.Random) -> dict:
    n = t1 - t0
    return {"ts_inicio": t0, "paso_s": 1,
            "minimos": [int(1250 + rng.gauss(0, 35)) for _ in range(n)],
            "maximos": [int(2050 + rng.gauss(0, 55)) for _ in range(n)]}


def construir_paquete(usuario: str, ahora_ts: Optional[int] = None, semilla: int = 7) -> dict:
    ahora = int(ahora_ts if ahora_ts is not None else time.time())
    rng = random.Random(semilla)
    acts = _plan_actividades(ahora, rng)

    mediciones = []
    for a in acts:
        for ts in range(a["inicio"], a["fin"], 10):
            mediciones.append({"uid": f"{a['uid']}-{ts}", "ts": ts, "bpm": _bpm_actividad(a, ts, rng),
                               "rpm": round(rng.uniform(22, 32), 1), "temp": round(rng.uniform(36.4, 37.2), 2),
                               "actividad": 2, "etiqueta": "ACTIVIDAD", "actividad_uid": a["uid"]})
    en_actividad = lambda ts: any(a["inicio"] <= ts <= a["fin"] for a in acts[-12:])
    for ts in range(ahora - 7 * 86400, ahora, 60):             # registro periódico de la última semana
        if en_actividad(ts):
            continue
        h = datetime.fromtimestamp(ts).hour + datetime.fromtimestamp(ts).minute / 60
        mediciones.append({"uid": f"{PREFIJO}-per-{ts}", "ts": ts,
                           "bpm": round(64 + 7 * math.sin(2 * math.pi * (h - 10) / 24) + rng.gauss(0, 1.8), 1),
                           "rpm": round(min(max(rng.gauss(14, 1.2), 10), 18), 1),
                           "temp": round(min(max(36.4 + 0.25 * math.sin(2 * math.pi * (h - 16) / 24)
                                                 + rng.gauss(0, .05), 35.6), 37.2), 2), "actividad": 0})
    mediciones.sort(key=lambda m: m["ts"])
    ecg = [_bloque_ecg(a["inicio"], a["fin"], rng) for a in acts[-3:]] + [_bloque_ecg(ahora - 600, ahora, rng)]
    return {"version": 1, "usuario": usuario, "generado": datetime.fromtimestamp(ahora).strftime("%Y-%m-%dT%H:%M:%S"),
            "actividades": [{k: a[k] for k in ("uid", "inicio", "fin", "tipo")} for a in acts],
            "mediciones": mediciones, "ecg": ecg, "_plan": acts}


def _rr_ventana(fc: float, rmssd_obj: float, rng: random.Random) -> list[float]:
    """60 s de intervalos R-R con arritmia sinusal respiratoria (forma de elipse en Poincaré)."""
    rr, t, out = 60000 / fc, 0.0, []
    while t < 60000:
        v = rr + (rmssd_obj * 0.9) * math.sin(2 * math.pi * t / 4200) + rng.gauss(0, rmssd_obj * 0.35)
        out.append(round(v, 1)); t += v
    return out


def cargar(repo: RepositorioHistorial, ahora_ts: Optional[int] = None, usuario: str = "ejemplo@vitaband.local") -> dict:
    """Importa el conjunto de ejemplo en el historial del usuario de ``repo``. Devuelve un resumen."""
    ahora = int(ahora_ts if ahora_ts is not None else time.time())
    datos = construir_paquete(usuario, ahora)
    plan = datos.pop("_plan")
    paquete = parsear_paquete(json.dumps(datos).encode("utf-8"), ahora)
    res = repo.importar_paquete(paquete)

    rng = random.Random(11)
    ids = {a.uid: a.id for a in repo.actividades_rango(ahora - SEMANAS * 8 * 86400, ahora + 86400)}
    for a in plan:                                              # RPE y disciplina de cada sesión
        sid = ids.get(a["uid"])
        if sid is not None:
            repo.guardar_nota_sesion(sid, a["rpe"], "Sesión de ejemplo")
            repo.guardar_disciplina(sid, _TIPOS[a["tipo"]][0])
    if repo.perfil() is None:                                   # no pisa un perfil que ya exista
        repo.guardar_perfil(34, "Hombre", 72.0, 150)

    from domain import hrv                                      # HRV y R-R en reposo (con bajada reciente)
    for d in range(30, 0, -1):
        ts = int(datetime.fromtimestamp(ahora - d * 86400).replace(hour=7, minute=30, second=0).timestamp())
        rmssd = 52 - (10 if d <= 2 else 0) + rng.gauss(0, 3)
        repo.guardar_hrv(hrv.ResultadoHrv(ts, round(rmssd, 1), round(60 + rng.gauss(0, 1.5), 1), 60))
        if d <= 7:
            for k in range(2):
                repo.guardar_rr(ts + k * 3600, _rr_ventana(61, max(rmssd, 25), rng))
    for k in range(72):                                         # últimas 24 h, una ventana cada 20 min
        repo.guardar_rr(ahora - 60 * (20 * k + 5), _rr_ventana(64, 38, rng))
    return {"actividades": res.actividades_nuevas, "mediciones": res.mediciones_nuevas}
