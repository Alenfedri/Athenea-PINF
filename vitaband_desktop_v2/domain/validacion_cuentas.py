"""Validación pura de los datos de registro (RF-41). Sin Qt ni base de datos."""

from __future__ import annotations

import re

PASSWORD_MIN = 10
NOMBRE_MIN = 2
NOMBRE_MAX = 60

_RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


def normalizar_email(email: str) -> str:
    """Forma canónica para comparar duplicados: sin espacios y en minúsculas."""
    return (email or "").strip().casefold()


def validar_email(email: str) -> list[str]:
    email = normalizar_email(email)
    if not email:
        return ["El correo es obligatorio."]
    if len(email) > 254 or not _RE_EMAIL.match(email):
        return ["El correo no tiene un formato válido."]
    return []


def validar_nombre(nombre: str) -> list[str]:
    nombre = (nombre or "").strip()
    if len(nombre) < NOMBRE_MIN:
        return [f"El nombre debe tener al menos {NOMBRE_MIN} caracteres."]
    if len(nombre) > NOMBRE_MAX:
        return [f"El nombre no puede superar {NOMBRE_MAX} caracteres."]
    return []


def validar_password(password: str, email: str = "") -> list[str]:
    errores: list[str] = []
    password = password or ""

    if len(password) < PASSWORD_MIN:
        errores.append(f"La contraseña debe tener al menos {PASSWORD_MIN} caracteres.")
    if not any(c.isalpha() for c in password):
        errores.append("La contraseña debe incluir al menos una letra.")
    if not any(c.isdigit() for c in password):
        errores.append("La contraseña debe incluir al menos un número.")
    if password and normalizar_email(password) == normalizar_email(email):
        errores.append("La contraseña no puede ser igual al correo.")
    return errores


def validar_registro(
    nombre: str, email: str, password: str, password_repetida: str
) -> list[str]:
    errores = validar_nombre(nombre) + validar_email(email) + validar_password(password, email)
    if password != password_repetida:
        errores.append("Las contraseñas no coinciden.")
    return errores
