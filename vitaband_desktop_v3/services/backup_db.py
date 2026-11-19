"""Copia de seguridad y restauración de la base de datos en un .zip.

Exportar: volcado consistente en caliente (``sqlite3.Connection.backup``) + ``manifest.json``.
Restaurar: valida el zip y la integridad, guarda un ``.bak`` de la BD actual y vuelca la copia
sobre la conexión abierta (sin sustituir el archivo, así la sesión sigue funcionando).
La copia incluye TODA la base (cuentas con sus hashes y secretos TOTP): hay que guardarla a buen recaudo.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime

VERSION_BACKUP = 1
NOMBRE_BD = "vitaband.db"
NOMBRE_MANIFEST = "manifest.json"
TABLAS_REQUERIDAS = ("usuarios", "mediciones")


class BackupInvalido(Exception):
    """El zip no es una copia válida de VitaBand."""


def ruta_de(conn: sqlite3.Connection) -> str:
    """Ruta del archivo de la BD ('' si es en memoria)."""
    return next((f[2] for f in conn.execute("PRAGMA database_list") if f[1] == "main"), "") or ""


def exportar_backup(conn: sqlite3.Connection, ruta_zip: str, ahora: datetime | None = None) -> str:
    carpeta = tempfile.mkdtemp(prefix="vitaband_bk_")
    try:
        tmp_bd = os.path.join(carpeta, NOMBRE_BD)
        destino = sqlite3.connect(tmp_bd)
        try:
            conn.backup(destino)
        finally:
            destino.close()
        manifest = {"app": "VitaBand Desktop", "version_backup": VERSION_BACKUP,
                    "fecha": (ahora or datetime.now()).isoformat(timespec="seconds"), "archivo_bd": NOMBRE_BD}
        with zipfile.ZipFile(ruta_zip, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(tmp_bd, NOMBRE_BD)
            z.writestr(NOMBRE_MANIFEST, json.dumps(manifest, indent=2))
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)
    return ruta_zip


def _extraer_y_validar(ruta_zip: str, carpeta: str) -> str:
    try:
        with zipfile.ZipFile(ruta_zip) as z:
            nombres = z.namelist()
            if NOMBRE_BD not in nombres or NOMBRE_MANIFEST not in nombres:
                raise BackupInvalido("El .zip no contiene una copia de VitaBand (faltan vitaband.db o manifest.json).")
            try:
                manifest = json.loads(z.read(NOMBRE_MANIFEST))
            except ValueError as e:
                raise BackupInvalido("El manifest.json está dañado.") from e
            if manifest.get("version_backup") != VERSION_BACKUP:
                raise BackupInvalido("La versión de la copia no es compatible.")
            ruta_bd = os.path.join(carpeta, NOMBRE_BD)
            with z.open(NOMBRE_BD) as origen, open(ruta_bd, "wb") as destino:
                shutil.copyfileobj(origen, destino)
    except zipfile.BadZipFile as e:
        raise BackupInvalido("El archivo no es un .zip válido.") from e
    try:
        con = sqlite3.connect(ruta_bd)
        try:
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BackupInvalido("La base de datos de la copia está dañada.")
            tablas = {f[0] for f in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            con.close()
    except sqlite3.DatabaseError as e:
        raise BackupInvalido("El archivo de la copia no es una base de datos SQLite.") from e
    if not set(TABLAS_REQUERIDAS) <= tablas:
        raise BackupInvalido("La base de datos de la copia no tiene las tablas de VitaBand.")
    return ruta_bd


def restaurar_backup(conn: sqlite3.Connection, ruta_zip: str, usuario_id: int) -> str:
    """Restaura la copia sobre ``conn``. Devuelve la ruta del .bak creado ('' si la BD es en memoria)."""
    carpeta = tempfile.mkdtemp(prefix="vitaband_rs_")
    try:
        ruta_bd = _extraer_y_validar(ruta_zip, carpeta)
        origen = sqlite3.connect(ruta_bd)
        try:
            if origen.execute("SELECT 1 FROM usuarios WHERE id = ?", (usuario_id,)).fetchone() is None:
                raise BackupInvalido("La copia no contiene tu cuenta: restaurarla te dejaría sin acceso.")
            bak = ""
            actual = ruta_de(conn)
            if actual:
                bak = f"{actual}.bak"
                seguridad = sqlite3.connect(bak)
                try:
                    conn.backup(seguridad)
                finally:
                    seguridad.close()
            origen.backup(conn)
        finally:
            origen.close()
        return bak
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)
