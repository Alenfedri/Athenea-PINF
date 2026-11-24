"""Metadatos globales de la aplicación (clave → valor) en SQLite, p. ej. la versión del prompt de «vitaband-coach»."""
from __future__ import annotations

from typing import Optional

_ESQUEMA = "CREATE TABLE IF NOT EXISTS app_meta (clave TEXT PRIMARY KEY, valor TEXT NOT NULL);"


class AppMeta:
    def __init__(self, repo):
        self._c = repo.conexion
        with self._c:
            self._c.executescript(_ESQUEMA)

    def obtener(self, clave: str) -> Optional[str]:
        f = self._c.execute("SELECT valor FROM app_meta WHERE clave = ?", (clave,)).fetchone()
        return f[0] if f else None

    def guardar(self, clave: str, valor: str) -> None:
        with self._c:
            self._c.execute("INSERT INTO app_meta (clave, valor) VALUES (?, ?) "
                            "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor", (clave, str(valor)))
