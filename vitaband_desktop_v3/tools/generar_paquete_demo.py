"""Genera un paquete de sincronización de DEMOSTRACIÓN para probar el escritorio sin el móvil.

Crea un archivo JSON válido (ver docs/contrato_sincronizacion.md) con mediciones
periódicas, una interrupción del registro, actividades con sus mediciones y ECG en
forma de envolvente. Los datos son SINTÉTICOS: sirven para probar la aplicación,
no representan a ninguna persona.

Uso (desde la carpeta del proyecto):
    python tools/generar_paquete_demo.py --usuario tu@correo.com
    python tools/generar_paquete_demo.py --usuario tu@correo.com --dias 7 --actividades 3 --salida intercambio

Es determinista: con los mismos parámetros y ``--semilla`` produce los mismos ``uid``, así
que volver a importarlo no duplica nada (útil para probar la deduplicación).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

if __package__ in (None, ""):                       # ejecución directa: python tools/generar_paquete_demo.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from domain.paquete_sync import PaqueteInvalido, parsear_paquete

INTERVALO_ACTIVIDAD_S = 10
DURACION_HUECO_S = 2 * 3600


def _hora_decimal(ts: int) -> float:
    d = datetime.fromtimestamp(ts)
    return d.hour + d.minute / 60


def _fc_reposo(ts: int, rng: random.Random) -> float:
    # ritmo circadiano suave: más baja de madrugada, más alta por la tarde
    return round(66 + 7 * math.sin(2 * math.pi * (_hora_decimal(ts) - 10) / 24) + rng.gauss(0, 1.8), 1)


def generar_paquete(
    usuario: str,
    dias: int = 3,
    actividades: int = 2,
    intervalo_s: int = 60,
    semilla: int = 1,
    ahora_ts: Optional[int] = None,
    con_hueco: bool = True,
) -> dict:
    """Devuelve el paquete (diccionario listo para ``json.dump``)."""
    if dias < 1 or actividades < 0 or intervalo_s < 10:
        raise ValueError("dias >= 1, actividades >= 0 e intervalo >= 10 s")

    rng = random.Random(semilla)
    ahora = int(ahora_ts if ahora_ts is not None else time.time())
    inicio = ahora - dias * 86400
    prefijo = f"demo{semilla}"

    # --- Actividades repartidas de forma uniforme dentro del periodo
    acts = []
    for k in range(actividades):
        dur = rng.randint(20, 40) * 60
        ini = int(inicio + (k + 1) * dias * 86400 / (actividades + 1) - dur / 2)
        acts.append({"uid": f"{prefijo}-act-{k + 1}", "inicio": ini, "fin": ini + dur,
                     "tipo": rng.choice(["carrera", "bicicleta", "caminata rápida"])})

    def actividad_en(ts: int) -> Optional[str]:
        return next((a["uid"] for a in acts if a["inicio"] <= ts <= a["fin"]), None)

    # --- Mediciones periódicas (con una interrupción simulada del registro)
    hueco = (inicio + int(dias * 86400 * 0.4), inicio + int(dias * 86400 * 0.4) + DURACION_HUECO_S) \
        if con_hueco and dias * 86400 > 3 * DURACION_HUECO_S else None
    mediciones = []
    for ts in range(inicio, ahora, intervalo_s):
        if hueco and hueco[0] <= ts < hueco[1]:
            continue
        act = actividad_en(ts)
        bpm = _fc_reposo(ts, rng) if not act else round(rng.uniform(120, 150), 1)
        m = {
            "uid": f"{prefijo}-per-{ts}", "ts": ts, "bpm": bpm,
            "rpm": round(min(max(rng.gauss(14, 1.2), 10), 18), 1) if not act else round(rng.uniform(22, 30), 1),
            "temp": round(min(max(36.4 + 0.25 * math.sin(2 * math.pi * (_hora_decimal(ts) - 16) / 24)
                                  + rng.gauss(0, 0.05), 35.6), 37.2), 2),
            "actividad": 0 if not act else 2,
        }
        if act:                                    # el registro periódico continúa durante la actividad
            m["etiqueta"], m["actividad_uid"] = "AMBOS", act
        mediciones.append(m)

    # --- Mediciones propias de cada actividad (más frecuentes)
    for a in acts:
        for ts in range(a["inicio"], a["fin"], INTERVALO_ACTIVIDAD_S):
            mediciones.append({
                "uid": f"{a['uid']}-{ts}", "ts": ts,
                "bpm": round(rng.uniform(115, 165), 1), "rpm": round(rng.uniform(22, 32), 1),
                "temp": round(rng.uniform(36.2, 37.0), 2), "actividad": 2,
                "etiqueta": "ACTIVIDAD", "actividad_uid": a["uid"],
            })
    mediciones.sort(key=lambda m: m["ts"])

    # --- ECG: envolvente por segundo durante cada actividad y los últimos 10 minutos
    def bloque(t0: int, t1: int) -> dict:
        n = t1 - t0
        return {
            "ts_inicio": t0, "paso_s": 1,
            "minimos": [int(1250 + rng.gauss(0, 40)) for _ in range(n)],
            "maximos": [int(2050 + rng.gauss(0, 60)) for _ in range(n)],
        }

    ecg = [bloque(a["inicio"], a["fin"]) for a in acts]
    ecg.append(bloque(ahora - 600, ahora))

    return {
        "version": 1,
        "usuario": usuario,
        "generado": datetime.fromtimestamp(ahora).strftime("%Y-%m-%dT%H:%M:%S"),
        "actividades": acts,
        "mediciones": mediciones,
        "ecg": ecg,
    }


def escribir_paquete(paquete: dict, carpeta: str, nombre: Optional[str] = None) -> str:
    """Escribe el paquete en ``carpeta`` de forma atómica (archivo temporal + renombrado).

    Así el escritorio nunca encuentra un archivo a medias. Devuelve la ruta final.
    """
    os.makedirs(carpeta, exist_ok=True)
    if nombre is None:
        slug = re.sub(r"[^a-z0-9]+", "_", paquete["usuario"].lower()).strip("_")
        nombre = f"paquete_demo_{slug}_{paquete['generado'].replace(':', '').replace('-', '')}.json"
    destino = os.path.join(carpeta, nombre)
    temporal = destino + ".tmp"
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump(paquete, f, ensure_ascii=False)
    os.replace(temporal, destino)
    return destino


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Genera un paquete de sincronización de demostración.")
    ap.add_argument("--usuario", required=True, help="correo del usuario propietario (el de la cuenta del escritorio)")
    ap.add_argument("--salida", default="intercambio", help="carpeta de intercambio (por defecto: intercambio)")
    ap.add_argument("--dias", type=int, default=3, help="días de historial periódico (por defecto: 3)")
    ap.add_argument("--actividades", type=int, default=2, help="número de actividades (por defecto: 2)")
    ap.add_argument("--intervalo", type=int, default=60, help="segundos entre mediciones periódicas (mín. 10)")
    ap.add_argument("--semilla", type=int, default=1, help="semilla del generador (mismos datos y uid)")
    ap.add_argument("--sin-huecos", action="store_true", help="no simular una interrupción del registro")
    ap.add_argument("--nombre", help="nombre del archivo (por defecto, uno automático)")
    args = ap.parse_args(argv)

    try:
        paquete = generar_paquete(args.usuario, args.dias, args.actividades, args.intervalo,
                                  args.semilla, con_hueco=not args.sin_huecos)
        # Autocomprobación: el paquete debe pasar la misma validación que usa el escritorio
        parsear_paquete(json.dumps(paquete).encode("utf-8"), int(time.time()))
    except (ValueError, PaqueteInvalido) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    ruta = escribir_paquete(paquete, args.salida, args.nombre)
    print(f"Paquete creado: {ruta}")
    print(f"  {len(paquete['mediciones'])} mediciones, {len(paquete['actividades'])} actividades, "
          f"{sum(len(b['minimos']) for b in paquete['ecg'])} s de ECG")
    print("Ábrelo en el escritorio con «Sincronizar ahora» (la cuenta debe usar el mismo correo).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
