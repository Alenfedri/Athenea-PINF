"""Inteligencia biométrica del Coach (banda pectoral ECG): escudo preventivo, detective de hábitos, HRR y calidad ECG,
susurrador en vivo, replanificador «sin culpa» e informe clínico. Estimaciones orientativas; no sustituyen a un médico."""
from __future__ import annotations

import json
import re
import statistics
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable, Optional, Sequence

from domain import marcadores_contexto

DIA = 86400
INTENSIDAD_PREVENTIVA = "descanso activo o Zona 1–2"

# ------------------------------------------------------------------ utilidades diarias


def _dia(ts: float) -> date:
    return date.fromtimestamp(ts)


def _por_dia(repo, desde_ts: int, hasta_ts: int) -> dict:
    """{fecha: (pulso basal medio, RMSSD medio)} a partir de las ventanas HRV en reposo."""
    acum: dict = {}
    for h in repo.hrv_rango(desde_ts, hasta_ts):
        acum.setdefault(_dia(h.ts), []).append((h.fc_media, h.rmssd_ms))
    return {d: (statistics.fmean(x[0] for x in v), statistics.fmean(x[1] for x in v)) for d, v in acum.items()}


# ------------------------------------------------------------------ 1. Escudo Preventivo

SUBIDA_BASAL_BPM = 5.0
CAIDA_RMSSD = 0.15
DIAS_MIN_ALERTA = 3


@dataclass(frozen=True)
class AlertaPreventiva:
    dias: int
    subida_bpm: float
    caida_rmssd_pct: float

    def texto(self, sencillo: bool = True) -> str:
        if sencillo:
            return (f"Tu batería interna lleva {self.dias} días bajando (un {self.caida_rmssd_pct:.0f} % menos) y tu pulso en "
                    f"reposo subió {self.subida_bpm:.0f} latidos: tu cuerpo está gastando energía extra, toca "
                    f"{INTENSIDAD_PREVENTIVA}.")
        return (f"Alerta preventiva: pulso basal +{self.subida_bpm:.1f} BPM y RMSSD −{self.caida_rmssd_pct:.0f} % sobre su media de "
                f"28 días durante {self.dias} días sin carga que lo justifique. Intensidad sugerida: {INTENSIDAD_PREVENTIVA}.")


def escudo_preventivo(repo, ahora_ts: int) -> Optional[AlertaPreventiva]:
    """Subida sostenida del pulso basal (≥ +5 BPM) con caída del RMSSD (≥ 15 %) ≥ 3 de los últimos 5 días sin carga que lo explique."""
    dias = _por_dia(repo, ahora_ts - 28 * DIA, ahora_ts + 1)
    hoy = _dia(ahora_ts)
    recientes = [hoy - timedelta(days=i) for i in range(5)]
    base = [v for d, v in dias.items() if d not in recientes]
    if len(base) < 5:
        base = list(dias.values())                                   # poco histórico: media de todo el mes
    if len(base) < 5 or sum(1 for d in recientes if d in dias) < DIAS_MIN_ALERTA:
        return None
    fc0, rm0 = statistics.fmean(v[0] for v in base), statistics.fmean(v[1] for v in base)
    malos = [(dias[d][0] - fc0, 100.0 * (rm0 - dias[d][1]) / rm0) for d in recientes
             if d in dias and dias[d][0] - fc0 >= SUBIDA_BASAL_BPM and (rm0 - dias[d][1]) / rm0 >= CAIDA_RMSSD]
    if len(malos) < DIAS_MIN_ALERTA or recientes[0] not in dias and recientes[1] not in dias:
        return None
    try:                                                              # una carga deportiva alta explica el cansancio
        from services import fisiologia_avanzada as fa
        trimp = fa.trimp_diario(repo, hoy)
        ult = [trimp.get(hoy - timedelta(days=i), 0.0) for i in range(3)]
        mes = [trimp.get(hoy - timedelta(days=i), 0.0) for i in range(28)]
        if statistics.fmean(mes) > 0 and statistics.fmean(ult) > 1.5 * statistics.fmean(mes):
            return None
    except Exception:
        pass
    return AlertaPreventiva(len(malos), statistics.fmean(m[0] for m in malos), statistics.fmean(m[1] for m in malos))


# ------------------------------------------------------------------ 2. Detective de Hábitos

HABITOS_RAPIDOS = ("Dormí mal", "Café tarde", "Mucha pantalla", "Buena hidratación")
MIN_DIAS_CORRELACION = 2
UMBRAL_VARIACION_PCT = 5.0

_ESQUEMA_HABITOS = """
CREATE TABLE IF NOT EXISTS habitos_diarios (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL,
    fecha      TEXT    NOT NULL,
    etiqueta   TEXT    NOT NULL,
    UNIQUE (usuario_id, fecha, etiqueta)
);
"""


@dataclass(frozen=True)
class Hallazgo:
    etiqueta: str
    n: int
    metrica: str            # «recuperación (RMSSD)», «pulso basal» o «estrés»
    ambito: str             # «ese día» o «el día siguiente»
    variacion_pct: float

    def texto(self) -> str:
        verbo = "sube" if self.variacion_pct > 0 else "baja"
        return (f"tras «{self.etiqueta}», tu {self.metrica} {self.ambito} {verbo} un {abs(self.variacion_pct):.0f} % "
                f"(sobre {self.n} días)")


class RegistroHabitos:
    def __init__(self, repo):
        self._repo, self._c, self._u = repo, repo.conexion, repo.usuario_id
        with self._c:
            self._c.executescript(_ESQUEMA_HABITOS)

    def registrar(self, etiqueta: str, fecha: Optional[date] = None) -> bool:
        """True si es nuevo ese día (sin duplicados)."""
        etiqueta = marcadores_contexto.normalizar_etiqueta(etiqueta)
        f = (fecha or date.today()).isoformat()
        with self._c:
            return self._c.execute("INSERT OR IGNORE INTO habitos_diarios (usuario_id, fecha, etiqueta) VALUES (?,?,?)",
                                   (self._u, f, etiqueta)).rowcount > 0

    def dias(self, etiqueta: str) -> list[date]:
        return [date.fromisoformat(f[0]) for f in self._c.execute(
            "SELECT fecha FROM habitos_diarios WHERE usuario_id = ? AND etiqueta = ? ORDER BY fecha", (self._u, etiqueta))]

    def del_dia(self, fecha: Optional[date] = None) -> list[str]:
        return [f[0] for f in self._c.execute("SELECT etiqueta FROM habitos_diarios WHERE usuario_id = ? AND fecha = ? ORDER BY id",
                                              (self._u, (fecha or date.today()).isoformat()))]

    def etiquetas(self) -> list[str]:
        return [f[0] for f in self._c.execute("SELECT DISTINCT etiqueta FROM habitos_diarios WHERE usuario_id = ? ORDER BY etiqueta",
                                              (self._u,))]

    def correlaciones(self, ahora_ts: int, dias_hist: int = 90) -> list[Hallazgo]:
        """Variación % real de RMSSD, pulso basal y estrés (Modo Escritorio) el mismo día y el siguiente frente a los días sin la etiqueta."""
        fisio = _por_dia(self._repo, ahora_ts - dias_hist * DIA, ahora_ts + 1)
        estres = _estres_por_dia(self._repo, ahora_ts - dias_hist * DIA)
        series = {"pulso basal": {d: v[0] for d, v in fisio.items()},
                  "recuperación (RMSSD)": {d: v[1] for d, v in fisio.items()}, "estrés": estres}
        res = []
        for et in self.etiquetas():
            marcados = set(self.dias(et))
            for metrica, serie in series.items():
                for ambito, desfase in (("ese día", 0), ("el día siguiente", 1)):
                    con = [serie[d + timedelta(days=desfase)] for d in marcados if d + timedelta(days=desfase) in serie]
                    sin = [v for d, v in serie.items() if (d - timedelta(days=desfase)) not in marcados]
                    if len(con) < MIN_DIAS_CORRELACION or len(sin) < 3 or statistics.fmean(sin) <= 0:
                        continue
                    var = 100.0 * (statistics.fmean(con) - statistics.fmean(sin)) / statistics.fmean(sin)
                    if abs(var) >= UMBRAL_VARIACION_PCT:
                        res.append(Hallazgo(et, len(con), metrica, ambito, var))
        return sorted(res, key=lambda h: -abs(h.variacion_pct))


def _estres_por_dia(repo, desde_ts: int) -> dict:
    """{fecha: fracción de tiempo en estrés sostenido} del Modo Escritorio (tabla balance_carga_mental)."""
    try:
        filas = repo.conexion.execute("SELECT fecha, calma_s, tension_s, estres_s FROM balance_carga_mental "
                                      "WHERE usuario = ? AND fecha >= ?", (repo.usuario_id, _dia(desde_ts).isoformat())).fetchall()
    except Exception:
        return {}
    return {date.fromisoformat(f[0]): f[3] / (f[1] + f[2] + f[3]) for f in filas if f[1] + f[2] + f[3] > 0}


# ------------------------------------------------------------------ 3. HRR 1' / 2' y calidad ECG

_ESQUEMA_HRR = """
CREATE TABLE IF NOT EXISTS recuperacion_sesion (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id  INTEGER NOT NULL,
    ts_fin      INTEGER NOT NULL,
    actividad_id INTEGER,
    bpm_pico    REAL    NOT NULL,
    hrr_1m      REAL,
    hrr_2m      REAL,
    UNIQUE (usuario_id, ts_fin)
);
"""


@dataclass(frozen=True)
class Hrr:
    bpm_pico: float
    hrr_1m: Optional[float]
    hrr_2m: Optional[float]

    def texto(self, sencillo: bool = True) -> str:
        if self.hrr_1m is None:
            return "Aún no hay datos suficientes de recuperación."
        partes = [f"tu pulso bajó {self.hrr_1m:.0f} latidos en el primer minuto"]
        if self.hrr_2m is not None:
            partes.append(f"{self.hrr_2m:.0f} en dos minutos")
        valor = "buena recuperación" if self.hrr_1m >= 18 else "recuperación normal" if self.hrr_1m >= 12 else "recuperación lenta"
        if sencillo:
            return ", ".join(partes).capitalize() + f": {valor} (cuanto más baja el pulso tras parar, mejor forma tienes)."
        return f"HRR 1' {self.hrr_1m:.0f} BPM" + (f" · HRR 2' {self.hrr_2m:.0f} BPM" if self.hrr_2m is not None else "") + f" ({valor})."


def _bpm_en(muestras: Sequence[tuple], t: float, tol: float = 6.0) -> Optional[float]:
    v = [b for ts, b in muestras if abs(ts - t) <= tol and b and b > 0]
    return statistics.fmean(v) if v else None


def calcular_hrr(muestras: Sequence[tuple], t_fin: float) -> Optional[Hrr]:
    """HRR 1'/2' = pulso al terminar el esfuerzo menos el pulso 60 y 120 s después. ``muestras``: [(ts, bpm)]."""
    antes = [b for ts, b in muestras if t_fin - 30 <= ts <= t_fin and b and b > 0]
    if len(antes) < 3:
        return None
    pico = max(statistics.fmean(antes[i:i + 3]) for i in range(len(antes) - 2))
    b60, b120 = _bpm_en(muestras, t_fin + 60), _bpm_en(muestras, t_fin + 120)
    if b60 is None and b120 is None:
        return None
    return Hrr(pico, None if b60 is None else max(0.0, pico - b60), None if b120 is None else max(0.0, pico - b120))


class RecuperacionSesiones:
    def __init__(self, repo):
        self._c, self._u = repo.conexion, repo.usuario_id
        with self._c:
            self._c.executescript(_ESQUEMA_HRR)

    def guardar(self, ts_fin: int, hrr: Hrr, actividad_id: Optional[int] = None) -> None:
        with self._c:
            self._c.execute("INSERT OR REPLACE INTO recuperacion_sesion (usuario_id, ts_fin, actividad_id, bpm_pico, hrr_1m, hrr_2m) "
                            "VALUES (?,?,?,?,?,?)", (self._u, int(ts_fin), actividad_id, hrr.bpm_pico, hrr.hrr_1m, hrr.hrr_2m))

    def rango(self, desde_ts: int, hasta_ts: int) -> list[tuple[int, Hrr]]:
        return [(f[0], Hrr(f[1], f[2], f[3])) for f in self._c.execute(
            "SELECT ts_fin, bpm_pico, hrr_1m, hrr_2m FROM recuperacion_sesion WHERE usuario_id = ? AND ts_fin >= ? AND ts_fin < ? "
            "ORDER BY ts_fin", (self._u, desde_ts, hasta_ts))]

    def ultimo(self) -> Optional[tuple[int, Hrr]]:
        f = self._c.execute("SELECT ts_fin, bpm_pico, hrr_1m, hrr_2m FROM recuperacion_sesion WHERE usuario_id = ? "
                            "ORDER BY ts_fin DESC LIMIT 1", (self._u,)).fetchone()
        return (f[0], Hrr(f[1], f[2], f[3])) if f else None


def evaluar_sesion_cerrada(repo, actividad) -> Optional[Hrr]:
    """HRR de una actividad ya cerrada con el pulso registrado justo después de terminar; lo guarda en SQLite."""
    ms = repo.mediciones_rango(actividad.fin_ts - 40, actividad.fin_ts + 135)
    h = calcular_hrr([(m.ts, m.bpm) for m in ms], actividad.fin_ts)
    if h is not None:
        RecuperacionSesiones(repo).guardar(actividad.fin_ts, h, actividad.id)
    return h


RR_MIN_MS, RR_MAX_MS = 250.0, 2000.0
SALTO_RELATIVO = 0.35          # un R-R que se aparta > 35 % de la mediana local es un salto brusco


@dataclass(frozen=True)
class CalidadEcg:
    pct_artefactos: float
    aislados: int
    rafagas: int
    nivel: str                  # «limpia» | «ruido_aislado» | «mal_contacto»

    @property
    def calidad_pct(self) -> float:
        return max(0.0, 100.0 - self.pct_artefactos)

    def texto(self, sencillo: bool = True) -> str:
        if self.nivel == "limpia":
            return ("Tu trazado salió limpio: la variabilidad que ves es la de tu corazón, no ruido."
                    if sencillo else f"Trazado limpio ({self.calidad_pct:.0f} % de R-R válidos).")
        if self.nivel == "ruido_aislado":
            return ("Hubo algún latido suelto raro, pero fue un pico aislado y no cambia nada: no te preocupes."
                    if sencillo else f"{self.aislados} artefactos aislados ({self.pct_artefactos:.1f} %); sin impacto relevante.")
        return ("La señal tuvo mucho ruido (electrodo seco o mal contacto): humedece los electrodos de la banda pectoral, "
                "ajústala bien y repite la medida." if sencillo else
                f"Calidad baja: {self.pct_artefactos:.0f} % de R-R inválidos en {self.rafagas} ráfagas; revisar contacto de los electrodos.")


def analizar_calidad_ecg(rr_ms: Sequence[float]) -> Optional[CalidadEcg]:
    """Distingue picos aislados imposibles o saltos bruscos (electrodo seco) de la variabilidad fisiológica sostenida."""
    rr = [float(x) for x in rr_ms]
    if len(rr) < 10:
        return None
    mal = [False] * len(rr)
    for i, v in enumerate(rr):
        vec = rr[max(0, i - 3):i] + rr[i + 1:i + 4]
        med = statistics.median(vec) if vec else v
        mal[i] = v < RR_MIN_MS or v > RR_MAX_MS or abs(v - med) > SALTO_RELATIVO * med
    rafagas = aislados = 0
    i = 0
    while i < len(mal):
        if mal[i]:
            j = i
            while j < len(mal) and mal[j]:
                j += 1
            if j - i >= 3:
                rafagas += 1
            else:
                aislados += j - i
            i = j
        else:
            i += 1
    pct = 100.0 * sum(mal) / len(mal)
    nivel = "mal_contacto" if rafagas >= 1 or pct > 10.0 else "ruido_aislado" if aislados else "limpia"
    return CalidadEcg(pct, aislados, rafagas, nivel)


def calidad_media(repo, desde_ts: int, hasta_ts: int) -> Optional[float]:
    """% medio de R-R válidos de las ventanas guardadas (None sin datos)."""
    v = [c.calidad_pct for c in (analizar_calidad_ecg(w) for w in repo.rr_rango(desde_ts, hasta_ts)) if c]
    return statistics.fmean(v) if v else None


# ------------------------------------------------------------------ 4. Susurrador en vivo

FUERA_ZONA_S = 240.0            # más de 4 min continuos fuera de la zona objetivo
ENFRIAMIENTO_SUSURRO_S = 300.0
MARCHAS = ("primera", "segunda", "tercera", "cuarta", "quinta")


def zona_objetivo_hoy(repo, hoy: date) -> Optional[int]:
    """Zona objetivo (0..4) de la sesión planificada para hoy: la de más duración del plan o «Zona N» del nombre."""
    try:
        filas = repo.conexion.execute("SELECT nombre, plan, id FROM sesiones_planificadas WHERE usuario_id = ? AND fecha = ? ORDER BY id",
                                      (repo.usuario_id, hoy.isoformat())).fetchall()
        try:                                            # «Iniciar ahora» fija la sesión objetivo del día
            f = repo.conexion.execute("SELECT valor FROM app_meta WHERE clave = ?", (f"objetivo_hoy_{repo.usuario_id}",)).fetchone()
            if f and f[0].split("|")[0] == hoy.isoformat():
                fijada = int(f[0].split("|")[1])
                filas = sorted(filas, key=lambda r: r[2] != fijada)
        except Exception:
            pass
    except Exception:
        return None
    for nombre, plan, _id in filas:
        dur: dict = {}

        def recorrer(o):
            if isinstance(o, dict):
                if "zona" in o and "duracion_s" in o:
                    dur[int(o["zona"])] = dur.get(int(o["zona"]), 0) + o["duracion_s"] * max(1, int(o.get("veces", 1)))
                for v in o.values():
                    recorrer(v)
            elif isinstance(o, list):
                for v in o:
                    recorrer(v)
        if plan:
            try:
                recorrer(json.loads(plan))
            except ValueError:
                pass
        if dur:
            return max(dur, key=dur.get)
        m = re.search(r"zona\s*([1-5])", nombre or "", re.I)
        if m:
            return int(m.group(1)) - 1
    return None


def texto_susurro(bpm: float, zona_actual: int, zona_objetivo: int) -> str:
    marcha = MARCHAS[zona_actual]
    if zona_actual > zona_objetivo:
        return (f"Vas en {marcha} marcha ({bpm:.0f} BPM) y hoy buscábamos la zona {zona_objetivo + 1}, un ritmo cómodo para "
                "construir resistencia. Baja un poco el ritmo hasta poder hablar sin jadear.")
    return (f"Vas en {marcha} marcha ({bpm:.0f} BPM) y hoy tocaba la zona {zona_objetivo + 1}. Sube un poco el ritmo "
            "para que el esfuerzo sea el planificado.")


@dataclass
class Susurrador:
    zona_objetivo: Optional[int] = None
    silenciado: bool = False
    _fuera_desde: Optional[float] = field(default=None, repr=False)
    _ultimo: Optional[float] = field(default=None, repr=False)

    def silenciar(self) -> None:
        self.silenciado = True

    def reiniciar(self) -> None:
        self._fuera_desde = self._ultimo = None
        self.silenciado = False

    def actualizar(self, t: float, bpm: Optional[float], fc_max: float) -> Optional[str]:
        """Texto del consejo si lleva > 4 min seguidos fuera de la zona objetivo; None en caso contrario."""
        if self.zona_objetivo is None or bpm is None or self.silenciado:
            self._fuera_desde = None
            return None
        from domain.zonas_actividad import zona_de
        zona = zona_de(bpm, fc_max)
        if zona == self.zona_objetivo:
            self._fuera_desde = None
            return None
        if self._fuera_desde is None:
            self._fuera_desde = t
        if (t - self._fuera_desde > FUERA_ZONA_S
                and (self._ultimo is None or t - self._ultimo >= ENFRIAMIENTO_SUSURRO_S)):
            self._ultimo = t
            return texto_susurro(bpm, zona, self.zona_objetivo)
        return None


# ------------------------------------------------------------------ 5. Replanificador «sin culpa»

ESTRES_ALTO_FRACCION = 0.25
ESTRES_ALTO_MIN_S = 1800.0


@dataclass(frozen=True)
class MotivoReajuste:
    sesion_saltada: Optional[str]
    estres_alto: bool

    def texto(self) -> str:
        if self.sesion_saltada and self.estres_alto:
            return f"Ayer no pudiste hacer «{self.sesion_saltada}» y además tuviste una jornada de mucho estrés."
        if self.sesion_saltada:
            return f"Ayer no pudiste hacer «{self.sesion_saltada}»."
        return "Ayer tuviste una jornada de mucho estrés."


def detectar_reajuste(repo, hoy: date) -> Optional[MotivoReajuste]:
    """Sesión planificada de ayer sin actividad registrada, o ayer en estrés alto (rojo) en Modo Escritorio."""
    ayer = hoy - timedelta(days=1)
    saltada = None
    try:
        plan = repo.conexion.execute("SELECT nombre FROM sesiones_planificadas WHERE usuario_id = ? AND fecha = ? ORDER BY id LIMIT 1",
                                     (repo.usuario_id, ayer.isoformat())).fetchone()
        if plan:
            ini = int(datetime.combine(ayer, datetime.min.time()).timestamp())
            if not repo.actividades_rango(ini, ini + DIA):
                saltada = plan[0]
    except Exception:
        pass
    alto = False
    try:
        f = repo.conexion.execute("SELECT calma_s, tension_s, estres_s FROM balance_carga_mental WHERE usuario = ? AND fecha = ?",
                                  (repo.usuario_id, ayer.isoformat())).fetchone()
        if f and sum(f) > 0:
            alto = f[2] / sum(f) >= ESTRES_ALTO_FRACCION and f[2] >= ESTRES_ALTO_MIN_S / 6 or f[2] >= ESTRES_ALTO_MIN_S
    except Exception:
        pass
    return MotivoReajuste(saltada, alto) if saltada or alto else None


@dataclass(frozen=True)
class CambioPlan:
    fecha: date
    nombre: str
    minutos_antes: float
    minutos_despues: float


def reajustar_semana(repo, hoy: date) -> list[CambioPlan]:
    """Acorta ~25 % las sesiones restantes de la semana y las baja a Zona 1–2 (sin recuperar lo perdido)."""
    domingo = hoy + timedelta(days=6 - hoy.weekday())
    c, u = repo.conexion, repo.usuario_id
    filas = c.execute("SELECT id, fecha, nombre, minutos, trimp FROM sesiones_planificadas WHERE usuario_id = ? AND fecha >= ? AND fecha <= ? "
                      "ORDER BY fecha, id", (u, hoy.isoformat(), domingo.isoformat())).fetchall()
    cambios = []
    with c:
        for id_, fecha, nombre, minutos, trimp in filas:
            nuevos = max(15.0, round(minutos * 0.75))
            nuevos = min(nuevos, minutos)
            nuevo_nombre = nombre if "Z1–2" in nombre else f"{nombre} (suave Z1–2)"
            c.execute("UPDATE sesiones_planificadas SET nombre = ?, minutos = ?, trimp = ?, plan = NULL WHERE id = ? AND usuario_id = ?",
                      (nuevo_nombre, nuevos, None if trimp is None else round(trimp * nuevos / minutos * 0.6, 1), id_, u))
            cambios.append(CambioPlan(date.fromisoformat(fecha), nuevo_nombre, minutos, nuevos))
    return cambios


def mensaje_reajuste(motivo: Optional[MotivoReajuste], cambios: Sequence[CambioPlan]) -> str:
    intro = (motivo.texto() + " " if motivo else "") + "Esto no es un fallo, es vida real: el cuerpo no se recupera compensando."
    if not cambios:
        return intro + " Esta semana no te quedan sesiones planificadas, así que no hay nada que ajustar. Descansa tranquilo."
    det = "; ".join(f"{c.fecha:%a %d}: {c.minutos_antes:.0f} → {c.minutos_despues:.0f} min" for c in cambios)
    return (intro + f" He reajustado {len(cambios)} sesión(es) de lo que queda de semana: más cortas y a Zona 1–2 ({det}). "
            "Sin culpa: lo importante es llegar descansado a la siguiente.")


# ------------------------------------------------------------------ 6. Informe clínico («Traductor Médico»)

def informe_clinico(repo, ahora_ts: int, dias: int = 30) -> str:
    """Dossier de texto del último mes para llevar a consulta (pulso basal, RMSSD, HRR, estrés, calidad ECG, observaciones)."""
    desde = ahora_ts - dias * DIA
    fisio = _por_dia(repo, desde, ahora_ts + 1)
    L = [f"INFORME DE SALUD CARDIOVASCULAR · VitaBand (banda pectoral ECG)",
         f"Periodo: {_dia(desde):%d/%m/%Y} – {_dia(ahora_ts):%d/%m/%Y} ({dias} días) · Generado el {datetime.fromtimestamp(ahora_ts):%d/%m/%Y %H:%M}", ""]
    ordenados = sorted(fisio.items())
    if ordenados:
        mitad = max(1, len(ordenados) // 2)
        fc = [v[0] for _, v in ordenados]
        rm = [v[1] for _, v in ordenados]
        L.append(f"PULSO BASAL (reposo): media {statistics.fmean(fc):.0f} BPM (mín {min(fc):.0f}, máx {max(fc):.0f}); "
                 f"1.ª mitad {statistics.fmean(fc[:mitad]):.0f} → 2.ª mitad {statistics.fmean(fc[mitad:] or fc):.0f} BPM.")
        m1, m2 = statistics.fmean(rm[:mitad]), statistics.fmean(rm[mitad:] or rm)
        tend = "estable" if abs(m2 - m1) / m1 < 0.05 else "al alza" if m2 > m1 else "a la baja"
        L.append(f"VARIABILIDAD CARDÍACA (RMSSD): media {statistics.fmean(rm):.0f} ms; tendencia {tend} "
                 f"({m1:.0f} → {m2:.0f} ms); {len(ordenados)} días con medida.")
    else:
        L.append("PULSO BASAL y RMSSD: sin mediciones en reposo en el periodo.")
    hrrs = RecuperacionSesiones(repo).rango(desde, ahora_ts + 1)
    h1 = [h.hrr_1m for _, h in hrrs if h.hrr_1m is not None]
    h2 = [h.hrr_2m for _, h in hrrs if h.hrr_2m is not None]
    L.append("RECUPERACIÓN POSTESFUERZO (HRR): " + (
        f"HRR 1' medio {statistics.fmean(h1):.0f} BPM" + (f" · HRR 2' medio {statistics.fmean(h2):.0f} BPM" if h2 else "") +
        f" ({len(hrrs)} sesiones)." if h1 else "sin sesiones con recuperación medida."))
    est = repo.conexion.execute("SELECT SUM(calma_s), SUM(tension_s), SUM(estres_s) FROM balance_carga_mental WHERE usuario = ? AND fecha >= ?",
                                (repo.usuario_id, _dia(desde).isoformat())).fetchone() if _tabla(repo, "balance_carga_mental") else None
    if est and est[0] is not None:
        L.append(f"ESTRÉS COGNITIVO (Modo Escritorio): {est[2] / 3600:.1f} h en estrés sostenido, {est[1] / 3600:.1f} h en tensión, "
                 f"{est[0] / 3600:.1f} h en foco calmado.")
    else:
        L.append("ESTRÉS COGNITIVO (Modo Escritorio): sin datos en el periodo.")
    cal = calidad_media(repo, desde, ahora_ts + 1)
    L.append(f"CALIDAD DEL TRAZADO ECG: {cal:.0f} % de intervalos R-R válidos de media." if cal is not None
             else "CALIDAD DEL TRAZADO ECG: sin ventanas R-R guardadas.")
    obs = []
    alerta = escudo_preventivo(repo, ahora_ts)
    if alerta:
        obs.append(alerta.texto(sencillo=False))
    if cal is not None and cal < 90:
        obs.append("Calidad de señal mejorable: humedecer los electrodos y ajustar la banda.")
    for h in RegistroHabitos(repo).correlaciones(ahora_ts)[:3]:
        obs.append("Hábitos: " + h.texto() + ".")
    L += ["", "OBSERVACIONES RELEVANTES:"] + ([f"- {o}" for o in obs] or ["- Sin hallazgos destacables."])
    L += ["", "Aviso: datos orientativos de un dispositivo de bienestar (no es un equipo médico); no sustituyen una valoración "
          "médica."]
    return "\n".join(L)


def _tabla(repo, nombre: str) -> bool:
    return bool(repo.conexion.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (nombre,)).fetchone())


# ------------------------------------------------------------------ Resumen para el Coach (online y offline)

def lineas_contexto(repo, ahora_ts: int) -> list[str]:
    """Líneas para el contexto del modelo: alerta, hallazgos de hábitos, HRR, calidad ECG y reajuste pendiente."""
    out = []
    a = _seguro(lambda: escudo_preventivo(repo, ahora_ts))
    if a:
        out.append("ALERTA PREVENTIVA ACTIVA: " + a.texto(sencillo=False) + " Rebajar la intensidad sugerida a descanso activo / Zona 1–2.")
    hs = _seguro(lambda: RegistroHabitos(repo).correlaciones(ahora_ts)) or []
    if hs:
        out.append("HÁBITOS ↔ CORAZÓN (comprobado con sus datos): " + "; ".join(h.texto() for h in hs[:4]) + ".")
    u = _seguro(lambda: RecuperacionSesiones(repo).ultimo())
    if u:
        out.append("Última recuperación postesfuerzo: " + u[1].texto(sencillo=False))
    cal = _seguro(lambda: calidad_media(repo, ahora_ts - 7 * DIA, ahora_ts + 1))
    if cal is not None:
        out.append(f"Calidad media del ECG (7 días): {cal:.0f} % de R-R válidos" + (" (señal con ruido: recomendar humedecer electrodos)." if cal < 90 else "."))
    m = _seguro(lambda: detectar_reajuste(repo, _dia(ahora_ts)))
    if m:
        out.append("REAJUSTE PENDIENTE (Modo Vida Real): " + m.texto() + " Ofrecer [ACCION:REAJUSTAR_SEMANA] con tono empático y sin culpa.")
    return out


def _seguro(f):
    try:
        return f()
    except Exception:
        return None


def completar_contexto(ctx, repo, ahora_ts: int) -> None:
    """Rellena los campos del ContextoCoach con datos reales de los 6 módulos (para el modo offline)."""
    ctx.alerta = _seguro(lambda: escudo_preventivo(repo, ahora_ts))
    ctx.hallazgos = [h.texto() for h in (_seguro(lambda: RegistroHabitos(repo).correlaciones(ahora_ts)) or [])[:4]]
    u = _seguro(lambda: RecuperacionSesiones(repo).ultimo())
    ctx.hrr = u[1] if u else None
    rr = _seguro(lambda: [x for w in repo.rr_rango(ahora_ts - 7 * DIA, ahora_ts + 1) for x in [analizar_calidad_ecg(w)] if x])
    ctx.calidad = None if not rr else CalidadEcg(statistics.fmean(c.pct_artefactos for c in rr), sum(c.aislados for c in rr),
                                                 sum(c.rafagas for c in rr), max((c.nivel for c in rr), key=["limpia", "ruido_aislado", "mal_contacto"].index))
    ctx.reajuste = _seguro(lambda: detectar_reajuste(repo, _dia(ahora_ts)))
