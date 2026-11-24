"""Cálculos fisiológicos de la banda pectoral: Keytel, vueltas, test ortostático, RPE y sesión en directo.

Son estimaciones orientativas, no un diagnóstico; no están validadas con una banda real.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Optional, Sequence

from domain import hrv
from domain.modelos import Medicion
from domain.zonas_actividad import FC_MAX_REFERENCIA, repartir_zonas

# ------------------------------------------------------------------ Keytel

HOMBRE, MUJER = "Hombre", "Mujer"
PESO_REFERENCIA_KG = {HOMBRE: 70.0, MUJER: 60.0}      # peso de referencia saludable si no hay peso registrado


@dataclass(frozen=True)
class PerfilFisiologico:
    edad: Optional[int] = None
    sexo: Optional[str] = None
    peso_kg: Optional[float] = None
    objetivo_semanal_min: int = 150

    @property
    def completo(self) -> bool:
        return bool(self.edad) and self.sexo in PESO_REFERENCIA_KG


def kcal_keytel(bpm_medio: Optional[float], minutos: float, perfil: Optional[PerfilFisiologico]) -> Optional[float]:
    """Ecuación de Keytel (2005). None si faltan edad o sexo. Nunca devuelve un valor negativo."""
    if perfil is None or not perfil.completo or bpm_medio is None or not math.isfinite(bpm_medio) or minutos <= 0:
        return None
    peso = perfil.peso_kg if perfil.peso_kg and perfil.peso_kg > 0 else PESO_REFERENCIA_KG[perfil.sexo]
    if perfil.sexo == HOMBRE:
        kj_min = -55.0969 + 0.6309 * bpm_medio + 0.1988 * peso + 0.2017 * perfil.edad
    else:
        kj_min = -20.4022 + 0.4472 * bpm_medio - 0.1263 * peso + 0.074 * perfil.edad
    return max(0.0, kj_min / 4.184) * minutos


def kcal_actividad(mediciones: Sequence[Medicion], perfil: Optional[PerfilFisiologico]) -> Optional[float]:
    """kcal de una sesión: duración activa (sin huecos) × BPM medio."""
    rep = repartir_zonas(mediciones)
    bpms = [m.bpm for m in mediciones if m.bpm and m.bpm > 0]
    if rep is None or not bpms:
        return None
    return kcal_keytel(statistics.fmean(bpms), rep.total_s / 60.0, perfil)


# ------------------------------------------------------------------ Vueltas

@dataclass(frozen=True)
class Vuelta:
    numero: int
    duracion_s: int
    bpm_medio: Optional[float]
    rpm_medio: Optional[float]


def desglose_vueltas(inicio_ts: int, fin_ts: int, marcas: Sequence[int], mediciones: Sequence[Medicion]) -> list[Vuelta]:
    """Tramos entre marcas: [inicio, m1), [m1, m2)… [mN, fin]. Sin marcas dentro de la sesión, lista vacía."""
    dentro = sorted({m for m in marcas if inicio_ts < m < fin_ts})
    if not dentro:
        return []
    limites = [inicio_ts, *dentro, fin_ts]
    salida = []
    for i, (a, b) in enumerate(zip(limites, limites[1:]), start=1):
        ms = [m for m in mediciones if a <= m.ts < b or (b == fin_ts and m.ts == fin_ts)]
        bpm = [m.bpm for m in ms if m.bpm and m.bpm > 0]
        rpm = [m.rpm for m in ms if m.rpm is not None]
        salida.append(Vuelta(i, int(b - a), statistics.fmean(bpm) if bpm else None,
                             statistics.fmean(rpm) if rpm else None))
    return salida


# ------------------------------------------------------------------ Test ortostático

FASE_REPOSO_S, DURACION_TEST_S = 120, 180
DELTA_MARCADO, DELTA_BAJO = 30.0, 10.0
FC_ESTABLE_S, PICO_S, RMSSD_VENTANA_S = 30, 30, 30


@dataclass(frozen=True)
class ResultadoOrtostatico:
    fc_basal: float
    rmssd_basal: Optional[float]
    fc_pico: float
    fc_estable: Optional[float]
    rmssd_pie: Optional[float]
    delta_fc: float                      # pico de pie − basal
    valoracion: str


def fase_ortostatica(t_rel: float) -> int:
    """0 = en reposo, 1 = de pie, 2 = terminado."""
    return 0 if t_rel < FASE_REPOSO_S else 1 if t_rel < DURACION_TEST_S else 2


def valorar_ortostatico(delta_fc: float, rmssd_basal: Optional[float]) -> str:
    if delta_fc >= DELTA_MARCADO:
        texto = (f"Respuesta ortostática marcada (ΔFC {delta_fc:.0f} BPM): posible fatiga, deshidratación o "
                 "recuperación autonómica incompleta. Repítelo descansado e hidratado.")
    elif delta_fc >= DELTA_BAJO:
        texto = f"Respuesta ortostática normal (ΔFC {delta_fc:.0f} BPM): recuperación autonómica adecuada."
    else:
        texto = (f"Respuesta ortostática débil (ΔFC {delta_fc:.0f} BPM): poco habitual; puede indicar fatiga. "
                 "Compárala con tu propia línea base.")
    if rmssd_basal is not None:
        texto += f" HRV basal: {rmssd_basal:.0f} ms ({hrv.clasificar(rmssd_basal).lower()})."
    return texto + " Orientativo, no es un diagnóstico médico."


def _rmssd(ecg: Sequence[tuple[float, float]], desde: float, hasta: float) -> Optional[float]:
    ventana = [v for t, v in ecg if desde <= t < hasta]
    if len(ventana) < hrv.FS_HZ * 10:
        return None
    r = hrv.evaluar_ventana(ventana)
    return None if r is None else r.rmssd_ms


def evaluar_ortostatico(bpm: Sequence[tuple[float, float]], ecg: Sequence[tuple[float, float]]
                        ) -> Optional[ResultadoOrtostatico]:
    """``bpm`` y ``ecg``: (segundos desde el inicio del test, valor). None si faltan datos de FC."""
    basal = [b for t, b in bpm if FASE_REPOSO_S - 60 <= t < FASE_REPOSO_S and b > 0]
    pico = [b for t, b in bpm if FASE_REPOSO_S <= t < FASE_REPOSO_S + PICO_S and b > 0]
    estable = [b for t, b in bpm if DURACION_TEST_S - FC_ESTABLE_S <= t < DURACION_TEST_S and b > 0]
    if not basal or not pico:
        return None
    fc_basal, fc_pico = statistics.fmean(basal), max(pico)
    rmssd_basal = _rmssd(ecg, FASE_REPOSO_S - 60, FASE_REPOSO_S)
    delta = fc_pico - fc_basal
    return ResultadoOrtostatico(
        fc_basal, rmssd_basal, fc_pico, statistics.fmean(estable) if estable else None,
        _rmssd(ecg, DURACION_TEST_S - RMSSD_VENTANA_S, DURACION_TEST_S), delta,
        valorar_ortostatico(delta, rmssd_basal))


# ------------------------------------------------------------------ Cruce RPE – pulso

RPE_SUAVE, RPE_DURO = 4, 8
FC_ALTA_PCT, FC_CONTENIDA_PCT = 75.0, 70.0


def cruce_rpe(rpe: Optional[int], fc_media: Optional[float], previas: Sequence[tuple[int, float]],
              fc_max: float = FC_MAX_REFERENCIA) -> Optional[str]:
    """Observación si el esfuerzo percibido y el pulso no cuadran. ``previas``: (rpe, fc_media) de las
    sesiones anteriores valoradas (más recientes primero)."""
    if rpe is None or fc_media is None or fc_media <= 0:
        return None
    pct = fc_media / fc_max * 100
    if rpe <= RPE_SUAVE and pct >= FC_ALTA_PCT:
        return (f"Posible desajuste esfuerzo-pulso: la sesión se valoró suave (RPE {rpe}) pero la FC media fue "
                f"del {pct:.0f} % de la FC máx. Puede indicar fatiga acumulada, calor o falta de recuperación.")
    if rpe >= RPE_DURO and pct < FC_CONTENIDA_PCT:
        repetidas = [r for r, f in previas[:2] if r >= RPE_DURO and f / fc_max * 100 < FC_CONTENIDA_PCT]
        if repetidas:
            return (f"Posible fatiga acumulada: se repite un esfuerzo percibido alto (RPE {rpe}) con el pulso "
                    f"contenido (FC media del {pct:.0f} % de la FC máx.). Considera descansar.")
    return None


# ------------------------------------------------------------------ Sesión en directo y auto-pausa

PAUSA_TRAS_S = 5.0
MAX_DT_S = 2.0
TEXTO_PAUSA = "PAUSA AUTOMÁTICA (Sin contacto)"


class SesionDirecto:
    """Sesión mientras la banda está CONECTADA: tiempo efectivo y medias sin las muestras sin contacto.

    Si el contacto se pierde más de 5 s seguidos, pasa a pausa: el tiempo efectivo se detiene y el tramo
    sin contacto no cuenta. Cortes de ≤ 5 s siguen contando como tiempo, pero sus muestras no entran
    en las medias.
    """

    def __init__(self):
        self.reiniciar()

    def reiniciar(self) -> None:
        self.activa = False
        self.pausada = False
        self.vueltas = 0
        self._acum = 0.0
        self._pend = 0.0
        self._sin_contacto = 0.0
        self._w_bpm = self._s_bpm = self._w_rpm = self._s_rpm = 0.0
        self._ultimo: Optional[float] = None

    @property
    def tiempo_efectivo_s(self) -> float:
        return self._acum + (0.0 if self.pausada else self._pend)

    @property
    def bpm_medio(self) -> Optional[float]:
        return self._s_bpm / self._w_bpm if self._w_bpm > 0 else None

    @property
    def rpm_medio(self) -> Optional[float]:
        return self._s_rpm / self._w_rpm if self._w_rpm > 0 else None

    @property
    def estado(self) -> str:
        return TEXTO_PAUSA if self.pausada else ""

    def actualizar(self, conectado: bool, contacto: bool, bpm: Optional[float], rpm: Optional[float],
                   ahora: float) -> None:
        if not conectado:
            self.activa = False
            self.pausada = False
            self._ultimo = None
            return
        if not self.activa:
            self.reiniciar()
            self.activa, self._ultimo = True, ahora
            return
        dt = min(max(ahora - (self._ultimo if self._ultimo is not None else ahora), 0.0), MAX_DT_S)
        self._ultimo = ahora
        if not contacto:
            self._sin_contacto += dt
            self._pend += dt
            if self._sin_contacto > PAUSA_TRAS_S:
                self.pausada = True
            return
        if self._sin_contacto > 0 and not self.pausada:
            self._acum += self._pend                      # corte breve: cuenta como tiempo
        self._pend = self._sin_contacto = 0.0
        self.pausada = False
        self._acum += dt
        if bpm is not None and bpm > 0:
            self._w_bpm += dt
            self._s_bpm += bpm * dt
        if rpm is not None and rpm > 0:
            self._w_rpm += dt
            self._s_rpm += rpm * dt
