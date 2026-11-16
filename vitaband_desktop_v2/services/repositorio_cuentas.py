"""Persistencia de cuentas de usuario en SQLite (RF-41, RF-01, RF-42).

La contraseña nunca se guarda: se guarda un hash scrypt con sal aleatoria.
El secreto TOTP sí se guarda tal cual (hace falta para verificar los códigos);
quien tenga acceso al archivo .db puede leerlo.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import sqlite3
import time
from dataclasses import dataclass
from typing import Optional

from services.repositorio_historial import TABLAS_DE_USUARIO

logger = logging.getLogger(__name__)

# Parámetros scrypt (OWASP: N=2^15 recomendado; 2^14 mantiene el login ágil en un PC)
_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_MAXMEM = 64 * 1024 * 1024

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    email               TEXT    NOT NULL UNIQUE,      -- normalizado (minúsculas)
    nombre              TEXT    NOT NULL,
    pw_hash             BLOB    NOT NULL,
    pw_sal              BLOB    NOT NULL,
    totp_secreto        TEXT    NOT NULL,
    totp_activo         INTEGER NOT NULL DEFAULT 0,   -- 1 tras el primer código válido
    totp_ultimo_paso    INTEGER NOT NULL DEFAULT -1,  -- anti-reutilización de códigos
    intentos_fallidos   INTEGER NOT NULL DEFAULT 0,
    bloqueado_hasta     REAL    NOT NULL DEFAULT 0,
    creado_ts           REAL    NOT NULL
);
"""


class EmailDuplicado(Exception):
    pass


@dataclass(frozen=True)
class Cuenta:
    id: int
    email: str
    nombre: str
    totp_secreto: str
    totp_activo: bool
    totp_ultimo_paso: int
    intentos_fallidos: int
    bloqueado_hasta: float


def hash_password(password: str, sal: Optional[bytes] = None) -> tuple[bytes, bytes]:
    sal = sal or secrets.token_bytes(16)
    clave = hashlib.scrypt(
        password.encode("utf-8"), salt=sal,
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, maxmem=_SCRYPT_MAXMEM, dklen=32,
    )
    return clave, sal


def comprobar_password(password: str, esperado: bytes, sal: bytes) -> bool:
    candidato, _ = hash_password(password, sal)
    return hmac.compare_digest(candidato, esperado)


class RepositorioCuentas:

    def __init__(self, ruta_bd: str = "vitaband_historial.db"):
        self._conn = sqlite3.connect(ruta_bd)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript(_ESQUEMA)

    # --------------------------------------------------
    # ALTA / CONSULTA
    # --------------------------------------------------

    def crear(
        self, email: str, nombre: str, password: str, totp_secreto: str,
        ahora: Optional[float] = None,
    ) -> int:
        """Crea la cuenta. Lanza EmailDuplicado si el correo ya existe (RF-41)."""
        clave, sal = hash_password(password)
        try:
            with self._conn:
                cursor = self._conn.execute(
                    "INSERT INTO usuarios (email, nombre, pw_hash, pw_sal, totp_secreto, creado_ts) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (email, nombre, clave, sal, totp_secreto,
                     time.time() if ahora is None else ahora),
                )
        except sqlite3.IntegrityError as exc:
            raise EmailDuplicado(email) from exc
        return int(cursor.lastrowid)

    def existe_email(self, email: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM usuarios WHERE email = ?", (email,)
        ).fetchone() is not None

    def obtener_por_email(self, email: str) -> Optional[Cuenta]:
        fila = self._conn.execute("SELECT * FROM usuarios WHERE email = ?", (email,)).fetchone()
        return self._a_cuenta(fila)

    def obtener_por_id(self, usuario_id: int) -> Optional[Cuenta]:
        fila = self._conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        return self._a_cuenta(fila)

    def password_correcta(self, usuario_id: int, password: str) -> bool:
        fila = self._conn.execute(
            "SELECT pw_hash, pw_sal FROM usuarios WHERE id = ?", (usuario_id,)
        ).fetchone()
        if fila is None:
            return False
        return comprobar_password(password, fila["pw_hash"], fila["pw_sal"])

    @staticmethod
    def gastar_tiempo_de_hash(password: str) -> None:
        """Calcula un hash descartable para igualar la latencia cuando el correo no existe."""
        hash_password(password)

    # --------------------------------------------------
    # ESTADO DE SEGURIDAD
    # --------------------------------------------------

    def registrar_fallo(self, usuario_id: int, max_intentos: int, bloqueo_s: float, ahora: float) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE usuarios SET intentos_fallidos = intentos_fallidos + 1 WHERE id = ?",
                (usuario_id,),
            )
            self._conn.execute(
                "UPDATE usuarios SET bloqueado_hasta = ?, intentos_fallidos = 0 "
                "WHERE id = ? AND intentos_fallidos >= ?",
                (ahora + bloqueo_s, usuario_id, max_intentos),
            )

    def limpiar_fallos(self, usuario_id: int) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE usuarios SET intentos_fallidos = 0, bloqueado_hasta = 0 WHERE id = ?",
                (usuario_id,),
            )

    def guardar_ultimo_paso(self, usuario_id: int, paso: int, activar: bool = False) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE usuarios SET totp_ultimo_paso = ?, totp_activo = CASE WHEN ? THEN 1 ELSE totp_activo END "
                "WHERE id = ?",
                (paso, 1 if activar else 0, usuario_id),
            )

    def reemplazar_secreto_inactivo(self, usuario_id: int, nuevo_secreto: str) -> None:
        """Solo para cuentas que nunca completaron el alta de MFA."""
        with self._conn:
            self._conn.execute(
                "UPDATE usuarios SET totp_secreto = ?, totp_ultimo_paso = -1 "
                "WHERE id = ? AND totp_activo = 0",
                (nuevo_secreto, usuario_id),
            )

    # --------------------------------------------------
    # ELIMINACIÓN (RF-39)
    # --------------------------------------------------

    def eliminar(self, usuario_id: int) -> bool:
        """Elimina la cuenta y TODOS sus datos asociados en una sola transacción.

        Borra mediciones, actividades, ECG, observaciones y registro de sincronización
        del usuario; si algo falla no se borra nada. Devuelve False si la cuenta no existía.
        Con ``secure_delete`` el contenido borrado se sobrescribe en el archivo.

        No alcanza a copias fuera de la base de datos (CSV exportados, archivos de
        intercambio del móvil, copias de seguridad).
        """
        self._conn.execute("PRAGMA secure_delete = ON")
        with self._conn:
            for tabla in TABLAS_DE_USUARIO:
                existe = self._conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (tabla,)
                ).fetchone()
                if existe:
                    self._conn.execute(f"DELETE FROM {tabla} WHERE usuario_id = ?", (usuario_id,))
            return self._conn.execute("DELETE FROM usuarios WHERE id = ?", (usuario_id,)).rowcount > 0

    def cerrar(self) -> None:
        try:
            self._conn.close()
        except Exception:
            logger.exception("Error cerrando la base de datos de cuentas")

    @staticmethod
    def _a_cuenta(fila: Optional[sqlite3.Row]) -> Optional[Cuenta]:
        if fila is None:
            return None
        return Cuenta(
            id=int(fila["id"]),
            email=fila["email"],
            nombre=fila["nombre"],
            totp_secreto=fila["totp_secreto"],
            totp_activo=bool(fila["totp_activo"]),
            totp_ultimo_paso=int(fila["totp_ultimo_paso"]),
            intentos_fallidos=int(fila["intentos_fallidos"]),
            bloqueado_hasta=float(fila["bloqueado_hasta"]),
        )
