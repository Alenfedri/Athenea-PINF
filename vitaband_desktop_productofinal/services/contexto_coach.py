"""Coach IA «Maxx»: nivel Sencillo/Experto, arquetipos, memoria persistente, contexto biométrico total y acciones."""
from __future__ import annotations

import re
import statistics
from datetime import datetime
from typing import Optional

from services import coach_ia

NIVEL_SENCILLO, NIVEL_EXPERTO = "SENCILLO", "EXPERTO"
NIVELES = ((NIVEL_SENCILLO, "Sencillo (Explicado)"), (NIVEL_EXPERTO, "Experto (Técnico)"))
ARQUETIPOS = {
    "cercano": ("Entrenador Cercano", "Adopta el rol de Entrenador Cercano: tono cálido y motivador, como un coach que te conoce; "
                "prioriza carga (CTL/ATL/TSB), zonas, progresión y qué hacer hoy."),
    "clinico": ("Fisiólogo Clínico", "Adopta el rol de Fisiólogo Clínico: prioriza HRV, FC en reposo y señales de recuperación o "
                "sobrecarga, con prudencia clínica y sin diagnosticar."),
    "antiestres": ("Copiloto Antiestrés", "Adopta el rol de Copiloto Antiestrés: prioriza el equilibrio de estrés, el descanso, "
                   "la respiración y la coherencia cardíaca con tono sereno."),
}
ARQUETIPO_DEFECTO = "cercano"
ACCIONES = ("COHERENCIA_60S", "PLAN_ZONA2", "REAJUSTAR_SEMANA")

_PROMPT_SENCILLO = (
    "[NIVEL:SENCILLO] Habla como un coach cercano y didáctico para un estudiante novato. PROHIBIDO soltar siglas o números "
    "sin traducirlos con ejemplos cotidianos y con los datos reales del usuario: Zonas 1–5 = las marchas de una bici o de un "
    "coche (p. ej. «tu Zona 2 hoy está entre X e Y BPM: tu marcha cómoda, donde puedes hablar sin ahogarte»); HRV/RMSSD = el "
    "porcentaje de batería de tu sistema nervioso (alta = cuerpo cargado y listo; baja = batería agotada por estrés o "
    "cansancio); TRIMP/ATL = la fatiga acumulada de los últimos días («agujetas internas»); CTL = tu depósito de resistencia "
    "construido semana a semana; desacoplamiento aeróbico = si el corazón se acelera al final manteniendo el mismo ritmo (falta "
    "de fondo o de hidratación). Solo cuando el usuario pida un análisis de sus datos, estructura la respuesta en: «1. En resumen», «2. Qué dicen tus datos (en palabras "
    "fáciles)» y «3. Qué te recomiendo hacer hoy».")
_PROMPT_EXPERTO = (
    "[NIVEL:EXPERTO] Rigor fisiológico ejecutivo y terminología técnica. Solo cuando el usuario pida un análisis de sus datos, estructura la respuesta en: «VEREDICTO "
    "CLARO», «EVIDENCIA FISIOLÓGICA» (con cifras exactas) y «ACCIÓN INMEDIATA».")
_PROMPT_REGLAS = (
    "REGLAS DE COACH (en ambos niveles): contrasta siempre lo que pide el usuario con su recuperación real; si el RMSSD cae más "
    "de un 15 % respecto a su media o el TSB es menor de -20, frena la intensidad y prioriza Zona 1–2 o descanso. Cuando "
    "recomiendes una pausa respiratoria termina con <ACTION>{\"type\": \"COHERENCIA_60S\"}</ACTION>; cuando recomiendes un rodaje suave de Zona 2 de "
    "40 min termina con <ACTION>{\"type\": \"PLAN_ZONA2\"}</ACTION>; cuando el contexto indique un REAJUSTE PENDIENTE ofrécelo con "
    "empatía y sin culpa terminando con <ACTION>{\"type\": \"REAJUSTAR_SEMANA\"}</ACTION> (solo si el usuario pide o acepta la "
    "acción; nunca en saludos ni en duelo). Nunca inventes datos que no estén en el contexto.")
_PROMPT_PILARES = (
    "6 PILARES (en ambos niveles, usando solo el contexto): (1) ESCUDO PREVENTIVO: si el contexto trae «ALERTA PREVENTIVA ACTIVA», "
    "rebaja la intensidad del día a descanso activo o Zona 1–2 y explica la señal (en Sencillo: «tu batería interna lleva días "
    "bajando y tu pulso en reposo subió; tu cuerpo gasta energía extra, toca descanso activo»). (2) DETECTIVE DE HÁBITOS: cita "
    "solo las correlaciones comprobadas de «HÁBITOS ↔ CORAZÓN». (3) RECUPERACIÓN: interpreta HRR 1'/2' (≥ 18 latidos en el "
    "primer minuto = buena) y la calidad del ECG: tranquiliza al principiante si fue ruido aislado y, si hubo mal contacto, "
    "recomienda humedecer los electrodos de la banda pectoral. (4) SUSURRADOR: si el usuario entrena fuera de la zona objetivo, "
    "dile en lenguaje sencillo qué hacer. (5) MODO VIDA REAL: ante una sesión saltada o estrés alto, reajusta sin culpa. "
    "(6) INFORME: si pide algo para su médico, indica el botón «Preparar resumen para mi médico».")
_PROMPT_ACCIONES = _PROMPT_REGLAS
PROMPT_MAESTRO = "\n".join([coach_ia.PROMPT_SISTEMA, "Tienes dos niveles que se activan con la etiqueta [NIVEL:SENCILLO] "
                            "(por defecto) o [NIVEL:EXPERTO] del mensaje.", _PROMPT_SENCILLO, _PROMPT_EXPERTO, _PROMPT_REGLAS, _PROMPT_PILARES])

CHULETA = (
    "BPM: latidos por minuto; tu pulso en este instante.\n"
    "Zonas 1–5: intensidad según tu pulso máximo, como las marchas de una bici (Z1 muy suave … Z5 máximo esfuerzo).\n"
    "HRV/RMSSD: la «batería» de tu sistema nervioso; más alta = mejor recuperado.\n"
    "TRIMP: carga de una sesión; sumada de varios días da tu fatiga acumulada (ATL).\n"
    "Desacoplamiento: si tu pulso sube al final con el mismo ritmo, estabas perdiendo eficiencia aeróbica.")

PREGUNTAS_PRINCIPIANTE = ("¿Cómo está mi batería hoy?", "¿Qué son las Zonas 1 a 5?", "Resume mi última sesión fácil")


def prompt_sistema(nivel: str = NIVEL_SENCILLO, arquetipo: str = ARQUETIPO_DEFECTO, memoria: str = "") -> str:
    partes = [coach_ia.PROMPT_SISTEMA, _PROMPT_EXPERTO if nivel == NIVEL_EXPERTO else _PROMPT_SENCILLO,
              ARQUETIPOS.get(arquetipo, ARQUETIPOS[ARQUETIPO_DEFECTO])[1], _PROMPT_ACCIONES, _PROMPT_PILARES]
    if memoria:
        partes.append("MEMORIA DEL USUARIO (notas y hechos que él mismo ha contado):\n" + memoria)
    return "\n".join(partes)


# ---------------------------------------------------------------- Memoria persistente (SQLite)

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS coach_memoria (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario INTEGER NOT NULL,
    ts      INTEGER NOT NULL,
    tipo    TEXT    NOT NULL,
    texto   TEXT    NOT NULL
);
"""
_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS borrar_coach_memoria_usuario AFTER DELETE ON usuarios
BEGIN DELETE FROM coach_memoria WHERE usuario = OLD.id; END;
"""
MAX_LONGITUD_NOTA = 240
_PATRONES_HECHOS = (
    ("Lesión", re.compile(r"\b(lesi[oó]n|lesionad[oa]|tendinitis|esguince|rotura|fractura|me duele|dolor de|contractura)\b", re.I)),
    ("Carrera", re.compile(r"\b(marat[oó]n|media marat[oó]n|10\s?k|5\s?k|carrera|competici[oó]n|triatl[oó]n|cursa)\b", re.I)),
    ("Sueño", re.compile(r"\b(falta de sue[nñ]o|dorm[ií] (mal|poco)|no (he )?dormido|duermo (mal|poco)|insomnio)\b", re.I)),
)


def extraer_hechos(texto: str) -> list[str]:
    """Frases del usuario con lesiones, carreras o falta de sueño → «Lesión: …» (hechos clave del chat)."""
    hechos = []
    for frase in re.split(r"(?<=[.!?\n])\s+", texto.strip()):
        f = frase.strip()
        if not f or f.endswith("?"):
            continue
        for etiqueta, patron in _PATRONES_HECHOS:
            if patron.search(f):
                hechos.append(f"{etiqueta}: {f[:MAX_LONGITUD_NOTA]}")
                break
    return hechos


class MemoriaCoach:
    def __init__(self, repo):
        self._c, self._u = repo.conexion, repo.usuario_id
        with self._c:
            self._c.executescript(_ESQUEMA)
            if self._c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='usuarios'").fetchone():
                self._c.executescript(_TRIGGER)

    def agregar(self, texto: str, tipo: str = "nota", ts: Optional[int] = None) -> Optional[int]:
        texto = " ".join(texto.split())[:MAX_LONGITUD_NOTA]
        if not texto:
            raise ValueError("La nota no puede estar vacía")
        if self._c.execute("SELECT 1 FROM coach_memoria WHERE usuario = ? AND tipo = ? AND texto = ?",
                           (self._u, tipo, texto)).fetchone():
            return None                                                  # sin duplicados
        with self._c:
            cur = self._c.execute("INSERT INTO coach_memoria (usuario, ts, tipo, texto) VALUES (?,?,?,?)",
                                  (self._u, int(ts if ts is not None else datetime.now().timestamp()), tipo, texto))
        return int(cur.lastrowid)

    def registrar_hechos_de(self, mensaje: str, ts: Optional[int] = None) -> list[str]:
        nuevos = []
        for h in extraer_hechos(mensaje):
            if self.agregar(h, "hecho", ts) is not None:
                nuevos.append(h)
        return nuevos

    def listar(self) -> list[tuple[int, int, str, str]]:
        """Notas manuales y hechos del chat (la ficha editable se guarda aparte con tipo «ficha:…»)."""
        return [tuple(f) for f in self._c.execute(
            "SELECT id, ts, tipo, texto FROM coach_memoria WHERE usuario = ? AND tipo IN ('nota', 'hecho') "
            "ORDER BY ts, id", (self._u,))]

    def fijar_ficha(self, campo: str, valor: str) -> None:
        """Campo editable de la ficha (disciplina, objetivo, fc_reposo, fc_max); vacío = borrar."""
        with self._c:
            self._c.execute("DELETE FROM coach_memoria WHERE usuario = ? AND tipo = ?", (self._u, f"ficha:{campo}"))
            valor = " ".join(str(valor).split())[:60]
            if valor:
                self._c.execute("INSERT INTO coach_memoria (usuario, ts, tipo, texto) VALUES (?,?,?,?)",
                                (self._u, int(datetime.now().timestamp()), f"ficha:{campo}", valor))

    def ficha(self) -> dict:
        return {t[6:]: x for t, x in self._c.execute(
            "SELECT tipo, texto FROM coach_memoria WHERE usuario = ? AND tipo LIKE 'ficha:%'", (self._u,))}

    def eliminar(self, id_: int) -> bool:
        with self._c:
            return self._c.execute("DELETE FROM coach_memoria WHERE usuario = ? AND id = ?", (self._u, id_)).rowcount > 0

    def a_texto(self, maximo: int = 8) -> str:
        return "\n".join(f"- {t}" for _, _, _, t in self.listar()[-maximo:])


# ---------------------------------------------------------------- Acciones ejecutables

_RE_ACCION = re.compile(r"\[ACCION:([A-Z0-9_]+)\]|<ACTION>\s*\{[^{}]*?\"type\"\s*:\s*\"([A-Za-z0-9_]+)\"[^{}]*?\}\s*</ACTION>")


def extraer_acciones(texto: str) -> tuple[str, list[str]]:
    """(texto sin etiquetas, acciones válidas sin repetir). Las etiquetas desconocidas se descartan."""
    acciones = []
    for m in _RE_ACCION.finditer(texto):
        nombre = (m.group(1) or m.group(2) or "").upper()
        if nombre in ACCIONES and nombre not in acciones:
            acciones.append(nombre)
    return _RE_ACCION.sub("", texto).strip(), acciones


# ---------------------------------------------------------------- Contexto biométrico total

def _seguro(f):
    try:
        return f()
    except Exception:
        return None


def zonas_bpm(fc_max: float) -> list[tuple[int, int, int]]:
    """[(zona, BPM mín, BPM máx)] con los mismos límites que el resto de la app (60/70/80/90 % de la FC máx)."""
    from domain.zonas_actividad import LIMITES_ZONAS
    cortes = [0.5] + list(LIMITES_ZONAS) + [1.0]
    return [(z + 1, round(fc_max * cortes[z]), round(fc_max * cortes[z + 1])) for z in range(5)]


def texto_zonas(fc_max: Optional[float]) -> str:
    return " · ".join(f"Z{z} {lo}-{hi} BPM" for z, lo, hi in zonas_bpm(fc_max)) if fc_max else ""


def contexto_total(vm) -> str:
    """Ficha, RMSSD 7/28 d, CTL/ATL/TSB, VO2máx, balance de estrés y última sesión (Z1–Z5, TRIMP, desacoplamiento)."""
    repo = vm.repositorio
    if repo is None:
        return ""
    from datetime import date
    from services import fisiologia_avanzada as fa, metricas_avanzadas as ma, vo2max
    from services.ia_local_sesion import desacoplamiento_pct
    ahora = int(vm._reloj())
    l = []
    perfil = _seguro(vm.perfil)
    mem = _seguro(vm.memoria_coach)
    editada = (mem.ficha() if mem else {}) or {}
    discs = _seguro(repo.disciplinas) or {}
    disc = editada.get("disciplina") or (max(set(discs.values()), key=list(discs.values()).count) if discs else None)
    reposo = _seguro(lambda: vo2max.fc_reposo(repo.mediciones_rango(ahora - 30 * 86400, ahora + 1)))
    fcmax = _seguro(lambda: vo2max.fc_max_observada(repo.mediciones_rango(ahora - 180 * 86400, ahora + 1)))
    try:
        reposo = float(editada["fc_reposo"]) if editada.get("fc_reposo") else reposo
        fcmax = float(editada["fc_max"]) if editada.get("fc_max") else fcmax
    except ValueError:
        pass
    objetivo = editada.get("objetivo") or (f"{perfil.objetivo_semanal_min} min semanales" if perfil else "")
    ficha = [f"disciplina habitual {disc}" if disc else "", f"objetivo {objetivo}" if objetivo else "",
             f"FC reposo {reposo:.0f} BPM" if reposo else "", f"FC máx {fcmax:.0f} BPM" if fcmax else ""]
    l.append("FICHA: " + (", ".join(x for x in ficha if x) or "sin datos"))
    zb = texto_zonas(fcmax or _seguro(lambda: float(vo2max.fc_max_tanaka(perfil.edad)) if perfil and perfil.edad else None))
    if zb:
        l.append("Zonas de pulso del usuario: " + zb + ".")
    hrvs = _seguro(lambda: repo.hrv_rango(ahora - 28 * 86400, ahora + 1)) or []
    r7 = [h.rmssd_ms for h in hrvs if h.ts >= ahora - 7 * 86400]
    if hrvs:
        d7 = f"{statistics.fmean(r7):.0f} ms" if r7 else "sin datos"
        m28 = statistics.fmean(h.rmssd_ms for h in hrvs)
        l.append(f"RMSSD medio: 7 días {d7} · 28 días {m28:.0f} ms.")
        if r7 and statistics.fmean(r7) < 0.85 * m28:
            l.append("ALERTA: el RMSSD de 7 días ha caído más de un 15 % respecto a su media: frenar la intensidad.")
    hoy = date.fromtimestamp(ahora)
    pmc = _seguro(lambda: fa.calcular_pmc(fa.trimp_diario(repo, hoy), hoy, 90))
    if pmc:
        p = pmc[-1]
        l.append(f"Carga: CTL {p.ctl:.0f} (resistencia), ATL {p.atl:.0f} (fatiga), TSB {p.tsb:+.0f} (forma).")
        if p.tsb < -20:
            l.append("ALERTA: TSB menor de -20: priorizar Zona 1–2 o descanso.")
    vo2 = _seguro(vm.estimacion_vo2)
    if vo2:
        l.append(f"VO2máx estimado: {vo2.vo2:.0f} ml/kg/min.")
    bal = _seguro(lambda: __import__("services.balance_mental", fromlist=["x"]).BalanceCargaMental(repo).dia())
    if bal and bal.total_s > 0:
        l.append("Balance de estrés de hoy (Modo Escritorio): " + bal.texto() + ".")
    acts = _seguro(lambda: repo.actividades_rango(ahora - 60 * 86400, ahora + 1)) or []
    if acts:
        act = acts[0]
        ms = _seguro(lambda: repo.mediciones_de_actividad(act.id)) or []
        bpm = [m.bpm for m in ms if m.bpm]
        if bpm:
            from domain.zonas_actividad import zona_de
            fm = fcmax or 190
            zt = [0] * 5
            for b in bpm:
                zt[zona_de(b, fm)] += 1
            zonas = ", ".join(f"Z{i + 1} {100 * n / len(bpm):.0f} %" for i, n in enumerate(zt))
            trimp = _seguro(lambda: ma.trimp(ms, fm))
            desac = _seguro(lambda: desacoplamiento_pct(bpm))
            l.append(f"Última sesión ECG ({datetime.fromtimestamp(act.inicio_ts):%d/%m/%Y %H:%M}, {act.duracion_s / 60:.0f} min): "
                     f"BPM medio {statistics.fmean(bpm):.0f}, máx {max(bpm):.0f}. {zonas}."
                     + (f" TRIMP {trimp:.0f}." if trimp else "") + (f" Desacoplamiento {desac:.1f} %." if desac is not None else ""))
    try:
        from services import inteligencia_biometrica as ib
        l += ib.lineas_contexto(repo, ahora)
    except Exception:
        pass
    return "\n".join(x for x in l if x)
