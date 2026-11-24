"""Coach IA híbrido: Ollama local con selección automática de modelo y respaldo offline.

Lee los datos de la cuenta en solo lectura (SELECT a través de los repositorios) y responde sobre la
banda pectoral VitaBand. Solo stdlib. El contexto se debe recopilar en el hilo principal (SQLite) y
pasarse ya resuelto al hilo que habla con Ollama."""

from __future__ import annotations

import ctypes
import json
import os
import re
import statistics
import unicodedata
import sys
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional, Sequence

from domain.zonas_actividad import analizar_actividad

OLLAMA_URL = "http://localhost:11434"
TIMEOUT_DETECCION_S = 1.5
TIMEOUT_GENERACION_S = 120          # lectura: la carga en frío de qwen2.5 (4,7 GB) puede tardar
TIMEOUT_CONEXION_S = 5
KEEP_ALIVE = "15m"
OPCIONES_OLLAMA = {"num_ctx": 4096, "temperature": 0.65, "top_p": 0.9, "num_predict": 700}


class OllamaDesconectado(Exception):
    """No hay servidor en localhost:11434 (motor caído); distinto de un fallo puntual de generación."""


class ErrorGeneracion(Exception):
    """Ollama está activo pero la generación falló o tardó demasiado; el motor se mantiene."""

    def __init__(self, mensaje: str, parcial: str = ""):
        super().__init__(mensaje)
        self.parcial = parcial
MODELO_GRANDE, MODELO_PEQUENO = "qwen2.5:7b", "qwen2.5:3b"
MODELOS_CAPACES = ("qwen2.5:7b", "llama3.1:8b", "gemma2:9b", "mistral")   # antes que cualquier modelo 1b/3b
RAM_MIN_GRANDE_GB = 12.0
TURNOS_MEMORIA = 10
DIA = 86400
DESCARGO = "Es orientativo y no sustituye a un diagnóstico médico."

PROMPT_SISTEMA = (
    "Eres el Coach VitaBand: fisiólogo del ejercicio y acompañante cercano de una persona que usa una banda pectoral con "
    "ECG. Responde SIEMPRE en español, con naturalidad y criterio humano, adaptando la longitud a lo que se te pide "
    "(una duda rápida o un saludo = 1 o 2 frases; un análisis = profundo, razonando el porqué con las cifras exactas). "
    "Elige cómo responder según estas PRIORIDADES, de mayor a menor: "
    "(1) EMPATÍA: si el usuario cuenta una pérdida (fallecimiento de un familiar), duelo, tristeza profunda o una crisis "
    "emocional, responde con calidez humana y respeto, acompaña y ofrece escucharle sin presionar. PROHIBIDO mencionar "
    "métricas cardíacas, entrenar, respirar o incluir etiquetas <ACTION>. "
    "(2) SEGURIDAD MÉDICA: si refiere síntomas reales (dolor torácico, mareo, falta de aire, síncope o palpitaciones "
    "preocupantes), responde con serenidad, aclara que VitaBand es una herramienta informativa y recomienda una valoración "
    "médica; no diagnostiques. "
    "(3) CONVERSACIÓN GENERAL: si te saluda o habla de temas cotidianos, respóndele de forma cercana, breve y humana, "
    "saludándole por su nombre si lo conoces y preguntándole cómo se siente o en qué puedes ayudarle; PROHIBIDO soltar "
    "métricas, diagnósticos o recomendaciones de entrenamiento si no ha pedido análisis o consejo. "
    "(4) ANÁLISIS FISIOLÓGICO Y DEPORTIVO: solo cuando pregunte por su corazón, fatiga, estrés, sueño o entrenamientos, "
    "usa en silencio los datos del contexto (perfil, HRV, TSB, TRIMP, sesiones recientes, plan) para razonar con rigor, "
    "explicar el porqué y, si es útil, cerrar con una pregunta de seguimiento. "
    "Los datos del contexto son solo de consulta silenciosa: úsalos únicamente cuando vengan al caso y no los recites sin "
    "que se pidan. Nunca inventes un dato; si falta, dilo. No emitas diagnósticos médicos. "
    "ACCIONES: solo en turnos donde el usuario pida o acepte explícitamente un plan, un hábito o un informe médico (nunca "
    "en saludos ni en conversación emocional), añade AL FINAL un bloque <ACTION>{\"type\": \"COHERENCIA_60S\" | "
    "\"PLAN_ZONA2\" | \"REAJUSTAR_SEMANA\"}</ACTION> sin explicarlo en el texto. "
    "Si el usuario ha escrito un hábito real no predefinido (ej. 'siesta', 'ayuno', 'viaje largo', 'fisioterapia', "
    "'altitud'), interprétalo con criterio deportivo. Si aparece una etiqueta inventada, absurda o sin sentido fisiológico "
    "(ej. 'asdf', 'volar', 'teletransportación'), ignórala por completo sin mencionarla ni inventar efectos.")

# Hábitos que el modo offline reconoce: clave → (raíces normalizadas, nota deportiva breve). Todo lo demás se ignora.
HABITOS_CONOCIDOS = {
    "cafe": (("cafe", "cafeina"), "La cafeína tardía puede elevar tu FC en reposo y recortar el sueño profundo."),
    "descanso": (("mal descanso", "descanso", "sueno", "dormi", "insomnio"), "Dormir poco suele bajar la HRV y subir la FC en reposo."),
    "mareo": (("mareo",), "Un mareo recurrente merece consultarlo con un profesional de la salud."),
    "estres": (("estres", "ansiedad", "nervios"), "El estrés sostenido suele reducir la HRV y frenar la recuperación."),
    "siesta": (("siesta",), "Una siesta corta (< 30 min) suele ayudar a recuperar; larga puede alterar el sueño nocturno."),
    "ayuno": (("ayuno",), "Entrenar en ayuno prolongado puede subir la FC y la percepción de esfuerzo."),
    "hidratacion": (("hidrat", "agua", "deshidrat", "sed"), "Una hidratación baja eleva la FC para el mismo esfuerzo."),
    "viaje": (("viaje", "jet lag", "desplazamiento"), "Los viajes largos alteran el sueño y la recuperación los días siguientes."),
    "dolor": (("dolor", "lesion", "molestia", "contractura", "agujetas"), "Con dolor, prioriza descanso y consulta si persiste."),
    "suplemento": (("suplement", "creatina", "proteina", "vitamina", "cafeina extra"), "Los suplementos rara vez cambian la HRV de un día; valora su efecto a medio plazo."),
    "fisioterapia": (("fisio", "masaje", "estiramiento", "foam"), "La fisioterapia o el masaje ayudan a la recuperación muscular."),
    "altitud": (("altitud", "altura", "montana"), "En altitud la FC sube y la HRV baja unos días hasta aclimatarte."),
    "alcohol": (("alcohol", "cerveza", "vino", "resaca"), "El alcohol suele bajar la HRV esa noche y empeorar el descanso."),
    "enfermedad": (("enfermedad", "fiebre", "resfriado", "gripe", "malestar"), "Con fiebre o malestar conviene no entrenar fuerte."),
    "calor_frio": (("sauna", "calor", "frio", "bano"), "El calor o el frío intenso modifican la FC y la HRV temporalmente."),
}


# ------------------------------------------------------------------ Contexto de la cuenta (solo lectura)

@dataclass
class ContextoCoach:
    perfil: dict = field(default_factory=dict)
    hrv_ultimo: Optional[tuple[str, float]] = None        # (fecha, RMSSD ms)
    hrv_reciente: Optional[float] = None                  # media de los últimos 3 días
    hrv_base: Optional[float] = None                      # media de los 27 días anteriores
    recuperacion: Optional[str] = None                    # "buena" | "moderada" | "baja"
    ratio_hrv: Optional[float] = None
    fc_reposo: Optional[float] = None
    ultima: Optional[dict] = None
    etiquetas: list = field(default_factory=list)         # [(etiqueta, veces)] de los últimos 14 días
    habitos: list = field(default_factory=list)           # [(etiqueta, veces, RMSSD 24 h después, % vs base)]
    semana: dict = field(default_factory=dict)
    alerta: Optional[object] = None                     # AlertaPreventiva (escudo preventivo)
    hallazgos: list = field(default_factory=list)       # correlaciones hábito ↔ corazón ya redactadas
    hrr: Optional[object] = None                        # última recuperación postesfuerzo
    calidad: Optional[object] = None                    # calidad del trazado ECG
    reajuste: Optional[object] = None                   # motivo del reajuste «sin culpa»
    fc_max: Optional[float] = None                        # FC máx observada (o Tanaka con la edad) para las zonas

    @property
    def vacio(self) -> bool:
        return self.hrv_ultimo is None and self.ultima is None and not self.etiquetas and self.fc_reposo is None

    def a_texto(self) -> str:
        l = []
        p = self.perfil
        l.append("Perfil: " + (", ".join(x for x in (
            f"{p['edad']} años" if p.get("edad") else "", p.get("sexo") or "",
            f"{p['peso_kg']:.0f} kg" if p.get("peso_kg") else "",
            f"objetivo semanal {p['objetivo_min']} min" if p.get("objetivo_min") else "") if x) or "sin datos"))
        if self.hrv_ultimo:
            l.append(f"Última HRV (RMSSD) en reposo: {self.hrv_ultimo[1]:.0f} ms el {self.hrv_ultimo[0]}.")
        if self.hrv_reciente is not None:
            base = f" frente a {self.hrv_base:.0f} ms de base personal" if self.hrv_base is not None else ""
            l.append(f"RMSSD medio 3 días: {self.hrv_reciente:.0f} ms{base}. Recuperación: "
                     f"{self.recuperacion or 'sin referencia suficiente'}.")
        if self.fc_reposo is not None:
            l.append(f"FC en reposo reciente: {self.fc_reposo:.0f} BPM.")
        u = self.ultima
        if u:
            z = "" if not u.get("zonas") else " Zonas: " + ", ".join(
                f"Z{i + 1} {v:.0f} %" for i, v in enumerate(u["zonas"])) + "."
            l.append(f"Última actividad ({u['fecha']}): {u['duracion_min']:.0f} min, BPM medio "
                     f"{u['bpm_medio']:.0f}, máx {u['bpm_max']:.0f}.{z} Umbral de fatiga: {u['umbral']}.")
        s = self.semana
        if s:
            l.append(f"Últimos 7 días: {s['sesiones']} sesiones, {s['minutos']:.0f} min de actividad.")
        if self.etiquetas:
            l.append("Etiquetas de contexto recientes: " + ", ".join(f"{e} ({n})" for e, n in self.etiquetas) + ".")
        for e, n, r, d in self.habitos:
            l.append(f"Tras «{e}» ({n} veces) el RMSSD medio fue {r:.0f} ms ({d:+.0f} % respecto a su base).")
        return "\n".join(l)


def _media(valores) -> Optional[float]:
    valores = list(valores)
    return statistics.fmean(valores) if valores else None


def recopilar_contexto(repo, perfil, ahora_ts: int) -> ContextoCoach:
    """Lectura solo-SELECT de la cuenta activa. Llamar desde el hilo principal."""
    ctx = ContextoCoach()
    if repo is None:
        return ctx
    ctx.perfil = {"edad": getattr(perfil, "edad", None), "sexo": getattr(perfil, "sexo", None),
                  "peso_kg": getattr(perfil, "peso_kg", None), "objetivo_min": getattr(perfil, "objetivo_semanal_min", None)}
    # HRV / recuperación
    hrvs = repo.hrv_rango(ahora_ts - 30 * DIA, ahora_ts + 1)
    if hrvs:
        ult = max(hrvs, key=lambda h: h.ts)
        ctx.hrv_ultimo = (f"{datetime.fromtimestamp(ult.ts):%d/%m/%Y}", float(ult.rmssd_ms))
    recientes = [h.rmssd_ms for h in hrvs if h.ts >= ahora_ts - 3 * DIA]
    previos = [h.rmssd_ms for h in hrvs if h.ts < ahora_ts - 3 * DIA]
    if len(recientes) >= 3:
        ctx.hrv_reciente = _media(recientes)
        if len(previos) >= 10:
            ctx.hrv_base = _media(previos)
            ctx.ratio_hrv = ctx.hrv_reciente / ctx.hrv_base if ctx.hrv_base else None
            if ctx.ratio_hrv is not None:
                ctx.recuperacion = "buena" if ctx.ratio_hrv >= 0.95 else "moderada" if ctx.ratio_hrv >= 0.80 else "baja"
    # FC en reposo (percentil 5 del pulso en reposo de los últimos 7 días)
    from services.vo2max import fc_reposo
    ctx.fc_reposo = fc_reposo(repo.mediciones_rango(ahora_ts - 7 * DIA, ahora_ts + 1))
    from services.vo2max import fc_max_observada, fc_max_tanaka
    ctx.fc_max = fc_max_observada(repo.mediciones_rango(ahora_ts - 180 * DIA, ahora_ts + 1)) or (
        fc_max_tanaka(perfil.edad) if perfil is not None and getattr(perfil, "edad", None) else None)
    # Actividades
    acts = repo.actividades_rango(ahora_ts - 60 * DIA, ahora_ts + 1)             # más reciente primero
    if acts:
        a = acts[0]
        ms = repo.mediciones_de_actividad(a.id)
        bpms = [m.bpm for m in ms if m.bpm and m.bpm > 0]
        if bpms:
            an = analizar_actividad(ms, a.inicio_ts)
            umbral = (f"a los {an.umbral.umbral.minuto} min ({an.umbral.umbral.bpm:.0f} BPM)" if an.umbral.umbral
                      else (an.umbral.motivo or "no detectado"))
            ctx.ultima = {"fecha": f"{datetime.fromtimestamp(a.inicio_ts):%d/%m/%Y}", "duracion_min": a.duracion_s / 60,
                          "bpm_medio": statistics.fmean(bpms), "bpm_max": max(bpms),
                          "zonas": None if an.zonas is None or an.zonas.total_s <= 0 else list(an.zonas.porcentajes),
                          "umbral": umbral}
    sem = [a for a in acts if a.inicio_ts >= ahora_ts - 7 * DIA]
    ctx.semana = {"sesiones": len(sem), "minutos": sum(a.duracion_s for a in sem) / 60}
    # Etiquetas de contexto y su efecto sobre la HRV de las 24 h siguientes
    marcas = repo.marcadores_rango(ahora_ts - 30 * DIA, ahora_ts + 1)
    cont: dict[str, int] = {}
    for ts, e in marcas:
        if ts >= ahora_ts - 14 * DIA:
            cont[e] = cont.get(e, 0) + 1
    ctx.etiquetas = sorted(cont.items(), key=lambda x: (-x[1], x[0]))[:6]
    base = _media(h.rmssd_ms for h in hrvs)
    por_etiqueta: dict[str, list] = {}
    for ts, e in marcas:
        despues = [h.rmssd_ms for h in hrvs if ts <= h.ts < ts + DIA]
        if despues:
            por_etiqueta.setdefault(e, []).append(statistics.fmean(despues))
    if base:
        for e, vs in sorted(por_etiqueta.items()):
            if len(vs) >= 2:
                r = statistics.fmean(vs)
                ctx.habitos.append((e, len(vs), r, 100.0 * (r / base - 1)))
    try:
        from services import inteligencia_biometrica as ib
        ib.completar_contexto(ctx, repo, ahora_ts)
    except Exception:
        pass
    return ctx


# ------------------------------------------------------------------ Detección de hardware y modelo

def ram_total_gb() -> Optional[float]:
    """RAM total en GB: ctypes en Windows, os.sysconf en Unix; None si no se puede saber."""
    try:
        if sys.platform.startswith("win"):
            class MEMORIA(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MEMORIA()
            m.dwLength = ctypes.sizeof(MEMORIA)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                return None
            return m.ullTotalPhys / 1024 ** 3
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3
    except (AttributeError, ValueError, OSError):
        return None


def modelos_ollama(base: str = OLLAMA_URL, timeout: float = TIMEOUT_DETECCION_S) -> Optional[list[str]]:
    """Nombres de modelos instalados en Ollama, o None si no responde."""
    try:
        with urllib.request.urlopen(f"{base}/api/tags", timeout=timeout) as r:
            datos = json.loads(r.read().decode("utf-8"))
        return [m.get("name") or m.get("model") for m in datos.get("models", []) if m.get("name") or m.get("model")]
    except Exception:
        return None


def coincide(instalado: str, base: str) -> bool:
    """Igual o con sufijo: «qwen2.5:7b-instruct» y «qwen2.5:7b-q4_K_M» cubren «qwen2.5:7b», pero «qwen2.5:70b» no."""
    i, b = instalado.lower(), base.lower()
    return i == b or (i.startswith(b) and not i[len(b)].isalnum())


def _buscar(modelos: Sequence[str], base: str) -> Optional[str]:
    return next((m for m in modelos if coincide(m, base)), None)


def elegir_modelo(ram_gb: Optional[float], modelos: Sequence[str]) -> Optional[str]:
    """Modelo capaz instalado primero; luego el fabricado por el aprovisionador; luego los pequeños."""
    for base in MODELOS_CAPACES:
        m = _buscar(modelos, base)
        if m:
            return m
    propio = _buscar(modelos, "vitaband-coach")
    if propio:
        return propio
    pequeno = _buscar(modelos, MODELO_PEQUENO)
    if pequeno:
        return pequeno
    return modelos[0] if modelos else None


@dataclass(frozen=True)
class Motor:
    tipo: str                        # "ollama" | "offline"
    modelo: Optional[str] = None

    @property
    def etiqueta(self) -> str:
        if self.tipo == "ollama":
            return f"Motor: Ollama ({self.modelo})"
        return "Motor: Análisis Offline"

    @property
    def acento(self) -> str:
        return "emerald" if self.tipo == "ollama" else "gold"


MOTOR_OFFLINE = Motor("offline")


def detectar_motor(base: str = OLLAMA_URL, ram: Callable[[], Optional[float]] = ram_total_gb) -> Motor:
    modelos = modelos_ollama(base)
    if not modelos:
        return MOTOR_OFFLINE
    elegido = elegir_modelo(ram(), modelos)
    return Motor("ollama", elegido) if elegido else MOTOR_OFFLINE


# ------------------------------------------------------------------ Memoria corta y prompt

class MemoriaCorta:
    """Últimos ``max_turnos`` pares pregunta/respuesta."""

    def __init__(self, max_turnos: int = TURNOS_MEMORIA):
        self._turnos: deque[tuple[str, str]] = deque(maxlen=max_turnos)

    def agregar(self, pregunta: str, respuesta: str) -> None:
        self._turnos.append((pregunta, respuesta))

    def limpiar(self) -> None:
        self._turnos.clear()

    @property
    def turnos(self) -> list[tuple[str, str]]:
        return list(self._turnos)


def construir_prompt(pregunta: str, ctx_texto: str, turnos: Sequence[tuple[str, str]],
                     sistema: Optional[str] = None) -> str:
    partes = [sistema or PROMPT_SISTEMA, "", "DATOS REALES DEL USUARIO (solo lectura):",
              ctx_texto or "Sin datos todavía en la cuenta."]
    if turnos:
        partes += ["", "CONVERSACIÓN RECIENTE:"]
        for q, a in turnos:
            partes += [f"Usuario: {q}", f"Coach: {a}"]
    partes += ["", f"Usuario: {pregunta}", "Coach:"]
    return "\n".join(partes)


def construir_mensajes(pregunta: str, ctx_texto: str, turnos: Sequence[tuple[str, str]],
                       sistema: Optional[str] = None) -> list[dict]:
    """Mensajes para /api/chat: los datos van SOLO en `system` (referencia silenciosa); el usuario va limpio."""
    s = (sistema or PROMPT_SISTEMA) + ("\n\nDATOS FISIOLÓGICOS DEL USUARIO (referencia silenciosa; consúltalos solo si la "
                                       "pregunta los requiere):\n" + (ctx_texto or "Sin datos todavía en la cuenta."))
    msgs = [{"role": "system", "content": s}]
    for q, a in list(turnos)[-TURNOS_MEMORIA:]:
        msgs += [{"role": "user", "content": q}, {"role": "assistant", "content": a[:600]}]
    msgs.append({"role": "user", "content": pregunta})
    return msgs


def consultar_ollama(modelo: str, prompt: str, timeout: float = TIMEOUT_GENERACION_S, base: str = OLLAMA_URL,
                     al_fragmento: Optional[Callable[[str], None]] = None) -> str:
    """Streaming NDJSON: /api/chat si `prompt` es una lista de mensajes, /api/generate si es un texto."""
    chat = not isinstance(prompt, str)
    cuerpo = json.dumps({"model": modelo, "messages" if chat else "prompt": prompt, "stream": True,
                         "keep_alive": KEEP_ALIVE, "options": OPCIONES_OLLAMA}).encode("utf-8")
    peticion = urllib.request.Request(f"{base}/api/{'chat' if chat else 'generate'}", data=cuerpo, headers={"Content-Type": "application/json"},
                                      method="POST")
    partes: list[str] = []
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as r:
            for linea in r:
                linea = (linea.decode("utf-8") if isinstance(linea, bytes) else linea).strip()
                if not linea:
                    continue
                d = json.loads(linea)
                if d.get("error"):
                    raise RuntimeError(str(d["error"]))
                f = ((d.get("message") or {}).get("content") if chat else d.get("response")) or ""
                if f:
                    partes.append(f)
                    if al_fragmento:
                        al_fragmento(f)
                if d.get("done"):
                    break
    except ConnectionError as e:
        raise OllamaDesconectado(str(e)) from e
    except urllib.error.URLError as e:
        if isinstance(e.reason, ConnectionError):
            raise OllamaDesconectado(str(e)) from e
        raise ErrorGeneracion(str(e), "".join(partes)) from e
    except Exception as e:
        raise ErrorGeneracion(str(e) or e.__class__.__name__, "".join(partes)) from e
    texto = "".join(partes).strip()
    if not texto:
        raise ErrorGeneracion("Respuesta vacía de Ollama")
    return texto


# ------------------------------------------------------------------ Respaldo offline

def intencion(pregunta: str) -> str:
    q = pregunta.lower()
    if any(k in q for k in ("reajust", "me salté", "me salte", "sin culpa", "replanific")):
        return "reajuste"
    if any(k in q for k in ("preventiv", "enfermo", "enfermedad", "escudo", "gripe", "me estoy poniendo")):
        return "escudo"
    if any(k in q for k in ("hrr", "recuperación rápida", "recuperacion rapida", "baja mi pulso", "bajan mis pulsaciones")):
        return "hrr"
    if any(k in q for k in ("calidad", "ruido", "electrodo", "artefacto", "señal")):
        return "calidad"
    if any(k in q for k in ("médico", "medico", "informe clínico", "informe clinico")):
        return "informe"
    if any(k in q for k in ("semana", "resumen", "estado")):
        return "semanal"
    if any(k in q for k in ("hábito", "habito", "café", "cafe", "estrés", "estres", "etiqueta", "alcohol", "mal descanso")):
        return "habitos"
    if any(k in q for k in ("sesión", "sesion", "actividad", "entrenamiento de", "zona", "umbral", "última", "ultima")):
        return "actividad"
    if any(k in q for k in ("recuper", "hrv", "rmssd", "entrenar", "descans", "fatiga", "bateria", "batería")):
        return "recuperacion"
    return "semanal"


def _recuperacion(c: ContextoCoach) -> str:
    if c.hrv_reciente is None:
        extra = f" Tu FC en reposo reciente es {c.fc_reposo:.0f} BPM." if c.fc_reposo is not None else ""
        return ("Aún no tengo suficiente HRV en reposo para valorar tu recuperación (necesito al menos 3 mediciones "
                "recientes con la banda puesta en reposo)." + extra)
    base = f" frente a {c.hrv_base:.0f} ms de tu base" if c.hrv_base is not None else ""
    if c.recuperacion is None:
        return f"Tu RMSSD de los últimos días es {c.hrv_reciente:.0f} ms, pero aún no tengo base suficiente para compararlo."
    consejo = {"buena": "Estás recuperado: puedes entrenar con normalidad.",
               "moderada": "Recuperación a medias: mejor una sesión suave en Z2 que una intensa.",
               "baja": "Recuperación baja: prioriza descanso o una sesión muy suave."}[c.recuperacion]
    fc = f" FC en reposo: {c.fc_reposo:.0f} BPM." if c.fc_reposo is not None else ""
    return f"Tu RMSSD medio de 3 días es {c.hrv_reciente:.0f} ms{base} ({c.ratio_hrv * 100:.0f} %). {consejo}{fc}"


def _actividad(c: ContextoCoach) -> str:
    u = c.ultima
    if not u:
        return "No encuentro actividades recientes con pulso registrado para analizar."
    z = ""
    if u.get("zonas"):
        dom = max(range(5), key=lambda i: u["zonas"][i])
        z = f" Pasaste más tiempo en Z{dom + 1} ({u['zonas'][dom]:.0f} %)."
    return (f"Tu última sesión ({u['fecha']}) duró {u['duracion_min']:.0f} min con un pulso medio de "
            f"{u['bpm_medio']:.0f} BPM y máximo de {u['bpm_max']:.0f}.{z} Umbral de fatiga: {u['umbral']}.")


def _normalizar(texto: str) -> str:
    sin_acentos = "".join(ch for ch in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9 ]+", " ", sin_acentos.lower()).strip()


def reconocer_habito(etiqueta: str) -> Optional[str]:
    """Clave del hábito fisiológico conocido que describe la etiqueta, o None (cadena sin sentido → se ignora)."""
    t = _normalizar(etiqueta)
    palabras = t.split()
    for clave, (raices, _) in HABITOS_CONOCIDOS.items():
        for r in raices:
            if (" " in r and r in t) or any(p.startswith(r) for p in palabras):
                return clave
    return None


def _habitos(c: ContextoCoach) -> str:
    etiquetas = [(e, n) for e, n in c.etiquetas if reconocer_habito(e)]      # lo inventado se descarta en silencio
    if not etiquetas and c.hallazgos:
        return "Lo que he comprobado con tus datos: " + "; ".join(c.hallazgos) + "."
    if not etiquetas:
        return ("Todavía no hay hábitos reconocibles (café, estrés, mal descanso, siesta, ayuno…). "
                "Márcalos en el Historial para analizarlos.")
    texto = "Etiquetas recientes: " + ", ".join(f"{e} ({n})" for e, n in etiquetas) + "."
    efectos = [(e, d) for e, _, _, d in c.habitos if reconocer_habito(e)]
    if efectos:
        texto += " " + " ".join(
            f"Tras «{e}» tu RMSSD fue {d:+.0f} % respecto a tu base ({'más bajo' if d < 0 else 'más alto'})."
            for e, d in efectos)
    else:
        texto += " Aún no hay suficientes repeticiones con HRV para ver su efecto."
    notas = []
    for e, _ in etiquetas:                                                  # nota deportiva de los hábitos libres
        clave = reconocer_habito(e)
        if clave not in ("cafe", "descanso", "mareo", "estres") and HABITOS_CONOCIDOS[clave][1] not in notas:
            notas.append(HABITOS_CONOCIDOS[clave][1])
    if c.hallazgos:
        texto += " Lo que he comprobado con tus datos: " + "; ".join(c.hallazgos) + "."
    return texto + (" " + " ".join(notas) if notas else "")


def _escudo(c: ContextoCoach, sencillo: bool = False) -> str:
    if c.alerta is None:
        return "No detecto señales de fatiga o enfermedad: tu pulso en reposo y tu HRV de los últimos días están dentro de lo habitual."
    return c.alerta.texto(sencillo) + " Hoy: " + "descanso activo o Zona 1–2."


def _hrr(c: ContextoCoach, sencillo: bool = False) -> str:
    return c.hrr.texto(sencillo) if c.hrr is not None else (
        "Aún no tengo una recuperación postesfuerzo medida: pulsa «Finalizar sesión» en Tiempo Real al terminar de entrenar "
        "y mide cuánto baja tu pulso en 1 y 2 minutos.")


def _calidad(c: ContextoCoach, sencillo: bool = False) -> str:
    return c.calidad.texto(sencillo) if c.calidad is not None else "Aún no hay suficientes intervalos R-R para valorar la calidad del trazado."


def _reajuste(c: ContextoCoach, sencillo: bool = False) -> str:
    if c.reajuste is None:
        return "Tu semana va según lo planificado: no hace falta reajustar nada."
    return (c.reajuste.texto() + " No pasa nada: puedo acortar y suavizar (Zona 1–2) lo que queda de semana sin intentar recuperar "
            "lo perdido. [ACCION:REAJUSTAR_SEMANA]")


def _informe(c: ContextoCoach, sencillo: bool = False) -> str:
    return ("Pulsa «Preparar resumen para mi médico» en la cabecera del Coach: genera un dossier del último mes con tu pulso "
            "basal, HRV, recuperación, estrés y calidad del ECG, listo para copiar o exportar a PDF/TXT.")


def _semanal(c: ContextoCoach) -> str:
    partes = []
    s = c.semana
    if s and s["sesiones"]:
        obj = c.perfil.get("objetivo_min")
        partes.append(f"Esta semana llevas {s['sesiones']} sesiones y {s['minutos']:.0f} min de actividad"
                      + (f" ({s['minutos'] / obj * 100:.0f} % de tu objetivo de {obj} min)." if obj else "."))
    else:
        partes.append("Esta semana no hay actividades registradas.")
    partes.append(_recuperacion(c))
    return " ".join(partes)


TEXTO_ZONAS = ("Las zonas 1 a 5 miden la intensidad según tu pulso máximo, como las marchas de una bicicleta: "
               "Z1 muy suave (recuperar), Z2 aeróbica fácil (base de resistencia), Z3 moderada (ritmo sostenido), "
               "Z4 umbral (duro) y Z5 máximo esfuerzo (solo unos minutos).")
_ANALOGIAS = {"recuperacion": "En resumen: tu HRV es como el porcentaje de batería de tu sistema nervioso. ",
              "actividad": "En resumen: piensa en las zonas de pulso como las marchas de una bicicleta. "}


def respuesta_offline(pregunta: str, c: ContextoCoach, sencillo: bool = False) -> str:
    """Respuesta inmediata a partir de los datos reales, sin red."""
    q = pregunta.lower()
    if "zonas 1" in q or ("qué son" in q and "zona" in q):
        propio = ""
        if c.fc_max:
            from services.contexto_coach import texto_zonas
            propio = f" Con tu pulso máximo ({c.fc_max:.0f} BPM): {texto_zonas(c.fc_max)}. Tu marcha cómoda es la Z2."
        return f"{TEXTO_ZONAS}{propio} {DESCARGO}"
    if c.vacio and not c.semana.get("sesiones") and not (c.alerta or c.hallazgos or c.hrr or c.calidad or c.reajuste):
        return ("Aún no tengo datos tuyos para analizar. Usa la banda pectoral unos días (en reposo y entrenando) "
                "y vuelve a preguntarme. " + DESCARGO)
    clave = intencion(pregunta)
    if clave in ("escudo", "hrr", "calidad", "reajuste", "informe"):
        f = {"escudo": _escudo, "hrr": _hrr, "calidad": _calidad, "reajuste": _reajuste, "informe": _informe}[clave]
        return f"{f(c, sencillo)} {DESCARGO}"
    f = {"recuperacion": _recuperacion, "actividad": _actividad, "habitos": _habitos, "semanal": _semanal}[clave]
    previo = _ANALOGIAS.get(clave, "") if sencillo else ""
    if sencillo and clave == "recuperacion" and c.ratio_hrv is not None:
        previo = (f"En resumen: la batería de tu sistema nervioso (tu HRV) está al {c.ratio_hrv * 100:.0f} % de lo "
                  "habitual en ti. ")
    alerta = f"{_escudo(c, sencillo)} " if c.alerta is not None and clave in ("recuperacion", "semanal") else ""
    return f"{previo}{alerta}{f(c)} {DESCARGO}"


def responder(motor: Motor, pregunta: str, ctx: ContextoCoach, turnos: Sequence[tuple[str, str]],
              consultar: Optional[Callable[..., str]] = None, sistema: Optional[str] = None, extra: str = "",
              sencillo: bool = False, al_fragmento: Optional[Callable[[str], None]] = None,
              estricto: bool = False) -> tuple[str, Motor]:
    """(texto, motor realmente usado). Servidor caído → offline. Fallo puntual: offline salvo `estricto`, que lanza
    ErrorGeneracion para que la UI conserve el motor y ofrezca reintentar."""
    if motor.tipo == "ollama":
        try:
            texto_ctx = ctx.a_texto() + (("\n" + extra) if extra else "")
            kw = {"al_fragmento": al_fragmento} if al_fragmento else {}
            return (consultar or consultar_ollama)(motor.modelo, construir_mensajes(pregunta, texto_ctx, turnos, sistema),
                             TIMEOUT_GENERACION_S, **kw), motor
        except (OllamaDesconectado, ConnectionError):
            pass
        except ErrorGeneracion:
            if estricto:
                raise
        except Exception as e:
            if estricto:
                raise ErrorGeneracion(str(e) or e.__class__.__name__) from e
    return respuesta_offline(pregunta, ctx, sencillo), MOTOR_OFFLINE
