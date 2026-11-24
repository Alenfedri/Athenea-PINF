"""IA local de sesión (reglas + numpy, sin red, < 50 ms): auto-etiquetado de la disciplina y veredicto ejecutivo.

Heurísticas fisiológicas orientativas, no validadas con una banda real. El auto-etiquetado solo actúa la primera
vez que se procesa una sesión sin disciplina; la elección manual del usuario (o su decisión de dejarla vacía) manda.
"""

from __future__ import annotations

import statistics
from typing import Optional, Sequence

import numpy as np

from domain.zonas_actividad import FC_MAX_REFERENCIA, zona_de

MIN_DURACION_S = 180
SALTO_SERIE_BPM = 20.0          # amplitud mínima pico-valle para contar una serie de fuerza
MIN_MUESTRAS_POR_SALTO = 15     # un ruido aleatorio cambia de dirección cada pocas muestras
MIN_SALTOS = 6                  # 3 ciclos pico-valle
UMBRAL_DESACOPLO_PCT = 5.0
RATIO_OPTIMO, RATIO_BAJO = 4.0, 3.0


def _suave(x: Sequence[float], n: int = 5) -> np.ndarray:
    a = np.asarray(x, float)
    if a.size < n:
        return a
    return np.convolve(a, np.ones(n) / n, mode="valid")


def _saltos(bpm: np.ndarray, amplitud: float) -> int:
    """Cambios de dirección de amplitud ≥ ``amplitud`` BPM (zigzag): picos y valles alternos."""
    if bpm.size < 3:
        return 0
    cuenta, extremo, subiendo = 0, bpm[0], None
    for v in bpm[1:]:
        if subiendo is None:
            if abs(v - extremo) >= amplitud:
                subiendo = v > extremo
                cuenta += 1
                extremo = v
        elif subiendo:
            if v > extremo:
                extremo = v
            elif extremo - v >= amplitud:
                subiendo, extremo = False, v
                cuenta += 1
        else:
            if v < extremo:
                extremo = v
            elif v - extremo >= amplitud:
                subiendo, extremo = True, v
                cuenta += 1
    return cuenta


def _deriva(x: Sequence[float]) -> float:
    """Último cuarto menos primer cuarto."""
    a = np.asarray(x, float)
    q = max(1, a.size // 4)
    return float(a[-q:].mean() - a[:q].mean())


def clasificar_disciplina_automatica(serie_bpm: Sequence[float], serie_rpm: Optional[Sequence[float]] = None,
                                     serie_temp: Optional[Sequence[float]] = None, duracion_s: float = 0,
                                     fc_max: float = FC_MAX_REFERENCIA) -> str:
    """'Fuerza' | 'Carrera' | 'Rodillo/Ciclismo' | 'Caminata' | 'Otra' según la cinética de la sesión."""
    bpm = np.asarray([b for b in serie_bpm if b and b > 0], float)
    if duracion_s < MIN_DURACION_S or bpm.size < 12:
        return "Otra"
    rpm = np.asarray([r for r in (serie_rpm or []) if r and r > 0], float)
    temp = np.asarray([t for t in (serie_temp or []) if t is not None], float)
    zonas = np.array([zona_de(b, fc_max) for b in bpm])
    tras = bpm[bpm.size // 10:]                               # sin el calentamiento
    z_tras = zonas[bpm.size // 10:]
    f_alta = float((z_tras >= 2).mean())                      # Z3–Z5
    f_baja = float((z_tras <= 1).mean())                      # Z1–Z2
    f_media = float(((z_tras >= 1) & (z_tras <= 3)).mean())   # Z2–Z4
    cv = float(tras.std() / tras.mean())
    rpm_med = float(rpm.mean()) if rpm.size >= 5 else None
    rpm_cv = float(rpm.std() / rpm.mean()) if rpm_med else None

    # Fuerza: dientes de sierra (series y recuperaciones), FC media moderada, mucha variabilidad
    ventana = int(min(15, max(1, round(10 * bpm.size / duracion_s))))            # ≈ 10 s de suavizado
    saltos = _saltos(_suave(bpm, ventana), SALTO_SERIE_BPM)
    if (saltos >= MIN_SALTOS and bpm.size / saltos >= MIN_MUESTRAS_POR_SALTO          # series, no ruido
            and cv >= 0.08 and bpm.mean() < 0.85 * fc_max):
        return "Fuerza"
    # Rodillo: progresión gradual del pulso + deriva térmica positiva sostenida + RPM moderadas-altas
    if (temp.size >= 12 and _deriva(temp) >= 0.5 and _deriva(bpm) >= 4 and f_media >= 0.7
            and (rpm_med is None or 14 <= rpm_med <= 32)):
        return "Rodillo/Ciclismo"
    # Carrera: pulso alto y sostenido (Z3–Z5) y poca dispersión; cadencia respiratoria alta y estable
    if f_alta >= 0.6 and cv <= 0.10 and (rpm_med is None or (rpm_med >= 22 and rpm_cv <= 0.25)):
        return "Carrera"
    # Caminata: pulso bajo-moderado estable (Z1–Z2) y respiración baja
    if f_baja >= 0.75 and cv <= 0.12 and (rpm_med is None or rpm_med < 20):
        return "Caminata"
    return "Otra"


def desacoplamiento_pct(serie_bpm: Sequence[float]) -> Optional[float]:
    """Deriva del pulso entre la 1.ª y la 2.ª mitad (tras el 10 % de calentamiento), en %."""
    b = np.asarray([x for x in serie_bpm if x and x > 0], float)
    b = b[b.size // 10:]
    if b.size < 20:
        return None
    m = b.size // 2
    a1, a2 = b[:m].mean(), b[m:].mean()
    return float((a2 - a1) / a1 * 100.0)


def generar_veredicto_sesion(datos: dict) -> str:
    """Diagnóstico ejecutivo de 3 líneas. ``datos``: trimp, rpe, ratio (BPM/RPM), desacoplamiento_pct,
    deriva_termica_c, duracion_s (todas opcionales)."""
    trimp, rpe = datos.get("trimp"), datos.get("rpe")
    ratio, desac = datos.get("ratio"), datos.get("desacoplamiento_pct")
    dterm = datos.get("deriva_termica_c")
    minutos = max(1.0, (datos.get("duracion_s") or 0) / 60.0)
    alto = trimp is not None and (trimp >= 150 or trimp / minutos >= 2.8)
    fatiga_oculta = rpe is not None and rpe >= 7 and trimp is not None and not alto
    # 1) Carga real vs. percepción
    if trimp is None:
        l1 = "Carga: sin TRIMP calculable en esta sesión."
    elif rpe is None:
        l1 = f"Carga: TRIMP {trimp:.0f} ({'alta' if alto else 'baja-moderada'}); sin RPE para contrastar la percepción."
    elif fatiga_oculta:
        l1 = f"Carga: RPE {rpe} con TRIMP {trimp:.0f} bajo-moderado → posible fatiga oculta (sueño, estrés o recuperación incompleta)."
    elif alto and rpe <= 6:
        l1 = f"Carga: TRIMP {trimp:.0f} alto con RPE {rpe} contenido → buena asimilación del esfuerzo."
    else:
        l1 = f"Carga: TRIMP {trimp:.0f} y RPE {rpe} coherentes entre sí."
    # 2) Eficiencia cardiorrespiratoria y térmica
    ratio_bajo = ratio is not None and ratio < RATIO_BAJO
    deriva = desac is not None and desac >= UMBRAL_DESACOPLO_PCT
    partes = []
    if ratio is not None:
        partes.append(f"BPM/RPM {ratio:.1f}:1 (" + ("fatiga respiratoria temprana, < 3:1" if ratio_bajo else
                      "óptimo ≈ 4:1" if ratio >= 3.5 else "aceptable") + ")")
    if desac is not None:
        partes.append(f"desacoplamiento {desac:.1f} % (" + ("deriva ≥ 5 %" if deriva else "base sólida < 5 %") + ")")
    if dterm is not None and dterm >= 0.5:
        partes.append(f"deriva térmica +{dterm:.1f} °C")
    l2 = "Eficiencia: " + (", ".join(partes) if partes else "sin datos de respiración ni de deriva suficientes") + "."
    # 3) Recomendación inmediata
    if fatiga_oculta or ratio_bajo or deriva:
        l3 = "Recomendación: priorizar recuperación activa o una sesión de Coherencia Cardíaca antes de otra carga intensa."
    elif trimp is None and ratio is None and desac is None:
        l3 = "Recomendación: registra más datos (RPE y sesiones con respiración) para un veredicto fiable."
    else:
        l3 = "Recomendación: respuesta eficiente; disponible para una sesión de calidad."
    return "\n".join((l1, l2, l3))


# ------------------------------------------------------------------ Persistencia (cuenta activa)

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS veredictos_sesion (
    usuario   INTEGER NOT NULL,
    sesion_id INTEGER NOT NULL,
    veredicto TEXT    NOT NULL,
    PRIMARY KEY (usuario, sesion_id)
);
"""
# Si la base tiene la tabla de cuentas, el borrado de una cuenta arrastra también sus veredictos.
_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS borrar_veredictos_usuario AFTER DELETE ON usuarios
BEGIN DELETE FROM veredictos_sesion WHERE usuario = OLD.id; END;
"""


def datos_de_sesion(detalle, rpe: Optional[int]) -> dict:
    from services import metricas_avanzadas as ma
    from services import ratio_pulso_resp as rr
    ms = sorted(detalle.mediciones, key=lambda m: m.ts)
    r, _ = rr.ratio_medio(ms)
    temps = [m.temp_c for m in ms if m.temp_c is not None]
    return {"trimp": ma.trimp(ms), "rpe": rpe, "ratio": r, "desacoplamiento_pct": desacoplamiento_pct([m.bpm for m in ms]),
            "deriva_termica_c": _deriva(temps) if len(temps) >= 12 else None, "duracion_s": detalle.actividad.duracion_s}


class IaLocalSesion:
    def __init__(self, repo):
        self._repo, self._c, self._u = repo, repo.conexion, repo.usuario_id
        with self._c:
            self._c.executescript(_ESQUEMA)
            if self._c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='usuarios'").fetchone():
                self._c.executescript(_TRIGGER)

    def veredicto_guardado(self, sesion_id: int) -> Optional[str]:
        f = self._c.execute("SELECT veredicto FROM veredictos_sesion WHERE usuario = ? AND sesion_id = ?",
                            (self._u, sesion_id)).fetchone()
        return None if f is None else f[0]

    def _detalle(self, sesion_id: int):
        from types import SimpleNamespace
        a = self._repo.obtener_actividad(sesion_id)
        return None if a is None else SimpleNamespace(actividad=a, mediciones=self._repo.mediciones_de_actividad(sesion_id))

    def procesar(self, sesion_id: int, regenerar: bool = False) -> Optional[str]:
        """Primera vez: auto-etiqueta la disciplina si falta y cachea el veredicto. Devuelve el veredicto."""
        previo = self.veredicto_guardado(sesion_id)
        if previo is not None and not regenerar:
            return previo
        d = self._detalle(sesion_id)
        if d is None:
            return None
        if previo is None and sesion_id not in self._repo.disciplinas():     # nunca pisa la elección del usuario
            ms = sorted(d.mediciones, key=lambda m: m.ts)
            disc = clasificar_disciplina_automatica([m.bpm for m in ms], [m.rpm for m in ms],
                                                    [m.temp_c for m in ms], d.actividad.duracion_s)
            self._repo.guardar_disciplina(sesion_id, disc)
        nota = self._repo.nota_sesion(sesion_id)
        texto = generar_veredicto_sesion(datos_de_sesion(d, nota[0] if nota else None))
        with self._c:
            self._c.execute("INSERT OR REPLACE INTO veredictos_sesion (usuario, sesion_id, veredicto) VALUES (?, ?, ?)",
                            (self._u, sesion_id, texto))
        return texto

    def procesar_pendientes(self, limite: int = 20) -> int:
        """Procesa las últimas ``limite`` actividades sin veredicto (tras una sincronización)."""
        hechos = {f[0] for f in self._c.execute("SELECT sesion_id FROM veredictos_sesion WHERE usuario = ?", (self._u,))}
        ids = [f[0] for f in self._c.execute(
            "SELECT id FROM actividades WHERE usuario_id = ? ORDER BY inicio_ts DESC", (self._u,)) if f[0] not in hechos]
        for i in ids[:limite]:
            self.procesar(i)
        return min(len(ids), limite)
