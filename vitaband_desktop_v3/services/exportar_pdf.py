"""Informe biométrico en PDF, generado solo con PySide6 (QPdfWriter + QPainter).

Contenido: cabecera con el perfil, estadísticas del rango, gráficas de BPM y RPM, un recorte
ampliado del ECG de la banda pectoral (envolvente de 1 s guardada) y las observaciones del
periodo. Todo es de solo lectura sobre el repositorio. Cada bloque se coloca entero: si no cabe
en la página, pasa a la siguiente.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional, Sequence

import numpy as np
from PySide6.QtCore import QMarginsF, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen

from domain import observaciones as obs
from domain.observaciones import DESCARGO
from domain.zonas_actividad import FC_MAX_REFERENCIA
from services.repositorio_historial import AMBITO_PERIODICO, RepositorioHistorial

DPI = 150
MARGEN = 90                         # px a 150 dpi (~15 mm)
ANCHO, ALTO = 1240, 1754            # A4 a 150 dpi
ECG_VENTANA_S = 120                 # recorte ampliado: últimos 2 min con ECG del rango
MAX_ECG_CONSULTA_S = 7 * 86400
MAX_PUNTOS_GRAFICA = 900
GRIS, TINTA = QColor("#666666"), QColor("#111111")
COLOR_BPM, COLOR_RPM, COLOR_ECG = QColor("#c0392b"), QColor("#1f77b4"), QColor("#2c3e50")


@dataclass(frozen=True)
class PerfilInforme:
    """Datos del perfil que se imprimen. Lo que no está registrado se muestra como tal."""
    nombre: str = ""
    correo: Optional[str] = None
    edad: Optional[int] = None
    sexo: Optional[str] = None
    fc_max: float = FC_MAX_REFERENCIA
    fc_max_configurada: bool = False


def _fecha(ts: int, formato: str = "%d/%m/%Y %H:%M") -> str:
    return datetime.fromtimestamp(ts).strftime(formato)


def _n(x: Optional[float], dec: int = 1, unidad: str = "") -> str:
    if x is None or not math.isfinite(x):
        return "sin datos"
    return f"{x:.{dec}f}".replace(".", ",") + (f" {unidad}" if unidad else "")


def _escala(lo: float, hi: float, n: int = 5) -> list[float]:
    if not math.isfinite(lo) or not math.isfinite(hi):
        return [0.0, 1.0]
    if hi - lo < 1e-9:
        lo, hi = lo - 1, hi + 1
    paso = (hi - lo) / (n - 1)
    mag = 10 ** math.floor(math.log10(paso))
    paso = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= paso), default=paso)
    ini = math.floor(lo / paso) * paso
    out, v = [], ini
    while v <= hi + paso * 0.999 and len(out) < 12:
        out.append(round(v, 6))
        v += paso
    return out


def _segmentos(x: np.ndarray, y: np.ndarray, corte: float):
    """Tramos continuos (parte los huecos mayores que ``corte`` y los NaN)."""
    tramo: list[tuple[float, float]] = []
    prev = None
    for xi, yi in zip(x, y):
        if not np.isfinite(yi) or (prev is not None and xi - prev > corte):
            if tramo:
                yield tramo
            tramo = []
        if np.isfinite(yi):
            tramo.append((xi, yi))
            prev = xi
    if tramo:
        yield tramo


class _Pagina:
    """Cursor de maquetación sobre un QPdfWriter."""

    def __init__(self, escritor: QPdfWriter, pintor: QPainter):
        self.w, self.p = escritor, pintor
        self.y = MARGEN
        self.numero = 1

    @property
    def ancho(self) -> int:
        return ANCHO - 2 * MARGEN

    def hay_sitio(self, alto: float) -> bool:
        return self.y + alto <= ALTO - MARGEN

    def reservar(self, alto: float) -> None:
        """Garantiza que un bloque de ``alto`` px cabe entero; si no, abre página nueva."""
        if not self.hay_sitio(alto):
            self.nueva()

    def nueva(self) -> None:
        self.pie()
        self.w.newPage()
        self.numero += 1
        self.y = MARGEN

    def pie(self) -> None:
        self.p.setFont(QFont("Sans", 8))
        self.p.setPen(GRIS)
        self.p.drawText(QRectF(MARGEN, ALTO - MARGEN + 20, self.ancho, 30), Qt.AlignmentFlag.AlignRight,
                        f"VitaBand · página {self.numero}")

    def texto(self, texto: str, pt: int = 10, negrita: bool = False, color: QColor = TINTA,
              sangria: int = 0, espacio: int = 8) -> None:
        fuente = QFont("Sans", pt)
        fuente.setBold(negrita)
        self.p.setFont(fuente)
        self.p.setPen(color)
        caja = QFontMetrics(fuente, self.w).boundingRect(
            0, 0, self.ancho - sangria, 10_000, int(Qt.TextFlag.TextWordWrap), texto)
        self.reservar(caja.height() + espacio)
        self.p.drawText(QRectF(MARGEN + sangria, self.y, self.ancho - sangria, caja.height() + 4),
                        int(Qt.TextFlag.TextWordWrap), texto)
        self.y += caja.height() + espacio

    def titulo_seccion(self, texto: str) -> None:
        self.reservar(90)                                # un título nunca queda solo al final
        self.y += 14
        self.texto(texto, 13, True, QColor("#8e1b1b"), espacio=4)
        self.p.setPen(QPen(QColor("#cccccc"), 2))
        self.p.drawLine(MARGEN, int(self.y), MARGEN + self.ancho, int(self.y))
        self.y += 12

    def tabla(self, filas: Sequence[tuple[str, str]]) -> None:
        alto_fila = 40
        self.reservar(alto_fila * len(filas) + 10)
        fuente = QFont("Sans", 10)
        for i, (k, v) in enumerate(filas):
            if i % 2 == 0:
                self.p.fillRect(QRectF(MARGEN, self.y, self.ancho, alto_fila), QColor("#f3f3f3"))
            self.p.setPen(TINTA)
            fuente.setBold(False)
            self.p.setFont(fuente)
            self.p.drawText(QRectF(MARGEN + 12, self.y, self.ancho * 0.55, alto_fila),
                            Qt.AlignmentFlag.AlignVCenter, k)
            fuente.setBold(True)
            self.p.setFont(fuente)
            self.p.drawText(QRectF(MARGEN + self.ancho * 0.58, self.y, self.ancho * 0.4, alto_fila),
                            Qt.AlignmentFlag.AlignVCenter, v)
            self.y += alto_fila
        self.y += 10

    def grafica(self, titulo: str, alto: int, dibujar: Callable[[QPainter, QRectF], None],
                x_etiquetas: Sequence[tuple[float, str]], y_ticks: Sequence[float], x0: float, x1: float,
                y0: float, y1: float, etiqueta_y: str, etiqueta_x: str) -> None:
        """Marco con ejes, rejilla y etiquetas; ``dibujar`` recibe el área de trazado."""
        total = alto + 130
        self.reservar(total)
        self.texto(titulo, 11, True, espacio=4)
        area = QRectF(MARGEN + 110, self.y + 6, self.ancho - 130, alto - 60)
        p = self.p
        p.setFont(QFont("Sans", 8))
        p.setPen(QPen(QColor("#dddddd"), 1))
        fx = lambda x: area.left() + (x - x0) / (x1 - x0 or 1) * area.width()
        fy = lambda y: area.bottom() - (y - y0) / (y1 - y0 or 1) * area.height()
        for v in y_ticks:
            p.setPen(QPen(QColor("#dddddd"), 1))
            p.drawLine(QPointF(area.left(), fy(v)), QPointF(area.right(), fy(v)))
            p.setPen(GRIS)
            p.drawText(QRectF(area.left() - 100, fy(v) - 14, 92, 28),
                       int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), _n(v, 0 if v == int(v) else 1))
        for x, txt in x_etiquetas:
            p.setPen(QPen(QColor("#eeeeee"), 1))
            p.drawLine(QPointF(fx(x), area.top()), QPointF(fx(x), area.bottom()))
            p.setPen(GRIS)
            p.drawText(QRectF(fx(x) - 70, area.bottom() + 6, 140, 28), Qt.AlignmentFlag.AlignHCenter, txt)
        self._fx, self._fy = fx, fy
        p.save()
        p.setClipRect(area)
        dibujar(p, area)
        p.restore()
        p.setPen(QPen(TINTA, 2))
        p.drawRect(area)
        p.setPen(GRIS)
        p.drawText(QRectF(area.left(), area.bottom() + 36, area.width(), 28), Qt.AlignmentFlag.AlignHCenter, etiqueta_x)
        p.save()
        p.translate(MARGEN + 12, area.center().y())
        p.rotate(-90)
        p.drawText(QRectF(-area.height() / 2, 0, area.height(), 26), Qt.AlignmentFlag.AlignHCenter, etiqueta_y)
        p.restore()
        self.y += alto + 40


def _promedios(mediciones, attr: str, desde: int, hasta: int):
    """Medias por intervalo: (centros, medias[NaN si vacío], ancho_s)."""
    pares = [(m.ts, getattr(m, attr)) for m in mediciones
             if getattr(m, attr) is not None and (attr != "bpm" or m.bpm > 0)]
    if not pares:
        return None
    ancho = max((hasta - desde) / MAX_PUNTOS_GRAFICA, 10.0)
    n = max(1, int(math.ceil((hasta - desde) / ancho)))
    suma, cuenta = np.zeros(n), np.zeros(n)
    for ts, v in pares:
        i = min(n - 1, int((ts - desde) / ancho))
        suma[i] += v
        cuenta[i] += 1
    medias = np.where(cuenta > 0, suma / np.maximum(cuenta, 1), np.nan)
    return desde + (np.arange(n) + 0.5) * ancho, medias, ancho


def _etiquetas_tiempo(desde: int, hasta: int, n: int = 5):
    formato = "%H:%M" if hasta - desde <= 86400 else "%d/%m" if hasta - desde > 3 * 86400 else "%d/%m %H:%M"
    return [(desde + (hasta - desde) * i / (n - 1), _fecha(int(desde + (hasta - desde) * i / (n - 1)), formato))
            for i in range(n)]


def _grafica_serie(pg: _Pagina, mediciones, attr: str, titulo: str, unidad: str, color: QColor,
                   desde: int, hasta: int) -> None:
    datos = _promedios(mediciones, attr, desde, hasta)
    if datos is None:
        pg.texto(f"{titulo}: sin datos en el periodo.", 10, color=GRIS)
        return
    x, y, ancho = datos
    validos = y[np.isfinite(y)]
    ticks = _escala(float(validos.min()), float(validos.max()))
    y0, y1 = ticks[0], ticks[-1]

    def dibujar(p: QPainter, area: QRectF) -> None:
        p.setPen(QPen(color, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        for tramo in _segmentos(x, y, 3 * ancho + 30):
            pts = [QPointF(pg._fx(a), pg._fy(b)) for a, b in tramo]
            if len(pts) > 1:
                p.drawPolyline(pts)
            else:                                        # un registro aislado: punto visible
                p.setBrush(color)
                p.drawEllipse(pts[0], 5, 5)

    pg.grafica(titulo, 340, dibujar, _etiquetas_tiempo(desde, hasta), ticks, desde, hasta, y0, y1,
               f"{titulo} ({unidad})", "Fecha y hora")


def _recorte_ecg(repo: RepositorioHistorial, desde: int, hasta: int):
    """Últimos ``ECG_VENTANA_S`` segundos con ECG del rango: (segundos, inicio, fin) o None."""
    segs = repo.ecg_rango(max(desde, hasta - MAX_ECG_CONSULTA_S), hasta)
    if not segs:
        return None
    fin = max(s.ts for s in segs) + 1
    ini = fin - ECG_VENTANA_S
    return [s for s in segs if ini <= s.ts < fin], ini, fin


def _grafica_ecg(pg: _Pagina, segundos, ini: int, fin: int) -> None:
    mins, maxs = [s.minimo for s in segundos], [s.maximo for s in segundos]
    ticks = _escala(float(min(mins)), float(max(maxs)))
    by_ts = {s.ts: s for s in segundos}

    def dibujar(p: QPainter, area: QRectF) -> None:
        p.setPen(QPen(COLOR_ECG, 3))
        for t in range(ini, fin):
            s = by_ts.get(t)
            if s is not None:
                x = pg._fx(t - ini + 0.5)
                p.drawLine(QPointF(x, pg._fy(s.minimo)), QPointF(x, pg._fy(s.maximo)))

    etiquetas = [(v, f"{int(v)} s") for v in range(0, ECG_VENTANA_S + 1, 20)]
    pg.grafica(f"Recorte ampliado del ECG (banda pectoral): {_fecha(ini, '%d/%m/%Y %H:%M:%S')} – "
               f"{_fecha(fin, '%H:%M:%S')}", 380, dibujar, etiquetas, ticks, 0, ECG_VENTANA_S, ticks[0], ticks[-1],
               "Amplitud (ADC)", "Tiempo desde el inicio del recorte (s)")
    pg.texto("Envolvente guardada (mínimo y máximo de cada segundo); no es la señal completa a 100 Hz, "
             "así que no permite medir intervalos R-R.", 9, color=GRIS)


def generar_informe_pdf(
    ruta: str,
    repo: RepositorioHistorial,
    desde_ts: int,
    hasta_ts: int,
    perfil: PerfilInforme = PerfilInforme(),
    ahora: Optional[float] = None,
) -> str:
    """Escribe el informe del rango [desde_ts, hasta_ts) en ``ruta`` y la devuelve."""
    if hasta_ts <= desde_ts:
        raise ValueError("El rango debe tener fin posterior al inicio")
    emision = int(time.time() if ahora is None else ahora)

    escritor = QPdfWriter(ruta)
    escritor.setResolution(DPI)
    escritor.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                                       QMarginsF(0, 0, 0, 0)))
    escritor.setTitle("Informe Biométrico VitaBand")
    pintor = QPainter(escritor)
    if not pintor.isActive():
        raise OSError(f"No se puede escribir el PDF en {ruta}")
    try:
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        pg = _Pagina(escritor, pintor)
        _dibujar_informe(pg, repo, desde_ts, hasta_ts, perfil, emision)
        pg.pie()
    finally:
        pintor.end()
    return ruta


def _dibujar_informe(pg: _Pagina, repo, desde: int, hasta: int, perfil: PerfilInforme, emision: int) -> None:
    mediciones = repo.mediciones_rango(desde, hasta, AMBITO_PERIODICO)
    sesiones = repo.actividades_rango(desde, hasta)
    hrvs = repo.hrv_rango(desde, hasta)

    # --- Cabecera
    pg.texto("Informe Biométrico VitaBand", 22, True, espacio=2)
    pg.texto("Telemetría de la banda pectoral VitaBand (ECG, pulso, respiración, temperatura y actividad)",
             10, color=GRIS, espacio=10)
    pg.tabla([
        ("Periodo", f"{_fecha(desde, '%d/%m/%Y')} – {_fecha(hasta - 1, '%d/%m/%Y')}"),
        ("Fecha de emisión", _fecha(emision)),
        ("Usuario", perfil.nombre or "sin nombre"),
        ("Correo", perfil.correo or "no registrado"),
        ("Edad", f"{perfil.edad} años" if perfil.edad else "no registrada"),
        ("Sexo", perfil.sexo or "no registrado"),
        ("FC máx.", f"{perfil.fc_max:.0f} BPM" + ("" if perfil.fc_max_configurada else " (referencia, no configurada)")),
    ])

    # --- Estadísticas
    bpm = [m.bpm for m in mediciones if m.bpm > 0]
    rpm = [m.rpm for m in mediciones if m.rpm is not None]
    reposo = obs.fc_reposo(mediciones)
    pg.titulo_seccion("Estadísticas del periodo")
    pg.tabla([
        ("BPM medio / mínimo / máximo",
         "sin datos" if not bpm else f"{_n(sum(bpm) / len(bpm))} / {_n(min(bpm), 0)} / {_n(max(bpm), 0)}"),
        ("RPM medio", _n(sum(rpm) / len(rpm) if rpm else None)),
        ("FC en reposo (media)", _n(reposo, 1, "BPM")),
        ("Último HRV (RMSSD)", f"{_n(hrvs[-1].rmssd_ms, 0, 'ms')} · {_fecha(hrvs[-1].ts)}" if hrvs else "sin datos"),
        ("Registros periódicos", str(len(mediciones))),
        ("Sesiones de actividad", str(len(sesiones))),
    ])

    # --- Gráficas
    pg.titulo_seccion("Evolución de pulso y respiración")
    if not mediciones:
        pg.texto("No hay mediciones periódicas en el periodo elegido.", 10, color=GRIS)
    else:
        _grafica_serie(pg, mediciones, "bpm", "Frecuencia cardíaca", "BPM", COLOR_BPM, desde, hasta)
        _grafica_serie(pg, mediciones, "rpm", "Frecuencia respiratoria", "RPM", COLOR_RPM, desde, hasta)

    # --- ECG
    pg.titulo_seccion("ECG de la banda pectoral")
    recorte = _recorte_ecg(repo, desde, hasta)
    if recorte is None:
        pg.texto("No hay ECG guardado en el periodo elegido.", 10, color=GRIS)
    else:
        _grafica_ecg(pg, *recorte)

    # --- Observaciones
    pg.titulo_seccion("Observaciones automáticas")
    observaciones = repo.observaciones_rango(desde, hasta, "CONTEXTO") + repo.observaciones_rango(desde, hasta, "DIARIA")
    if not observaciones:
        pg.texto("No hay observaciones generadas para este periodo.", 10, color=GRIS)
    for o in observaciones[:120]:
        cabecera = (f"Contexto: «{o.clave}»" if o.tipo == "CONTEXTO"
                    else f"Día {o.clave[8:10]}/{o.clave[5:7]}/{o.clave[:4]}")
        lineas = [l for l in o.lineas if l != DESCARGO]
        pg.reservar(90)
        pg.texto(cabecera, 10, True, espacio=2)
        for l in lineas:
            pg.texto("• " + l, 9, sangria=20, espacio=3)
        pg.y += 6

    marcadores = repo.marcadores_rango(desde, hasta)
    if marcadores:
        pg.titulo_seccion("Marcadores de contexto")
        pg.texto("; ".join(f"{_fecha(t)} {e}" for t, e in marcadores[:60]), 9)

    pg.y += 10
    pg.texto(DESCARGO, 8, color=GRIS)
