"""Seudonimización determinista para exportar datos a un médico o entrenador."""

from __future__ import annotations

import hashlib

PREFIJO = "SUJETO-"


def seudonimo(correo: str = "", nombre: str = "") -> str:
    """``SUJETO-`` + 6 primeros hex del SHA-256 del correo (o del nombre si no hay correo)."""
    base = (correo or nombre or "").strip().lower()
    return PREFIJO + hashlib.sha256(base.encode("utf-8")).hexdigest()[:6]
