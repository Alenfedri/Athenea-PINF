"""Motor de observaciones orientativas (RF-22, 23, 25, 47, 48, 49).

Todo el texto que sale de aquí es INFORMATIVO: no es un diagnóstico médico.
Los umbrales son valores de referencia generales, configurables en ``Umbrales``,
y no están validados clínicamente.

Reglas generales:
  * Se interpreta cada valor según su contexto (RF-25): en reposo (nivel 0) o en
    actividad (niveles 1 y 2). Los registros sin clasificar no se usan para
    valorar, para no aplicar el mismo criterio a situaciones distintas.
  * Si hay pocos datos, se dice, en vez de inventar una conclusión.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Mapping, Optional, Sequence

from domain.analisis import (
    detectar_interrupciones,
    estadisticas,
    umbral_interrupcion,
)
from domain.modelos import (
    NIVEL_INTENSA,
    NIVEL_MEDIA,
    NIVEL_REPOSO,
    Actividad,
    Medicion,
)

DESCARGO = "Observación orientativa de carácter informativo; no constituye un diagnóstico médico."


@dataclass(frozen=True)
class Umbrales:
    fc_reposo_alta: float = 100.0
    fc_reposo_baja: float = 45.0
    fr_reposo_alta: float = 20.0
    fr_reposo_baja: float = 10.0
    temp_alta: float = 37.5
    temp_baja: float = 35.0
    min_registros: int = 6              # mínimo de registros para valorar un contexto
    min_registros_franja: int = 3       # idem, por franja horaria
    dif_franja_bpm: float = 8.0         # diferencia entre franjas para hablar de patrón
    min_dias_patron: int = 3
    proporcion_patron: float = 0.6
    esfuerzo_ligero: float = 0.30       # FC media sobre la de reposo
    esfuerzo_moderado: float = 0.70


FRANJAS = (
    ("de madrugada (0-6 h)", 0, 6),
    ("por la mañana (6-12 h)", 6, 12),
    ("por la tarde (12-18 h)", 12, 18),
    ("por la noche (18-24 h)", 18, 24),
)


# --------------------------------------------------
# FORMATO
# --------------------------------------------------

def _n(x: float, dec: int = 1) -> str:
    return f"{x:.{dec}f}".replace(".", ",")


def _con_signo(x: float) -> str:
    return f"{x:+.1f}".replace(".", ",")


def formatear_duracion(segundos: int) -> str:
    segundos = max(0, int(segundos))
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    if h:
        return f"{h} h {m:02d} min"
    if m:
        return f"{m} min {s:02d} s"
    return f"{s} s"


# --------------------------------------------------
# CONTEXTO
# --------------------------------------------------

def en_reposo(m: Medicion) -> bool:
    return m.nivel_actividad == NIVEL_REPOSO


def en_actividad(m: Medicion) -> bool:
    return m.nivel_actividad in (NIVEL_MEDIA, NIVEL_INTENSA)


def _valores(ms: Sequence[Medicion], attr: str) -> list[float]:
    return [getattr(m, attr) for m in ms if getattr(m, attr) is not None]


def fc_reposo(mediciones: Sequence[Medicion], umbrales: Umbrales = Umbrales()) -> Optional[float]:
    """FC media en reposo, o None si hay pocos registros en reposo."""
    reposo = [m.bpm for m in mediciones if en_reposo(m)]
    if len(reposo) < umbrales.min_registros:
        return None
    return sum(reposo) / len(reposo)


# --------------------------------------------------
# PATRONES RECURRENTES (RF-25)
# --------------------------------------------------

def detectar_patrones(
    dias: Mapping[date, Sequence[Medicion]], umbrales: Umbrales = Umbrales()
) -> list[str]:
    """Patrones que se repiten en varios días, solo con registros en reposo."""
    cuenta: Counter[str] = Counter()
    validos = 0

    for _, ms in dias.items():
        medias: dict[str, float] = {}
        for nombre, a, b in FRANJAS:
            vals = [m.bpm for m in ms if en_reposo(m) and a <= m.instante.hour < b]
            if len(vals) >= umbrales.min_registros_franja:
                medias[nombre] = sum(vals) / len(vals)
        if len(medias) >= 2:
            validos += 1
            alta = max(medias, key=medias.get)
            if medias[alta] - min(medias.values()) >= umbrales.dif_franja_bpm:
                cuenta[alta] += 1

    if validos < umbrales.min_dias_patron or not cuenta:
        return []

    franja, veces = cuenta.most_common(1)[0]
    if veces / validos >= umbrales.proporcion_patron:
        return [
            f"Patrón recurrente: en reposo, tu FC suele ser más alta {franja} "
            f"({veces} de {validos} días con datos suficientes)."
        ]
    return []


# --------------------------------------------------
# OBSERVACIÓN DIARIA (RF-23, 47)
# --------------------------------------------------

def observacion_diaria(
    dia: date,
    mediciones: Sequence[Medicion],
    anteriores: Mapping[date, Sequence[Medicion]],
    intervalo_s: float,
    fin_ts: int,
    umbrales: Umbrales = Umbrales(),
    lineas_extra: Sequence[str] = (),
) -> Optional[list[str]]:
    """Resumen de evolución de un día del historial periódico; None si no hay datos.

    ``lineas_extra`` (p. ej. la recuperación por HRV) se añade antes del descargo.
    """
    if not mediciones:
        return None

    ms = sorted(mediciones, key=lambda m: m.ts)
    inicio_dia = int(datetime(dia.year, dia.month, dia.day).timestamp())
    fin_dia = int((datetime(dia.year, dia.month, dia.day) + timedelta(days=1)).timestamp())
    fin_efectivo = min(fin_dia, fin_ts)

    lineas: list[str] = []

    # -- Cobertura e interrupciones (RF-27)
    ts = [m.ts for m in ms]
    horas = len({datetime.fromtimestamp(t).hour for t in ts})
    lineas.append(f"Registros: {len(ms)} mediciones periódicas repartidas en {horas} h distintas del día.")
    huecos = detectar_interrupciones(ts, inicio_dia, fin_efectivo, umbral_interrupcion(ts, 3 * intervalo_s))
    if huecos:
        minutos = sum(h.duracion_s for h in huecos) // 60
        lineas.append(
            f"Interrupciones: {len(huecos)} periodo(s) sin datos, {minutos} min en total "
            f"(no se han contado como mediciones)."
        )

    # -- Reposo (contexto principal para valorar)
    reposo = [m for m in ms if en_reposo(m)]
    activos = [m for m in ms if en_actividad(m)]
    est_fc_rep = estadisticas([m.bpm for m in reposo])
    valorable_reposo = len(reposo) >= umbrales.min_registros

    if valorable_reposo and est_fc_rep:
        partes = [f"FC media {_n(est_fc_rep.media)} BPM"]
        fr = estadisticas(_valores(reposo, "rpm"))
        if fr:
            partes.append(f"FR media {_n(fr.media)} RPM")
        tp = estadisticas(_valores(reposo, "temp_c"))
        if tp:
            partes.append(f"temperatura media {_n(tp.media, 2)} °C")
        lineas.append(f"En reposo ({len(reposo)} registros): " + ", ".join(partes) + ".")
    else:
        lineas.append(
            f"En reposo hay pocos registros ({len(reposo)}) para valorar este contexto."
        )

    # -- Actividad
    if len(activos) >= umbrales.min_registros:
        est = estadisticas([m.bpm for m in activos])
        lineas.append(
            f"En actividad física ({len(activos)} registros): FC media {_n(est.media)} BPM, "
            f"máxima {_n(est.maximo)} BPM. Valores más altos que en reposo son esperables."
        )
    elif activos:
        lineas.append(f"En actividad física hay pocos registros ({len(activos)}) para valorar.")

    # -- Evolución respecto al día anterior (RF-47)
    previo = anteriores.get(dia - timedelta(days=1))
    if previo and valorable_reposo and est_fc_rep:
        fc_prev = fc_reposo(previo, umbrales)
        if fc_prev is not None:
            lineas.append(
                f"Evolución: FC en reposo {_con_signo(est_fc_rep.media - fc_prev)} BPM "
                f"respecto al día anterior ({_n(fc_prev)} BPM)."
            )

    # -- Observaciones orientativas, solo con el contexto adecuado (RF-23, 25)
    avisos: list[str] = []
    if valorable_reposo and est_fc_rep:
        if est_fc_rep.media > umbrales.fc_reposo_alta:
            avisos.append(f"FC en reposo elevada ({_n(est_fc_rep.media)} BPM; referencia general < {_n(umbrales.fc_reposo_alta, 0)}).")
        elif est_fc_rep.media < umbrales.fc_reposo_baja:
            avisos.append(f"FC en reposo baja ({_n(est_fc_rep.media)} BPM; referencia general > {_n(umbrales.fc_reposo_baja, 0)}).")
        fr = estadisticas(_valores(reposo, "rpm"))
        if fr and fr.media > umbrales.fr_reposo_alta:
            avisos.append(f"FR en reposo elevada ({_n(fr.media)} RPM).")
        elif fr and fr.media < umbrales.fr_reposo_baja:
            avisos.append(f"FR en reposo baja ({_n(fr.media)} RPM).")
    tp_all = estadisticas(_valores(ms, "temp_c"))
    if tp_all and tp_all.cantidad >= umbrales.min_registros:
        if tp_all.media > umbrales.temp_alta:
            avisos.append(f"Temperatura cutánea media alta ({_n(tp_all.media, 2)} °C).")
        elif tp_all.media < umbrales.temp_baja:
            avisos.append(f"Temperatura cutánea media baja ({_n(tp_all.media, 2)} °C).")

    if avisos:
        lineas.extend("Observación: " + a for a in avisos)
    elif valorable_reposo:
        lineas.append("Observación: los valores en reposo se mantienen dentro de los rangos de referencia generales.")

    # -- Patrones recurrentes (RF-25)
    conjunto = dict(anteriores)
    conjunto[dia] = ms
    lineas.extend(detectar_patrones(conjunto, umbrales))
    lineas.extend(lineas_extra)

    lineas.append(DESCARGO)
    return lineas


# --------------------------------------------------
# RESUMEN DE ACTIVIDAD (RF-48)
# --------------------------------------------------

def resumen_actividad(
    actividad: Actividad,
    mediciones: Sequence[Medicion],
    fc_reposo_referencia: Optional[float],
    umbrales: Umbrales = Umbrales(),
) -> list[str]:
    ms = sorted(mediciones, key=lambda m: m.ts)
    ini = actividad.inicio
    tipo = f" ({actividad.tipo})" if actividad.tipo else ""
    dur = actividad.duracion_s

    lineas = [
        f"Actividad{tipo}: {ini:%d/%m/%Y} a las {ini:%H:%M}, duración {formatear_duracion(dur)}.",
    ]

    if dur < 600:
        lineas.append("Duración: sesión corta (menos de 10 min).")
    elif dur >= 3600:
        lineas.append("Duración: sesión larga (1 h o más).")

    if not ms:
        lineas.append("No hay mediciones asociadas a esta actividad.")
        lineas.append(DESCARGO)
        return lineas

    lineas.append(f"Mediciones asociadas: {len(ms)}.")

    fc = estadisticas([m.bpm for m in ms])
    if fc:
        lineas.append(
            f"FC: media {_n(fc.media)} BPM, mínima {_n(fc.minimo)} BPM, máxima {_n(fc.maximo)} BPM."
        )
    fr = estadisticas(_valores(ms, "rpm"))
    if fr:
        lineas.append(f"FR: media {_n(fr.media)} RPM, máxima {_n(fr.maximo)} RPM.")

    temps = [(m.ts, m.temp_c) for m in ms if m.temp_c is not None]
    if len(temps) >= 2:
        lineas.append(
            f"Temperatura cutánea: de {_n(temps[0][1], 2)} °C a {_n(temps[-1][1], 2)} °C "
            f"({_con_signo(temps[-1][1] - temps[0][1])} °C)."
        )

    # Contexto de esfuerzo físico
    niveles = [m.nivel_actividad for m in ms if m.nivel_actividad in (NIVEL_REPOSO, NIVEL_MEDIA, NIVEL_INTENSA)]
    if niveles:
        total = len(niveles)
        pct = lambda n: _n(100 * niveles.count(n) / total, 0)
        lineas.append(
            f"Nivel de actividad detectado: reposo {pct(NIVEL_REPOSO)} %, "
            f"media {pct(NIVEL_MEDIA)} %, intensa {pct(NIVEL_INTENSA)} %."
        )

    if fc and fc_reposo_referencia:
        exceso = fc.media / fc_reposo_referencia - 1
        if exceso < umbrales.esfuerzo_ligero:
            nivel = "ligero"
        elif exceso < umbrales.esfuerzo_moderado:
            nivel = "moderado"
        else:
            nivel = "alto"
        lineas.append(
            f"Esfuerzo estimado: {nivel} (FC media un {_n(100 * exceso, 0)} % sobre tu FC en reposo "
            f"de referencia, {_n(fc_reposo_referencia)} BPM)."
        )
    else:
        lineas.append("Esfuerzo: no hay FC en reposo de referencia suficiente para estimarlo.")

    # Interrupciones dentro de la actividad (RF-27)
    ts = [m.ts for m in ms]
    huecos = detectar_interrupciones(ts, actividad.inicio_ts, actividad.fin_ts, umbral_interrupcion(ts, 5))
    if huecos:
        lineas.append(
            f"Interrupciones: {len(huecos)} periodo(s) sin datos durante la actividad "
            f"({sum(h.duracion_s for h in huecos)} s en total)."
        )

    lineas.append(DESCARGO)
    return lineas
