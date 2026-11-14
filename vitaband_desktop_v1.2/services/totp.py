"""TOTP (RFC 6238) con HMAC-SHA1, 6 dígitos y paso de 30 s.

Implementación con la biblioteca estándar, compatible con Google Authenticator,
Microsoft Authenticator, Authy, etc. Sin dependencias externas.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from typing import Optional
from urllib.parse import quote

PASO_S = 30
DIGITOS = 6


def generar_secreto(bytes_: int = 20) -> str:
    """Secreto aleatorio en Base32 (160 bits por defecto), sin relleno '='."""
    return base64.b32encode(secrets.token_bytes(bytes_)).decode("ascii").rstrip("=")


def _decodificar(secreto: str) -> bytes:
    limpio = secreto.replace(" ", "").replace("-", "").upper()
    return base64.b32decode(limpio + "=" * (-len(limpio) % 8))


def codigo_en_paso(secreto: str, paso: int, digitos: int = DIGITOS) -> str:
    mac = hmac.new(_decodificar(secreto), struct.pack(">Q", paso), hashlib.sha1).digest()
    desplazamiento = mac[-1] & 0x0F
    numero = struct.unpack(">I", mac[desplazamiento:desplazamiento + 4])[0] & 0x7FFFFFFF
    return str(numero % (10 ** digitos)).zfill(digitos)


def paso_actual(ahora: Optional[float] = None) -> int:
    return int((time.time() if ahora is None else ahora) // PASO_S)


def codigo_actual(secreto: str, ahora: Optional[float] = None) -> str:
    return codigo_en_paso(secreto, paso_actual(ahora))


def verificar(
    secreto: str,
    codigo: str,
    ahora: Optional[float] = None,
    ventana: int = 1,
    ultimo_paso_usado: int = -1,
) -> Optional[int]:
    """Devuelve el paso en el que el código es válido, o None.

    Acepta ±``ventana`` pasos por desfase de reloj. Rechaza cualquier paso
    <= ``ultimo_paso_usado`` para impedir reutilizar un código ya aceptado.
    """
    codigo = (codigo or "").strip().replace(" ", "")
    if len(codigo) != DIGITOS or not codigo.isdigit():
        return None

    actual = paso_actual(ahora)
    for paso in range(actual - ventana, actual + ventana + 1):
        if paso <= ultimo_paso_usado:
            continue
        if hmac.compare_digest(codigo_en_paso(secreto, paso), codigo):
            return paso
    return None


def uri_aprovisionamiento(secreto: str, cuenta: str, emisor: str = "VitaBand") -> str:
    """URI otpauth:// que entienden las apps autenticadoras (también para un QR)."""
    etiqueta = quote(f"{emisor}:{cuenta}")
    return (
        f"otpauth://totp/{etiqueta}?secret={secreto}&issuer={quote(emisor)}"
        f"&algorithm=SHA1&digits={DIGITOS}&period={PASO_S}"
    )


def secreto_legible(secreto: str) -> str:
    """Agrupa el secreto de 4 en 4 para teclearlo a mano en la app autenticadora."""
    return " ".join(secreto[i:i + 4] for i in range(0, len(secreto), 4))
