"""Paquete de intercambio móvil -> escritorio (RF-18, RF-20).

El móvil exporta un archivo JSON con este formato (versión 1) en la carpeta de
intercambio y el escritorio lo importa. Ver docs/contrato_sincronizacion.md.

La validación es estricta y de todo o nada: si algo no cumple el formato, el
paquete entero se rechaza y no se importa nada (así no se guardan datos a medias
ni alterados, RF-20).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Optional

from domain.interprete_biometrico import BPM_MAX_VALIDO, BPM_MIN_VALIDO
from domain.modelos import (
    ETIQUETA_ACTIVIDAD,
    ETIQUETA_PERIODICO,
    ETIQUETAS,
    NIVELES_VALIDOS,
)
from domain.validacion_cuentas import normalizar_email

VERSION_SOPORTADA = 1

TS_MINIMO = 946684800            # 2000-01-01
MAX_MEDICIONES = 200_000
MAX_ACTIVIDADES = 5_000
MAX_BLOQUES_ECG = 5_000
MAX_SEGUNDOS_ECG_BLOQUE = 3_600
MAX_ERRORES = 15


class PaqueteInvalido(Exception):
    def __init__(self, errores: list[str]):
        super().__init__("; ".join(errores))
        self.errores = errores


@dataclass(frozen=True)
class MedicionImportada:
    uid: str
    ts: int
    bpm: float
    rpm: Optional[float]
    temp_c: Optional[float]
    nivel_actividad: Optional[int]
    etiqueta: str
    actividad_uid: Optional[str]


@dataclass(frozen=True)
class ActividadImportada:
    uid: str
    inicio_ts: int
    fin_ts: int
    tipo: Optional[str]


@dataclass(frozen=True)
class BloqueEcgImportado:
    ts_inicio: int
    minimos: tuple[int, ...]
    maximos: tuple[int, ...]


@dataclass(frozen=True)
class PaqueteSync:
    version: int
    usuario: str                                   # correo normalizado del propietario
    generado: Optional[str] = None
    mediciones: tuple[MedicionImportada, ...] = field(default_factory=tuple)
    actividades: tuple[ActividadImportada, ...] = field(default_factory=tuple)
    ecg: tuple[BloqueEcgImportado, ...] = field(default_factory=tuple)


class _Errores:
    def __init__(self) -> None:
        self.lista: list[str] = []

    def add(self, texto: str) -> None:
        if len(self.lista) < MAX_ERRORES:
            self.lista.append(texto)

    def __bool__(self) -> bool:
        return bool(self.lista)


def _entero(v: Any) -> Optional[int]:
    """Acepta enteros (y floats sin decimales); rechaza bool, texto y NaN."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and math.isfinite(v) and v == int(v):
        return int(v)
    return None


def _real(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if math.isfinite(v) else None


def _texto_id(v: Any) -> Optional[str]:
    if isinstance(v, str) and 1 <= len(v.strip()) <= 64:
        return v.strip()
    return None


def parsear_paquete(datos: bytes, ahora_ts: int) -> PaqueteSync:
    """Valida y convierte un paquete. Lanza PaqueteInvalido con la lista de problemas."""
    err = _Errores()

    try:
        crudo = json.loads(datos.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise PaqueteInvalido(["El archivo no es un JSON válido en UTF-8."])

    if not isinstance(crudo, dict):
        raise PaqueteInvalido(["El paquete debe ser un objeto JSON."])

    if crudo.get("version") != VERSION_SOPORTADA:
        raise PaqueteInvalido([f"Versión de paquete no soportada (se esperaba {VERSION_SOPORTADA})."])

    usuario = crudo.get("usuario")
    if not isinstance(usuario, str) or "@" not in usuario:
        raise PaqueteInvalido(["Falta el campo «usuario» (correo del propietario)."])

    generado = crudo.get("generado")
    if generado is not None and not isinstance(generado, str):
        err.add("«generado» debe ser texto.")
        generado = None

    limite_ts = ahora_ts + 86400

    def ts_valido(v: Any, donde: str) -> Optional[int]:
        t = _entero(v)
        if t is None or not (TS_MINIMO <= t <= limite_ts):
            err.add(f"{donde}: marca de tiempo no válida.")
            return None
        return t

    # ---------------------------------------------------- actividades
    actividades: list[ActividadImportada] = []
    uids_actividad: set[str] = set()
    lista_act = crudo.get("actividades", [])
    if not isinstance(lista_act, list) or len(lista_act) > MAX_ACTIVIDADES:
        err.add("«actividades» debe ser una lista (máximo %d)." % MAX_ACTIVIDADES)
        lista_act = []
    for i, a in enumerate(lista_act):
        donde = f"actividades[{i}]"
        if not isinstance(a, dict):
            err.add(f"{donde}: debe ser un objeto.")
            continue
        uid = _texto_id(a.get("uid"))
        ini = ts_valido(a.get("inicio"), donde + ".inicio")
        fin = ts_valido(a.get("fin"), donde + ".fin")
        tipo = a.get("tipo")
        if uid is None:
            err.add(f"{donde}: «uid» obligatorio (1-64 caracteres).")
        if ini is not None and fin is not None and fin < ini:
            err.add(f"{donde}: «fin» es anterior a «inicio».")
        if tipo is not None and not (isinstance(tipo, str) and len(tipo) <= 40):
            err.add(f"{donde}: «tipo» debe ser texto de hasta 40 caracteres.")
            tipo = None
        if uid is not None and uid in uids_actividad:
            err.add(f"{donde}: uid repetido dentro del paquete.")
        if uid is not None and ini is not None and fin is not None and fin >= ini:
            uids_actividad.add(uid)
            actividades.append(ActividadImportada(uid, ini, fin, tipo.strip() if tipo else None))

    # ---------------------------------------------------- mediciones
    mediciones: list[MedicionImportada] = []
    uids_med: set[str] = set()
    lista_med = crudo.get("mediciones", [])
    if not isinstance(lista_med, list) or len(lista_med) > MAX_MEDICIONES:
        err.add("«mediciones» debe ser una lista (máximo %d)." % MAX_MEDICIONES)
        lista_med = []
    for i, m in enumerate(lista_med):
        if err and len(err.lista) >= MAX_ERRORES:
            break
        donde = f"mediciones[{i}]"
        if not isinstance(m, dict):
            err.add(f"{donde}: debe ser un objeto.")
            continue

        uid = _texto_id(m.get("uid"))
        ts = ts_valido(m.get("ts"), donde + ".ts")
        bpm = _real(m.get("bpm"))
        rpm = _real(m.get("rpm")) if m.get("rpm") is not None else None
        temp = _real(m.get("temp")) if m.get("temp") is not None else None
        nivel = _entero(m.get("actividad")) if m.get("actividad") is not None else None
        act_uid = m.get("actividad_uid")
        etiqueta = m.get("etiqueta")

        if uid is None:
            err.add(f"{donde}: «uid» obligatorio (1-64 caracteres).")
        elif uid in uids_med:
            err.add(f"{donde}: uid repetido dentro del paquete.")
        if bpm is None or not (BPM_MIN_VALIDO <= bpm <= BPM_MAX_VALIDO):
            err.add(f"{donde}: «bpm» fuera de rango ({BPM_MIN_VALIDO:.0f}-{BPM_MAX_VALIDO:.0f}).")
        if m.get("rpm") is not None and (rpm is None or not (0 <= rpm <= 100)):
            err.add(f"{donde}: «rpm» fuera de rango (0-100).")
        if m.get("temp") is not None and (temp is None or not (20 <= temp <= 45)):
            err.add(f"{donde}: «temp» fuera de rango (20-45).")
        if m.get("actividad") is not None and nivel not in NIVELES_VALIDOS:
            err.add(f"{donde}: «actividad» debe ser 0, 1, 2 o 255.")

        if act_uid is not None:
            act_uid = _texto_id(act_uid)
            if act_uid is None:
                err.add(f"{donde}: «actividad_uid» no válido.")
        if etiqueta is None:
            etiqueta = ETIQUETA_ACTIVIDAD if act_uid else ETIQUETA_PERIODICO
        elif etiqueta not in ETIQUETAS:
            err.add(f"{donde}: «etiqueta» debe ser una de {', '.join(ETIQUETAS)}.")
        elif etiqueta != ETIQUETA_PERIODICO and not act_uid:
            err.add(f"{donde}: una medición {etiqueta} necesita «actividad_uid».")
        elif etiqueta == ETIQUETA_PERIODICO and act_uid:
            err.add(f"{donde}: una medición PERIODICO no puede llevar «actividad_uid».")

        if act_uid and act_uid not in uids_actividad:
            # Puede referirse a una actividad ya importada antes; lo comprueba el repositorio.
            pass

        if uid is not None and ts is not None and bpm is not None and not err:
            uids_med.add(uid)
            mediciones.append(
                MedicionImportada(uid, ts, bpm, rpm, temp, nivel, etiqueta, act_uid)
            )

    # ---------------------------------------------------- ECG
    bloques: list[BloqueEcgImportado] = []
    lista_ecg = crudo.get("ecg", [])
    if not isinstance(lista_ecg, list) or len(lista_ecg) > MAX_BLOQUES_ECG:
        err.add("«ecg» debe ser una lista (máximo %d bloques)." % MAX_BLOQUES_ECG)
        lista_ecg = []
    for i, b in enumerate(lista_ecg):
        donde = f"ecg[{i}]"
        if not isinstance(b, dict):
            err.add(f"{donde}: debe ser un objeto.")
            continue
        ini = ts_valido(b.get("ts_inicio"), donde + ".ts_inicio")
        mins, maxs = b.get("minimos"), b.get("maximos")
        if b.get("paso_s", 1) != 1:
            err.add(f"{donde}: solo se admite «paso_s» = 1.")
        if not (isinstance(mins, list) and isinstance(maxs, list) and len(mins) == len(maxs)
                and 1 <= len(mins) <= MAX_SEGUNDOS_ECG_BLOQUE):
            err.add(f"{donde}: «minimos» y «maximos» deben ser listas de igual longitud (1-{MAX_SEGUNDOS_ECG_BLOQUE}).")
            continue
        enteros_min = [_entero(v) for v in mins]
        enteros_max = [_entero(v) for v in maxs]
        if any(v is None or not (-32767 <= v <= 32767) for v in enteros_min + enteros_max):
            err.add(f"{donde}: los valores deben ser enteros de 16 bits.")
            continue
        if any(a > c for a, c in zip(enteros_min, enteros_max)):
            err.add(f"{donde}: algún mínimo es mayor que su máximo.")
            continue
        if ini is not None:
            bloques.append(BloqueEcgImportado(ini, tuple(enteros_min), tuple(enteros_max)))

    if err:
        raise PaqueteInvalido(err.lista)

    return PaqueteSync(
        version=VERSION_SOPORTADA,
        usuario=normalizar_email(usuario),
        generado=generado,
        mediciones=tuple(mediciones),
        actividades=tuple(actividades),
        ecg=tuple(bloques),
    )


def propietario_de(datos: bytes) -> Optional[str]:
    """Correo del propietario de un paquete sin validar el resto (para repartir archivos)."""
    try:
        crudo = json.loads(datos.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return None
    if isinstance(crudo, dict) and isinstance(crudo.get("usuario"), str):
        return normalizar_email(crudo["usuario"])
    return None
