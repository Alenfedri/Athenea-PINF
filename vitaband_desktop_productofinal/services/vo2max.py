"""VO2máx por el método de Uth, clasificación por edad y sexo y edad cardiovascular estimada.

Son estimaciones orientativas (referencias aproximadas), no un diagnóstico.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional, Sequence

import numpy as np

from domain.modelos import NIVEL_REPOSO
from services.calculos_fisiologicos import PerfilFisiologico

MIN_MUESTRAS_REPOSO = 20
VENTANA_FCMAX_DIAS = 90
FCMAX_RANGO = (120.0, 220.0)

# VO2máx de referencia (ml/kg/min) a los 20 años y descenso por año de edad
_NORMA = {"Hombre": (48.0, 0.45), "Mujer": (40.0, 0.36)}
CATEGORIAS = ("Muy baja", "Baja", "Media", "Buena", "Excelente")
_CORTES = (0.75, 0.90, 1.10, 1.30)          # cocientes sobre la media de su edad y sexo


def vo2max_uth(fc_max: Optional[float], fc_reposo: Optional[float]) -> Optional[float]:
    """VO2máx = 15,3 × (FCmáx / FCreposo)."""
    if not fc_max or not fc_reposo or fc_max <= 0 or fc_reposo <= 0 or fc_reposo >= fc_max:
        return None
    return 15.3 * fc_max / fc_reposo


def fc_max_tanaka(edad: int) -> float:
    return 208.0 - 0.7 * edad


def vo2_referencia(edad: int, sexo: str) -> Optional[float]:
    if sexo not in _NORMA:
        return None
    base, pendiente = _NORMA[sexo]
    return max(10.0, base - pendiente * (edad - 20))


def clasificar(vo2: float, edad: int, sexo: str) -> Optional[str]:
    ref = vo2_referencia(edad, sexo)
    if ref is None:
        return None
    r = vo2 / ref
    return CATEGORIAS[sum(r >= c for c in _CORTES)]


def edad_cardiovascular(vo2: float, sexo: str) -> Optional[int]:
    """Edad cuya media de VO2máx coincide con la del usuario (limitada a 18–90)."""
    if sexo not in _NORMA:
        return None
    base, pendiente = _NORMA[sexo]
    return int(round(min(90.0, max(18.0, 20 + (base - vo2) / pendiente))))


@dataclass(frozen=True)
class EstimacionVo2:
    vo2: float
    fc_max: float
    fc_reposo: float
    fc_max_observada: bool
    categoria: Optional[str]
    edad_cv: Optional[int]
    edad: Optional[int]

    def texto(self) -> str:
        partes = [f"VO2máx ≈ {self.vo2:.1f} ml/kg/min"]
        if self.categoria:
            partes.append(f"nivel {self.categoria.lower()}")
        if self.edad_cv is not None and self.edad:
            partes.append(f"edad cardiovascular ≈ {self.edad_cv} (edad real {self.edad})")
        partes.append(f"FCmáx {self.fc_max:.0f} ({'observada' if self.fc_max_observada else 'Tanaka'}) · "
                      f"FC reposo {self.fc_reposo:.0f}")
        return " · ".join(partes)


def fc_reposo(mediciones: Sequence) -> Optional[float]:
    """Percentil 5 del pulso en reposo (robusto a picos); None con pocas muestras."""
    v = [m.bpm for m in mediciones if m.bpm and m.bpm > 0 and m.nivel_actividad == NIVEL_REPOSO]
    return float(np.percentile(v, 5)) if len(v) >= MIN_MUESTRAS_REPOSO else None


def fc_max_observada(mediciones: Sequence) -> Optional[float]:
    v = [m.bpm for m in mediciones if m.bpm and FCMAX_RANGO[0] <= m.bpm <= FCMAX_RANGO[1]]
    return float(np.percentile(v, 99.5)) if len(v) >= MIN_MUESTRAS_REPOSO else None


def estimar(reposo: Optional[float], maximo_obs: Optional[float], perfil: Optional[PerfilFisiologico]
            ) -> Optional[EstimacionVo2]:
    """Necesita FC de reposo; la FCmáx es la observada o, si no hay, la de Tanaka con la edad del perfil."""
    edad = perfil.edad if perfil and perfil.edad else None
    sexo = perfil.sexo if perfil and perfil.sexo in _NORMA else None
    fcm, observada = maximo_obs, True
    if fcm is None and edad:
        fcm, observada = fc_max_tanaka(edad), False
    vo2 = vo2max_uth(fcm, reposo)
    if vo2 is None:
        return None
    return EstimacionVo2(
        vo2, fcm, reposo, observada,
        clasificar(vo2, edad, sexo) if edad and sexo else None,
        edad_cardiovascular(vo2, sexo) if sexo else None, edad)


def _inicio_mes(d: date) -> date:
    return d.replace(day=1)


def _mes_anterior(d: date) -> date:
    return (d.replace(day=1) - timedelta(days=1)).replace(day=1)


def evolucion_mensual(repo, perfil: Optional[PerfilFisiologico], hoy: date, meses: int = 6
                      ) -> list[tuple[str, EstimacionVo2]]:
    """Un valor por mes con datos (de más antiguo a más reciente). FC reposo del mes; FCmáx de los
    90 días anteriores al fin de ese mes."""
    salida = []
    ini = _inicio_mes(hoy)
    for _ in range(meses):
        fin = (ini.replace(day=28) + timedelta(days=4)).replace(day=1)
        t0, t1 = int(datetime(ini.year, ini.month, 1).timestamp()), int(datetime(fin.year, fin.month, 1).timestamp())
        reposo = fc_reposo(repo.mediciones_rango(t0, t1))
        if reposo is not None:
            historia = repo.mediciones_rango(t1 - VENTANA_FCMAX_DIAS * 86400, t1)
            est = estimar(reposo, fc_max_observada(historia), perfil)
            if est is not None:
                salida.append((f"{ini:%Y-%m}", est))
        ini = _mes_anterior(ini)
    return salida[::-1]
