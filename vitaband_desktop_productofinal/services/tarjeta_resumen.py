"""Tarjeta resumen vertical (540×960) de una sesión, lista para compartir como PNG."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Sequence

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF
from ui.tema_vitaband import COLORES_ZONAS as _ZONAS, ESMERALDA_ECG, FONDO_OBSIDIANA, ORO_CHAMPAN, TARJETA_PINO, TEXTO_MARFIL, TEXTO_SALVIA, VERDE_PINO

ANCHO, ALTO = 540, 960
FONDO = FONDO_OBSIDIANA
PANEL = TARJETA_PINO
TEXTO = TEXTO_MARFIL
GRIS = TEXTO_SALVIA
ACENTO = ESMERALDA_ECG
ORO = ORO_CHAMPAN
BORDE = VERDE_PINO
COLORES_ZONAS = tuple(_ZONAS.values())
MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


@dataclass(frozen=True)
class DatosTarjeta:
    inicio_ts: int
    duracion_s: float
    bpm_serie: Sequence[tuple[float, float]] = ()        # (segundos desde el inicio, BPM)
    zonas_pct: Optional[Sequence[float]] = None          # 5 valores, Z1..Z5
    kcal: Optional[float] = None
    trimp: Optional[float] = None
    insignias: Sequence[str] = field(default_factory=tuple)
    disciplina: Optional[str] = None


def _duracion(s: float) -> str:
    s = max(0, int(s))
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def _fecha(ts: int) -> str:
    d = datetime.fromtimestamp(ts)
    return f"{d.day} {MESES[d.month - 1]} {d.year} · {d:%H:%M}"


def _fuente(px: int, negrita: bool = False) -> QFont:
    f = QFont()
    f.setPixelSize(px)
    f.setBold(negrita)
    return f


def _texto(p: QPainter, x: float, y: float, texto: str, px: int, color: str = TEXTO, negrita: bool = False,
           ancho: Optional[float] = None, alinear=Qt.AlignmentFlag.AlignLeft) -> None:
    p.setFont(_fuente(px, negrita))
    p.setPen(QColor(color))
    w = ancho if ancho is not None else ANCHO - x - 36
    p.drawText(QRectF(x, y, w, px * 1.6), int(alinear | Qt.AlignmentFlag.AlignVCenter), texto)


def _estrella(p: QPainter, cx: float, cy: float, r: float, color: str) -> None:
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else r * 0.45
        pts.append(QPointF(cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawPolygon(QPolygonF(pts))


def _curva(p: QPainter, rect: QRectF, serie: Sequence[tuple[float, float]]) -> Optional[tuple[float, float, float]]:
    pts = [(t, b) for t, b in serie if b and b > 0]
    p.setPen(QPen(QColor(BORDE), 1.5))
    p.setBrush(QColor(PANEL))
    p.drawRoundedRect(rect, 14, 14)
    if len(pts) < 2:
        _texto(p, rect.x(), rect.y() + rect.height() / 2 - 14, "Sin datos de pulso", 18, GRIS,
               ancho=rect.width(), alinear=Qt.AlignmentFlag.AlignHCenter)
        return None
    if len(pts) > 160:                                          # se reduce a ~160 puntos por promedio
        paso = len(pts) / 160
        pts = [(sum(t for t, _ in pts[int(i * paso):int((i + 1) * paso)]) / max(1, len(pts[int(i * paso):int((i + 1) * paso)])),
                sum(b for _, b in pts[int(i * paso):int((i + 1) * paso)]) / max(1, len(pts[int(i * paso):int((i + 1) * paso)])))
               for i in range(160) if pts[int(i * paso):int((i + 1) * paso)]]
    t0, t1 = pts[0][0], pts[-1][0]
    lo, hi = min(b for _, b in pts), max(b for _, b in pts)
    lo, hi = lo - 5, hi + 5
    x = lambda t: rect.x() + 16 + (rect.width() - 32) * ((t - t0) / (t1 - t0) if t1 > t0 else 0)
    y = lambda b: rect.bottom() - 16 - (rect.height() - 32) * (b - lo) / (hi - lo)
    ruta = QPainterPath(QPointF(x(pts[0][0]), y(pts[0][1])))
    for i in range(1, len(pts)):                                # curva suave (cúbicas con puntos medios)
        ax, ay, bx, by = x(pts[i - 1][0]), y(pts[i - 1][1]), x(pts[i][0]), y(pts[i][1])
        ruta.cubicTo(QPointF((ax + bx) / 2, ay), QPointF((ax + bx) / 2, by), QPointF(bx, by))
    relleno = QPainterPath(ruta)
    relleno.lineTo(QPointF(x(pts[-1][0]), rect.bottom() - 16))
    relleno.lineTo(QPointF(x(pts[0][0]), rect.bottom() - 16))
    relleno.closeSubpath()
    degradado = QLinearGradient(0, rect.top(), 0, rect.bottom())
    c1, c2 = QColor(ACENTO), QColor(ACENTO)
    c1.setAlpha(120)
    c2.setAlpha(0)
    degradado.setColorAt(0, c1)
    degradado.setColorAt(1, c2)
    p.setBrush(QBrush(degradado))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPath(relleno)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(ACENTO), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawPath(ruta)
    return lo + 5, hi - 5, sum(b for _, b in pts) / len(pts)


def generar_tarjeta(d: DatosTarjeta) -> QImage:
    img = QImage(ANCHO, ALTO, QImage.Format.Format_ARGB32)
    img.fill(QColor(FONDO))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    # Cabecera
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(ACENTO))
    p.drawRoundedRect(QRectF(36, 56, 6, 62), 3, 3)
    _texto(p, 56, 48, "VitaBand", 40, TEXTO, True)
    _texto(p, 56, 92, "Banda Pectoral ECG", 18, GRIS)
    _texto(p, 36, 150, _fecha(d.inicio_ts) + (f"  ·  {d.disciplina}" if d.disciplina else ""), 20, GRIS)

    # Duración
    _texto(p, 36, 196, "DURACIÓN", 14, GRIS, True)
    _texto(p, 36, 214, _duracion(d.duracion_s), 76, TEXTO, True)

    # Curva de BPM
    rect = QRectF(36, 330, ANCHO - 72, 190)
    datos = _curva(p, rect, d.bpm_serie)
    if datos:
        _texto(p, 36, 530, f"Pulso medio {datos[2]:.0f} BPM  ·  mín {datos[0]:.0f}  ·  máx {datos[1]:.0f}", 16, GRIS)

    # Zonas
    _texto(p, 36, 570, "ZONAS CARDÍACAS", 14, GRIS, True)
    pct = list(d.zonas_pct) if d.zonas_pct and len(d.zonas_pct) == 5 else None
    for i in range(5):
        yy = 604 + i * 34
        _texto(p, 36, yy - 3, f"Z{i + 1}", 18, TEXTO, True, ancho=40)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(PANEL))
        p.drawRoundedRect(QRectF(84, yy + 3, 340, 18), 9, 9)
        v = 0.0 if pct is None else max(0.0, min(100.0, pct[i]))
        if v > 0:
            p.setBrush(QColor(COLORES_ZONAS[i]))
            p.drawRoundedRect(QRectF(84, yy + 3, max(18.0, 340 * v / 100), 18), 9, 9)
        _texto(p, 432, yy - 3, "—" if pct is None else f"{v:.0f} %", 18, TEXTO, ancho=72,
               alinear=Qt.AlignmentFlag.AlignRight)

    # kcal y TRIMP
    for k, (titulo, valor) in enumerate((("ENERGÍA (kcal)", d.kcal), ("CARGA (TRIMP)", d.trimp))):
        r = QRectF(36 + k * 240, 800, 228, 84)
        p.setPen(QPen(QColor(BORDE), 1.5))
        p.setBrush(QColor(PANEL))
        p.drawRoundedRect(r, 14, 14)
        _texto(p, r.x() + 16, r.y() + 8, titulo, 13, GRIS, True, ancho=r.width() - 32)
        _texto(p, r.x() + 16, r.y() + 28, "N/D" if valor is None else f"{valor:.0f}", 36, TEXTO, True, ancho=r.width() - 32)

    # Insignias
    if d.insignias:
        for i, nombre in enumerate(list(d.insignias)[:2]):
            yy = 898 + i * 28
            _estrella(p, 50, yy + 12, 9, ORO)
            _texto(p, 68, yy, nombre if len(nombre) <= 44 else nombre[:43] + "…", 15, ORO, True, ancho=440)
    else:
        _texto(p, 36, 900, "Sin récords personales en esta sesión", 15, GRIS)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(BORDE), 2))
    p.drawRoundedRect(QRectF(8, 8, ANCHO - 16, ALTO - 16), 20, 20)           # marco Verde Pino
    p.end()
    return img


def guardar_tarjeta(d: DatosTarjeta, ruta: str) -> bool:
    return generar_tarjeta(d).save(ruta, "PNG")
