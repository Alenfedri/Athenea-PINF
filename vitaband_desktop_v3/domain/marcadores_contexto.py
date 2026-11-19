"""Cruce de marcadores de contexto («Café», «Mal descanso»…) con las métricas diarias.

Compara los días con una etiqueta frente a los demás días con datos. Solo informa cuando hay
muestra suficiente y la variación es relevante. Es orientativo, no un diagnóstico: una
coincidencia no demuestra causa.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping, Optional, Sequence

ETIQUETAS_RAPIDAS = ("Café", "Mal descanso", "Mareo", "Estrés")


@dataclass(frozen=True)
class UmbralesContexto:
    min_dias_marcados: int = 2
    min_dias_referencia: int = 3
    variacion_pct: float = 5.0


@dataclass(frozen=True)
class MetricasDia:
    fc_reposo: Optional[float] = None
    rmssd: Optional[float] = None
    rpm_reposo: Optional[float] = None


# (atributo, nombre, sentido «malo»: +1 si subir es peor, -1 si bajar es peor)
_METRICAS = (
    ("fc_reposo", "FC en reposo", +1, "subió", "bajó"),
    ("rmssd", "HRV (RMSSD)", -1, "subió", "bajó"),
    ("rpm_reposo", "frecuencia respiratoria en reposo", +1, "subió", "bajó"),
)


def _media(valores: Sequence[float]) -> float:
    return sum(valores) / len(valores)


def _pct(x: float) -> str:
    return f"{x:.0f}".replace(".", ",") + " %"


def lineas_cruce(
    etiqueta: str,
    dias_marcados: Sequence[date],
    metricas: Mapping[date, MetricasDia],
    umbrales: UmbralesContexto = UmbralesContexto(),
) -> list[str]:
    """Frases que comparan los días marcados con los habituales (vacío si no hay base)."""
    marcados = set(dias_marcados)
    lineas: list[str] = []
    for attr, nombre, _, sube, baja in _METRICAS:
        con = [v for d, m in metricas.items() if d in marcados and (v := getattr(m, attr)) is not None]
        sin = [v for d, m in metricas.items() if d not in marcados and (v := getattr(m, attr)) is not None]
        if len(con) < umbrales.min_dias_marcados or len(sin) < umbrales.min_dias_referencia:
            continue
        ref = _media(sin)
        if ref <= 0:
            continue
        var = (_media(con) - ref) / ref * 100
        if abs(var) < umbrales.variacion_pct:
            continue
        verbo = sube if var > 0 else baja
        lineas.append(
            f"Los días marcados con '{etiqueta}' tu {nombre} {verbo} un {_pct(abs(var))} "
            f"respecto a tu media habitual ({len(con)} días marcados frente a {len(sin)} sin marcar).")
    return lineas
