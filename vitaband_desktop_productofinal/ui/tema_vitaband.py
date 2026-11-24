"""Identidad visual «Verde Pino & Obsidiana» de VitaBand (banda pectoral ECG)."""

from __future__ import annotations

from pathlib import Path

import pyqtgraph as pg

FONDO_OBSIDIANA = "#090E0C"
TARJETA_PINO = "#111916"
TARJETA_ELEVADA = "#17221E"
BORDE_BOSQUE = "#21312B"
VERDE_PINO = "#1B4D3E"
ESMERALDA_ECG = "#10B981"
ESMERALDA_BRILLO = "#34D399"
ORO_CHAMPAN = "#D4AF37"
CORAL_PULSO = "#F43F5E"
TEXTO_MARFIL = "#F2F6F4"
TEXTO_SALVIA = "#8BA096"
COLORES_ZONAS = {"Z1": "#64748B", "Z2": "#10B981", "Z3": "#F59E0B", "Z4": "#F97316", "Z5": "#F43F5E"}
ALFA_REJILLA = 0.15

RUTA_QSS = Path(__file__).resolve().parents[1] / "styles" / "vitaband_pino.qss"


def configurar_pyqtgraph() -> None:
    pg.setConfigOption("background", TARJETA_PINO)
    pg.setConfigOption("foreground", TEXTO_SALVIA)
    pg.setConfigOption("antialias", True)


def cargar_qss(ruta: Path = RUTA_QSS) -> str:
    return ruta.read_text(encoding="utf-8")


def aplicar_tema_global(app) -> bool:
    """Configura pyqtgraph y carga la hoja de estilos. Devuelve False (sin excepción) si falta el QSS."""
    configurar_pyqtgraph()
    try:
        app.setStyleSheet(cargar_qss())
    except OSError:
        return False
    return True
