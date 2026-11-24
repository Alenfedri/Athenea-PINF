"""Aprovisionamiento OPCIONAL del motor IA local (Ollama + Qwen) del Coach IA.

Nada se descarga ni se instala sin consentimiento explícito: ``comprobar()`` solo mira (CHECK_ONLY) y, si falta algo,
devuelve CONSENT_REQUIRED. ``instalar()`` solo se llama tras el clic del usuario en «Sí, instalar modelo elegido».
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

from services import coach_ia

CHECK_ONLY, READY, CONSENT_REQUIRED, INSTALLING, OFFLINE, ERROR = (
    "CHECK_ONLY", "READY", "CONSENT_REQUIRED", "INSTALLING", "OFFLINE", "ERROR")
COACH_MODEL_NAME = MODELO_COACH = "vitaband-coach"
COACH_PROMPT_VERSION = "v5.0"
COACH_PARAMETROS = {"temperature": 0.35, "top_p": 0.85, "repeat_penalty": 1.12, "num_ctx": 8192}
CLAVE_VERSION_META = "coach_prompt_version"
CREATE_NO_WINDOW = 0x08000000          # Windows: sin ventana de consola al arrancar ollama serve
RAM_LIGERO_MAX_GB = 12.0
DISCO_COMPLETO_MIN_GB = 15.0
MARGEN_DISCO_GB = 1.0
ESPERA_ARRANQUE_S = 20.0


class ErrorProvision(RuntimeError):
    pass


@dataclass(frozen=True)
class OpcionModelo:
    model_id: str
    nombre: str
    tamano_gb: float
    etiqueta_peso: str

    def texto(self, recomendada: bool = False) -> str:
        return f"{self.nombre} · {self.etiqueta_peso}" + (" (Recomendado)" if recomendada else "")


LIGERA = OpcionModelo("qwen2.5:1.5b", "Qwen 2.5 Ligero (1.5B)", 1.0, "1,0 GB")
COMPLETA = OpcionModelo("qwen2.5", "Qwen 2.5 Completo (7B)", 4.7, "4,7 GB")
CATALOGO = (LIGERA, COMPLETA)


@dataclass(frozen=True)
class Capacidad:
    ram_gb: Optional[float]
    disco_libre_gb: Optional[float]
    ruta: str = ""


def ruta_modelos() -> str:
    """Carpeta de modelos de Ollama (OLLAMA_MODELS) o, si no existe, el perfil del usuario."""
    r = os.environ.get("OLLAMA_MODELS")
    if r:
        return r
    return os.path.join(os.path.expanduser("~"), ".ollama")


def _disco_libre_gb(ruta: str) -> Optional[float]:
    p = ruta
    while p and not os.path.exists(p):                        # sube hasta una ruta existente (la carpeta puede no existir aún)
        padre = os.path.dirname(p)
        if padre == p:
            break
        p = padre
    try:
        return shutil.disk_usage(p or os.path.expanduser("~")).free / 1024 ** 3
    except OSError:
        return None


def detectar_capacidad_equipo(ruta: Optional[str] = None,
                              ram: Callable[[], Optional[float]] = coach_ia.ram_total_gb,
                              disco: Callable[[str], Optional[float]] = _disco_libre_gb) -> Capacidad:
    """RAM física total (ctypes en Windows, sysconf/proc en Unix) y disco libre donde Ollama guarda los modelos."""
    ruta = ruta or ruta_modelos()
    r = ram()
    if r is None:
        try:
            with open("/proc/meminfo") as f:
                r = int(f.readline().split()[1]) / 1024 ** 2
        except (OSError, ValueError, IndexError):
            r = None
    return Capacidad(r, disco(ruta), ruta)


def recomendada(cap: Capacidad) -> OpcionModelo:
    """Ligera si RAM ≤ 12 GB o disco < 15 GB (o si no se puede saber); completa solo en equipos holgados."""
    if cap.ram_gb is None or cap.disco_libre_gb is None:
        return LIGERA
    if cap.ram_gb <= RAM_LIGERO_MAX_GB or cap.disco_libre_gb < DISCO_COMPLETO_MIN_GB:
        return LIGERA
    return COMPLETA


def opciones(cap: Capacidad) -> list[tuple[OpcionModelo, str, bool]]:
    """[(opción, texto del desplegable, es_recomendada)] — la etiqueta «(Recomendado)» solo aparece en una."""
    rec = recomendada(cap)
    return [(o, o.texto(o is rec), o is rec) for o in CATALOGO]


# --------------------------------------------------------------- Comprobación pasiva (sin descargas)

def _urlopen(*a, **k):
    return urllib.request.urlopen(*a, **k)


def _flags_sin_ventana() -> dict:
    return {"creationflags": CREATE_NO_WINDOW} if sys.platform.startswith("win") else {}


def binario_ollama() -> Optional[str]:
    return shutil.which("ollama")


def arrancar_si_instalado(base: str = coach_ia.OLLAMA_URL) -> bool:
    """Arranca ``ollama serve`` solo si el binario ya existe en el equipo y el servidor no responde. Nunca instala."""
    if os.environ.get("PYTEST_CURRENT_TEST"):                 # los tests no lanzan procesos reales
        return False
    if coach_ia.modelos_ollama(base) is not None:
        return True
    exe = binario_ollama()
    if not exe:
        return False
    try:
        subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, **_flags_sin_ventana())
    except OSError:
        return False
    return _esperar_servidor(base, 8.0)


def _esperar_servidor(base: str, limite_s: float, dormir: Callable[[float], None] = time.sleep) -> bool:
    fin = time.monotonic() + limite_s
    while time.monotonic() < fin:
        if coach_ia.modelos_ollama(base) is not None:
            return True
        dormir(0.5)
    return False


def preparar_coach(base: str = coach_ia.OLLAMA_URL, version_guardada: Optional[str] = None) -> bool:
    """Crea o actualiza «vitaband-coach» (POST /api/create, sin descargar pesos) si no existe o si cambió
    COACH_PROMPT_VERSION respecto a la guardada en app_meta. Devuelve True si lo ha creado/actualizado."""
    modelos = coach_ia.modelos_ollama(base)
    if not modelos:
        return False
    existe = coach_ia._buscar(modelos, MODELO_COACH)
    if existe and version_guardada == COACH_PROMPT_VERSION:
        return False
    origen = None
    for o in (COMPLETA, LIGERA):
        origen = next((m for m in modelos if m.lower() in (o.model_id, o.model_id + ":latest")), None)
        if origen:
            break
    origen = origen or existe                                   # sin Qwen suelto: se rehace desde el propio vitaband-coach
    if not origen:
        return False
    try:
        crear_coach(origen, base)
        return True
    except Exception:
        return False


def comprobar(base: str = coach_ia.OLLAMA_URL, arrancar: bool = True, version_guardada: Optional[str] = None) -> tuple[str, coach_ia.Motor]:
    """CHECK_ONLY: (estado, motor). READY si ya hay motor; CONSENT_REQUIRED si falta Ollama o un modelo Qwen."""
    if arrancar:
        arrancar_si_instalado(base)
        preparar_coach(base, version_guardada)
    motor = coach_ia.detectar_motor(base)
    if motor.tipo == "ollama":
        return READY, motor
    return CONSENT_REQUIRED, coach_ia.MOTOR_OFFLINE


# --------------------------------------------------------------- Instalación (solo tras consentimiento)

def instalar_ollama() -> None:
    """Instala Ollama con el gestor de paquetes de cada sistema; lanza ErrorProvision si falla."""
    if sys.platform.startswith("win"):
        orden = ["winget", "install", "-e", "--id", "Ollama.Ollama", "--silent",
                 "--accept-package-agreements", "--accept-source-agreements"]
    elif sys.platform == "darwin":
        orden = ["brew", "install", "ollama"]
    else:
        orden = ["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"]
    try:
        r = subprocess.run(orden, capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.SubprocessError) as e:
        raise ErrorProvision(f"No se pudo instalar Ollama: {e}")
    if r.returncode != 0:
        raise ErrorProvision("La instalación de Ollama falló. Instálalo manualmente desde ollama.com.")


def _post_lineas(url: str, cuerpo: dict, timeout: float = 600):
    peticion = urllib.request.Request(url, data=json.dumps(cuerpo).encode("utf-8"),
                                      headers={"Content-Type": "application/json"}, method="POST")
    with _urlopen(peticion, timeout=timeout) as r:
        for linea in r:
            linea = linea.strip()
            if linea:
                yield json.loads(linea.decode("utf-8"))


def descargar_modelo(model_id: str, progreso: Callable[[int, str], None], base: str = coach_ia.OLLAMA_URL) -> None:
    """``POST /api/pull`` con progreso en %; solo el modelo indicado."""
    ultimo = -1
    for ev in _post_lineas(f"{base}/api/pull", {"model": model_id, "stream": True}):
        if ev.get("error"):
            raise ErrorProvision(str(ev["error"]))
        total, hecho = ev.get("total"), ev.get("completed")
        if total and hecho is not None:
            pct = max(0, min(100, int(100 * hecho / total)))
            if pct != ultimo:
                ultimo = pct
                progreso(pct, f"Descargando {model_id}… {pct} %")
        elif ev.get("status"):
            progreso(max(ultimo, 0), str(ev["status"]))
    progreso(100, "Descarga completada")


def crear_coach(model_id: str, base: str = coach_ia.OLLAMA_URL) -> None:
    """``POST /api/create``: fabrica «vitaband-coach» a partir del modelo elegido con el prompt de sistema del Coach."""
    from services import contexto_coach                       # prompt maestro con los dos niveles
    cuerpo = {"model": MODELO_COACH, "from": model_id,
              "system": f"[VITABAND_COACH {COACH_PROMPT_VERSION}]\n{contexto_coach.PROMPT_MAESTRO}",
              "parameters": dict(COACH_PARAMETROS), "stream": True}
    for ev in _post_lineas(f"{base}/api/create", cuerpo):
        if ev.get("error"):
            raise ErrorProvision(str(ev["error"]))


def instalar(model_id: str, progreso: Callable[[int, str], None], base: str = coach_ia.OLLAMA_URL,
             capacidad: Optional[Capacidad] = None, instalador: Callable[[], None] = instalar_ollama,
             esperar: Callable[[str, float], bool] = _esperar_servidor) -> coach_ia.Motor:
    """Instala Ollama si falta, descarga ÚNICAMENTE ``model_id`` y crea vitaband-coach. Devuelve el motor resultante."""
    opcion = next((o for o in CATALOGO if o.model_id == model_id), None)
    if opcion is None:
        raise ErrorProvision(f"Modelo no permitido: {model_id}")
    cap = capacidad or detectar_capacidad_equipo()
    if cap.disco_libre_gb is not None and cap.disco_libre_gb < opcion.tamano_gb + MARGEN_DISCO_GB:
        raise ErrorProvision(f"Espacio insuficiente: hacen falta {opcion.etiqueta_peso} y hay {cap.disco_libre_gb:.1f} GB libres.")
    if coach_ia.modelos_ollama(base) is None:
        if not binario_ollama():
            progreso(0, "Instalando Ollama…")
            instalador()
        exe = binario_ollama()
        if exe:
            try:
                subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 stdin=subprocess.DEVNULL, **_flags_sin_ventana())
            except OSError:
                pass
        if not esperar(base, ESPERA_ARRANQUE_S):
            raise ErrorProvision("Ollama no responde en localhost:11434. Ábrelo y vuelve a intentarlo.")
    descargar_modelo(model_id, progreso, base)
    progreso(100, f"Creando {MODELO_COACH}…")
    crear_coach(model_id, base)
    return coach_ia.Motor("ollama", MODELO_COACH)
