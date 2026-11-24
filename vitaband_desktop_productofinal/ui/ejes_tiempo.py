"""Eje X de horas con UNA sola fila de marcas (el DateAxisItem apilaba dos niveles superpuestos)."""

from __future__ import annotations

import math
from datetime import datetime

import pyqtgraph as pg

_PASOS = (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400, 172800, 604800)


class EjeHoras(pg.AxisItem):

    def __init__(self, **kw):
        super().__init__(orientation="bottom", **kw)

    def tickValues(self, minVal, maxVal, size):
        span = maxVal - minVal
        if not span > 0:
            return []
        objetivo = max(2, int(size / 90))                       # ~90 px por etiqueta
        paso = next((p for p in _PASOS if span / p <= objetivo), _PASOS[-1])
        off = datetime.fromtimestamp(minVal).astimezone().utcoffset().total_seconds()   # alinea a hora local
        primero = math.ceil((minVal + off) / paso) * paso - off
        n = int(span // paso) + 1
        return [(paso, [primero + i * paso for i in range(n) if primero + i * paso <= maxVal])]

    def tickStrings(self, values, scale, spacing):
        a, b = self.range
        formato = "%d/%m %H:%M" if (b - a) > 1.5 * 86400 else "%H:%M:%S" if spacing < 60 else "%H:%M"
        out = []
        for v in values:
            try:
                out.append(datetime.fromtimestamp(v).strftime(formato))
            except (OverflowError, OSError, ValueError):
                out.append("")
        return out
