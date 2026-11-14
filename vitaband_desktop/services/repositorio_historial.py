"""Repositorio local (SQLite) del historial de media de BPM por fecha.

Sustituye al TinyDB original. No depende de Qt: es una clase Python pura que
usa solo la biblioteca estándar, por lo que se puede probar con ``:memory:``.

Hilos: la conexión se abre en el hilo que crea el repositorio (el de la UI) y
solo debe usarse desde él. Los mensajes MQTT llegan al ViewModel por señales Qt
en cola, así que las escrituras ya ocurren en ese hilo.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS media_bpm (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    instante      TEXT    NOT NULL,           -- ISO 8601, hora local
    fecha         TEXT    NOT NULL,           -- YYYY-MM-DD, para consultas por día
    media_bpm     REAL    NOT NULL,
    sincronizado  INTEGER NOT NULL DEFAULT 0  -- 0 = pendiente, 1 = enviado
);
CREATE INDEX IF NOT EXISTS idx_media_bpm_fecha ON media_bpm (fecha);
CREATE INDEX IF NOT EXISTS idx_media_bpm_sync  ON media_bpm (sincronizado);
"""


@dataclass(frozen=True)
class RegistroMediaBpm:
    id: int
    instante: datetime
    media_bpm: float
    sincronizado: bool


class RepositorioHistorial:

    def __init__(self, ruta_bd: str = "vitaband_historial.db"):
        self._conn = sqlite3.connect(ruta_bd)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript(_ESQUEMA)

    # --------------------------------------------------
    # ESCRITURA
    # --------------------------------------------------

    def guardar_media_bpm(
        self,
        media_bpm: float,
        instante: Optional[datetime] = None
    ) -> int:
        """Guarda una media de BPM como pendiente de sincronizar. Devuelve su id."""
        instante = instante or datetime.now()

        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO media_bpm (instante, fecha, media_bpm) VALUES (?, ?, ?)",
                (instante.isoformat(timespec="seconds"),
                 instante.date().isoformat(),
                 float(media_bpm)),
            )

        return int(cursor.lastrowid)

    def marcar_sincronizados(self, ids: Iterable[int]) -> None:
        ids = list(ids)
        if not ids:
            return

        marcas = ",".join("?" for _ in ids)
        with self._conn:
            self._conn.execute(
                f"UPDATE media_bpm SET sincronizado = 1 WHERE id IN ({marcas})",
                ids,
            )

    # --------------------------------------------------
    # LECTURA
    # --------------------------------------------------

    def contar_pendientes(self) -> int:
        fila = self._conn.execute(
            "SELECT COUNT(*) AS n FROM media_bpm WHERE sincronizado = 0"
        ).fetchone()
        return int(fila["n"])

    def obtener_pendientes(self, limite: int = 500) -> list[RegistroMediaBpm]:
        filas = self._conn.execute(
            "SELECT * FROM media_bpm WHERE sincronizado = 0 ORDER BY id LIMIT ?",
            (limite,),
        ).fetchall()
        return [self._a_registro(f) for f in filas]

    def historial_por_fecha(self, dia: date) -> list[RegistroMediaBpm]:
        filas = self._conn.execute(
            "SELECT * FROM media_bpm WHERE fecha = ? ORDER BY instante",
            (dia.isoformat(),),
        ).fetchall()
        return [self._a_registro(f) for f in filas]

    def media_diaria(self, dia: date) -> Optional[float]:
        fila = self._conn.execute(
            "SELECT AVG(media_bpm) AS media FROM media_bpm WHERE fecha = ?",
            (dia.isoformat(),),
        ).fetchone()
        return None if fila["media"] is None else float(fila["media"])

    # --------------------------------------------------
    # CIERRE
    # --------------------------------------------------

    def cerrar(self) -> None:
        try:
            self._conn.close()
        except Exception:
            logger.exception("Error cerrando la base de datos del historial")

    @staticmethod
    def _a_registro(fila: sqlite3.Row) -> RegistroMediaBpm:
        return RegistroMediaBpm(
            id=int(fila["id"]),
            instante=datetime.fromisoformat(fila["instante"]),
            media_bpm=float(fila["media_bpm"]),
            sincronizado=bool(fila["sincronizado"]),
        )
