"""Modo Entrenador: paquetes de seguimiento portables ``.vbcoach`` (JSON) con privacidad por diseño.

- ``exportar_coach_pack`` lee SOLO la cuenta activa; las etiquetas personales/hábitos se omiten salvo
  consentimiento explícito (``incluir_etiquetas=True``) y el correo nunca se incluye.
- ``importar_coach_pack`` / ``listar_coach_packs`` trabajan únicamente con el directorio aislado
  ``data/coach_packs/``: este módulo no abre ninguna base SQLite, así que nunca puede leer otras cuentas.
- ``exportar_informes_lote_anonimizados`` genera un PDF por paquete con ``Sujeto #001``, ``#002``…
"""

from __future__ import annotations

import json
import os
import re
import shutil
import statistics
import time
from datetime import date, datetime, timedelta
from typing import Optional, Sequence, Union

from PySide6.QtCore import QMarginsF, QPointF
from PySide6.QtGui import QColor, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen

from services import calculos_fisiologicos as calc
from services import fisiologia_avanzada as fa
from services import vo2max
from services.planificacion_entrenamiento import GestorCalendarioPlanificado

FORMATO, VERSION = "vbcoach", 1
EXTENSION = ".vbcoach"
DIR_COACH_PACKS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "coach_packs")
DIAS_VALIDOS = (42, 90)
_DIA = 86400


# ------------------------------------------------------------------ Exportación

def construir_coach_pack(repo, hoy: date, dias: int = 42, incluir_etiquetas: bool = False,
                         alias_opcional: str = "", nombre: str = "") -> dict:
    """Diccionario del paquete (sin escribir en disco)."""
    if dias not in DIAS_VALIDOS:
        raise ValueError("El rango debe ser de 42 o 90 días")
    fin = int(datetime.combine(hoy + timedelta(days=1), datetime.min.time()).timestamp())
    ini = fin - dias * _DIA

    hrvs = repo.hrv_rango(ini, fin)
    rm = [h.rmssd_ms for h in hrvs]
    f = repo.perfil()
    perfil = calc.PerfilFisiologico(f["edad"], f["sexo"], f["peso_kg"], f["objetivo_semanal_min"]) if f else None
    meds = repo.mediciones_rango(ini, fin)
    reposo = vo2max.fc_reposo(meds)
    est = vo2max.estimar(reposo, vo2max.fc_max_observada(meds), perfil)

    pmc = fa.calcular_pmc(fa.trimp_diario(repo, hoy), hoy, dias)
    acts = repo.actividades_rango(ini, fin)
    zonas = [0.0] * 5
    from domain.zonas_actividad import repartir_zonas
    for a in acts:
        r = repartir_zonas(repo.mediciones_de_actividad(a.id))
        if r:
            zonas = [x + y for x, y in zip(zonas, r.segundos)]
    total = sum(zonas)
    cumpl = GestorCalendarioPlanificado(repo).cumplimiento_semanal(hoy)

    pack = {
        "formato": FORMATO, "version": VERSION, "generado": datetime.now().isoformat(timespec="seconds"),
        "alias": (alias_opcional or nombre or "Deportista").strip(), "dias": dias,
        "incluye_etiquetas": bool(incluir_etiquetas),
        "metricas": {
            "rmssd_medio_ms": statistics.fmean(rm) if rm else None,
            "rmssd_ultimo_ms": rm[-1] if rm else None,
            "vo2max": est.vo2 if est else None,
            "fc_reposo": reposo,
            "tsb_actual": pmc[-1].tsb if pmc else None,
            "ctl_actual": pmc[-1].ctl if pmc else None,
            "atl_actual": pmc[-1].atl if pmc else None,
        },
        "pmc": [{"fecha": p.fecha.isoformat(), "ctl": round(p.ctl, 2), "atl": round(p.atl, 2),
                 "tsb": round(p.tsb, 2)} for p in pmc],
        "sesiones": {"n": len(acts), "minutos": sum(a.duracion_s for a in acts) / 60.0,
                     "zonas_pct": [100.0 * z / total for z in zonas] if total > 0 else [0.0] * 5},
        "cumplimiento_semanal_pct": cumpl.pct,
    }
    if incluir_etiquetas:
        cont: dict[str, int] = {}
        for _, e in repo.marcadores_rango(ini, fin):
            cont[e] = cont.get(e, 0) + 1
        pack["habitos"] = [{"etiqueta": k, "veces": v} for k, v in sorted(cont.items(), key=lambda x: (-x[1], x[0]))]
    return pack


def exportar_coach_pack(repo, ruta: str, hoy: Optional[date] = None, dias: int = 42, incluir_etiquetas: bool = False,
                        alias_opcional: str = "", nombre: str = "") -> str:
    pack = construir_coach_pack(repo, hoy or date.today(), dias, incluir_etiquetas, alias_opcional, nombre)
    if not ruta.endswith(EXTENSION):
        ruta += EXTENSION
    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump(pack, fh, ensure_ascii=False, indent=1)
    return ruta


def construir_coach_pack_completo(repo, hoy: date, nombre: str = "", sujeto_anonimo: str = "") -> dict:
    """Pack de 90 días compatible con el importador (``formato``/``metricas``) + perfil, sesiones y evolución.

    Con ``sujeto_anonimo`` (p. ej. SUJETO-xxxxxx, derivado del SHA-256) el nombre real no aparece en el paquete.
    """
    pack = construir_coach_pack(repo, hoy, 90, True, sujeto_anonimo, nombre)
    if sujeto_anonimo:
        pack["alias"] = sujeto_anonimo
    pack["anonimizado"] = bool(sujeto_anonimo)
    fin = int(datetime.combine(hoy + timedelta(days=1), datetime.min.time()).timestamp())
    ini = fin - 90 * _DIA
    f = repo.perfil()
    pack["perfil"] = ({"edad": f["edad"], "sexo": f["sexo"], "peso_kg": f["peso_kg"],
                       "objetivo_semanal_min": f["objetivo_semanal_min"]} if f else None)
    disc = repo.disciplinas()
    sesiones = []
    for a in repo.actividades_rango(ini, fin):
        nota = repo.nota_sesion(a.id)
        sesiones.append({"inicio": datetime.fromtimestamp(a.inicio_ts).isoformat(timespec="seconds"),
                         "duracion_min": round(a.duracion_s / 60.0, 1), "tipo": a.tipo,
                         "disciplina": disc.get(a.id), "rpe": nota[0] if nota else None})
    pack["actividades"] = sesiones
    pack["hrv_diario"] = [{"fecha": datetime.fromtimestamp(h.ts).date().isoformat(), "rmssd_ms": round(h.rmssd_ms, 1)}
                          for h in repo.hrv_rango(ini, fin)]
    return pack


def exportar_coach_pack_completo(repo, ruta: str, nombre: str = "", sujeto_anonimo: str = "",
                                 hoy: Optional[date] = None) -> str:
    pack = construir_coach_pack_completo(repo, hoy or date.today(), nombre, sujeto_anonimo)
    if not ruta.endswith(EXTENSION):
        ruta += EXTENSION
    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump(pack, fh, ensure_ascii=False, indent=1)
    return ruta


# ------------------------------------------------------------------ Bandeja aislada

def _validar(d: object) -> dict:
    if not isinstance(d, dict) or d.get("formato") != FORMATO or not isinstance(d.get("metricas"), dict):
        raise ValueError("El archivo no es un paquete .vbcoach válido")
    if int(d.get("version", 0)) > VERSION:
        raise ValueError("Versión de paquete no soportada")
    return d


def leer_coach_pack(ruta: str) -> dict:
    with open(ruta, "r", encoding="utf-8") as fh:
        return _validar(json.load(fh))


def importar_coach_pack(ruta: str, directorio: str = DIR_COACH_PACKS) -> str:
    """Copia el paquete (validado) a la bandeja aislada y devuelve la ruta de la copia."""
    leer_coach_pack(ruta)
    os.makedirs(directorio, exist_ok=True)
    base = re.sub(r"[^\w.-]", "_", os.path.splitext(os.path.basename(ruta))[0]) or "pack"
    destino, n = os.path.join(directorio, base + EXTENSION), 1
    while os.path.exists(destino):
        n += 1
        destino = os.path.join(directorio, f"{base}_{n}{EXTENSION}")
    shutil.copyfile(ruta, destino)
    return destino


def listar_coach_packs(directorio: str = DIR_COACH_PACKS) -> list[dict]:
    """Paquetes de la bandeja (los ilegibles se ignoran). Cada uno lleva su ``archivo``."""
    if not os.path.isdir(directorio):
        return []
    salida = []
    for nombre in sorted(os.listdir(directorio)):
        if nombre.endswith(EXTENSION):
            try:
                d = leer_coach_pack(os.path.join(directorio, nombre))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            d["archivo"] = os.path.join(directorio, nombre)
            salida.append(d)
    return salida


# ------------------------------------------------------------------ PDF anonimizado por lotes

def _n(x, dec=1, unidad=""):
    return "N/D" if x is None else f"{x:.{dec}f}{(' ' + unidad) if unidad else ''}"


def _dibujar_pack(pg, pack: dict, sujeto: str) -> None:
    from services.exportar_pdf import GRIS, MARGEN, _fecha
    m = pack["metricas"]
    pg.texto("Informe de seguimiento VitaBand", 22, True, espacio=2)
    pg.texto("Datos de la banda pectoral ECG · identidad anonimizada", 10, color=GRIS, espacio=10)
    pg.tabla([("Sujeto", sujeto), ("Periodo", f"últimos {pack.get('dias', '?')} días"),
              ("Generado", str(pack.get("generado", ""))[:16].replace("T", " "))])
    pg.titulo_seccion("Métricas")
    cumpl = pack.get("cumplimiento_semanal_pct")
    pg.tabla([("HRV medio (RMSSD)", _n(m.get("rmssd_medio_ms"), 0, "ms")), ("VO2máx estimado", _n(m.get("vo2max"), 1)),
              ("FC en reposo", _n(m.get("fc_reposo"), 0, "BPM")), ("TSB (forma)", _n(m.get("tsb_actual"), 1)),
              ("CTL / ATL", f"{_n(m.get('ctl_actual'), 1)} / {_n(m.get('atl_actual'), 1)}"),
              ("Cumplimiento semanal", "N/D" if cumpl is None else f"{cumpl:.0f} %")])
    s = pack.get("sesiones", {})
    z = s.get("zonas_pct") or [0] * 5
    pg.titulo_seccion("Sesiones")
    pg.tabla([("Sesiones / minutos", f"{s.get('n', 0)} / {_n(s.get('minutos'), 0)}"),
              ("Reparto Z1–Z5", " · ".join(f"Z{i + 1} {v:.0f}%" for i, v in enumerate(z)))])
    pg.titulo_seccion("Hábitos")
    hab = pack.get("habitos")
    pg.texto("No compartido" if hab is None else (", ".join(f"{h['etiqueta']} ×{h['veces']}" for h in hab) or "Sin etiquetas"),
             10, espacio=6)
    puntos = pack.get("pmc") or []
    if len(puntos) >= 2:
        todos = [p[k] for p in puntos for k in ("ctl", "atl", "tsb")]
        y0, y1 = min(todos + [0]), max(todos) * 1.05 or 1
        n = len(puntos) - 1
        colores = {"ctl": "#1B4D3E", "atl": "#c0392b", "tsb": "#D4AF37"}

        def dibujar(p: QPainter, area):
            for clave, col in colores.items():
                p.setPen(QPen(QColor(col), 3))
                pts = [QPointF(pg._fx(i), pg._fy(q[clave])) for i, q in enumerate(puntos)]
                for a, b in zip(pts, pts[1:]):
                    p.drawLine(a, b)

        pg.grafica("CTL (verde) · ATL (rojo) · TSB (dorado)", 420, dibujar,
                   [(0, puntos[0]["fecha"][5:]), (n, puntos[-1]["fecha"][5:])],
                   [round(y0), round((y0 + y1) / 2), round(y1)], 0, n, y0, y1, "Carga", "Fecha")


def exportar_informes_lote_anonimizados(paquetes: Sequence[Union[str, dict]], carpeta: str) -> list[str]:
    """Un PDF por paquete en ``carpeta`` con identificadores ``Sujeto #001``…; no contiene alias ni correos."""
    from services.exportar_pdf import DPI, _Pagina
    os.makedirs(carpeta, exist_ok=True)
    salida = []
    for i, p in enumerate(paquetes, 1):
        pack = _validar(leer_coach_pack(p) if isinstance(p, str) else p)
        sujeto = f"Sujeto #{i:03d}"
        ruta = os.path.join(carpeta, f"informe_sujeto_{i:03d}.pdf")
        escritor = QPdfWriter(ruta)
        escritor.setResolution(DPI)
        escritor.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                                           QMarginsF(0, 0, 0, 0)))
        escritor.setTitle(f"Informe VitaBand · {sujeto}")
        pintor = QPainter(escritor)
        if not pintor.isActive():
            raise OSError(f"No se puede escribir el PDF en {ruta}")
        try:
            pg = _Pagina(escritor, pintor)
            _dibujar_pack(pg, pack, sujeto)
            pg.pie()
        finally:
            pintor.end()
        salida.append(ruta)
    return salida
