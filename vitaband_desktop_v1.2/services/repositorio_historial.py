"""Repositorio local (SQLite) de mediciones, siempre acotado a UN usuario.

* RF-03: toda consulta y escritura filtra por ``usuario_id``; un usuario nunca ve
  ni toca los datos de otro.
* RF-13: cada medición lleva fecha y hora (``ts``, segundos Unix UTC).
* RF-17: es SQLite en disco, así que los datos persisten al cerrar la app.
* RF-20: ``uid`` único por usuario; reinsertar la misma medición (p. ej. al
  recibirla otra vez desde el móvil) no la duplica.
* RF-43: ``etiqueta`` = PERIODICO, ACTIVIDAD o AMBOS.
* RF-21: ``estado_sync`` = PENDIENTE, SINCRONIZADO o ERROR.

Hilos: úsese solo desde el hilo que lo creó (el de la UI).
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time as hora, timedelta
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

ETIQUETAS = ("PERIODICO", "ACTIVIDAD", "AMBOS")
ESTADOS_SYNC = ("PENDIENTE", "SINCRONIZADO", "ERROR")

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS mediciones (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id    INTEGER NOT NULL,
    uid           TEXT    NOT NULL,
    ts            INTEGER NOT NULL,                       -- segundos Unix (UTC)
    bpm           REAL    NOT NULL,                       -- media temporal de BPM
    rpm           REAL,
    temp_c        REAL,
    etiqueta      TEXT    NOT NULL DEFAULT 'PERIODICO'
                  CHECK (etiqueta IN ('PERIODICO','ACTIVIDAD','AMBOS')),
    actividad_id  INTEGER,
    estado_sync   TEXT    NOT NULL DEFAULT 'PENDIENTE'
                  CHECK (estado_sync IN ('PENDIENTE','SINCRONIZADO','ERROR')),
    UNIQUE (usuario_id, uid)
);
CREATE INDEX IF NOT EXISTS idx_med_usuario_ts   ON mediciones (usuario_id, ts);
CREATE INDEX IF NOT EXISTS idx_med_usuario_sync ON mediciones (usuario_id, estado_sync);
"""


@dataclass(frozen=True)
class RegistroMediaBpm:
    id: int
    uid: str
    instante: datetime          # hora local, sin zona
    media_bpm: float
    etiqueta: str
    estado_sync: str

    @property
    def sincronizado(self) -> bool:
        return self.estado_sync == "SINCRONIZADO"


class RepositorioHistorial:

    def __init__(self, ruta_bd: str, usuario_id: int):
        if usuario_id is None:
            raise ValueError("usuario_id es obligatorio (RF-03)")
        self._usuario_id = int(usuario_id)
        self._conn = sqlite3.connect(ruta_bd)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript(_ESQUEMA)

    @property
    def usuario_id(self) -> int:
        return self._usuario_id

    # --------------------------------------------------
    # ESCRITURA
    # --------------------------------------------------

    def guardar_medicion(
        self,
        bpm: float,
        instante: Optional[datetime] = None,
        uid: Optional[str] = None,
        etiqueta: str = "PERIODICO",
        rpm: Optional[float] = None,
        temp_c: Optional[float] = None,
        actividad_id: Optional[int] = None,
        estado_sync: str = "PENDIENTE",
    ) -> Optional[int]:
        """Guarda una medición. Devuelve su id, o None si ya existía ese ``uid`` (RF-20)."""
        if etiqueta not in ETIQUETAS:
            raise ValueError(f"Etiqueta no válida: {etiqueta}")
        if estado_sync not in ESTADOS_SYNC:
            raise ValueError(f"Estado de sincronización no válido: {estado_sync}")

        instante = instante or datetime.now()
        uid = uid or uuid.uuid4().hex

        with self._conn:
            cursor = self._conn.execute(
                "INSERT OR IGNORE INTO mediciones "
                "(usuario_id, uid, ts, bpm, rpm, temp_c, etiqueta, actividad_id, estado_sync) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (self._usuario_id, uid, int(instante.timestamp()), float(bpm),
                 rpm, temp_c, etiqueta, actividad_id, estado_sync),
            )
        return int(cursor.lastrowid) if cursor.rowcount else None

    def guardar_media_bpm(self, media_bpm: float, instante: Optional[datetime] = None) -> Optional[int]:
        """Atajo para la media de 10 s que llega por MQTT (historial periódico)."""
        return self.guardar_medicion(media_bpm, instante)

    def marcar_sincronizados(self, ids: Iterable[int]) -> None:
        self._cambiar_estado(ids, "SINCRONIZADO")

    def marcar_error(self, ids: Iterable[int]) -> None:
        self._cambiar_estado(ids, "ERROR")

    def _cambiar_estado(self, ids: Iterable[int], estado: str) -> None:
        ids = list(ids)
        if not ids:
            return
        marcas = ",".join("?" for _ in ids)
        with self._conn:
            self._conn.execute(
                f"UPDATE mediciones SET estado_sync = ? WHERE usuario_id = ? AND id IN ({marcas})",
                [estado, self._usuario_id, *ids],
            )

    # --------------------------------------------------
    # LECTURA
    # --------------------------------------------------

    def contar_por_estado(self) -> dict[str, int]:
        cuentas = {e: 0 for e in ESTADOS_SYNC}
        for fila in self._conn.execute(
            "SELECT estado_sync, COUNT(*) AS n FROM mediciones WHERE usuario_id = ? GROUP BY estado_sync",
            (self._usuario_id,),
        ):
            cuentas[fila["estado_sync"]] = int(fila["n"])
        return cuentas

    def contar_pendientes(self) -> int:
        return self.contar_por_estado()["PENDIENTE"]

    def obtener_pendientes(self, limite: int = 500) -> list[RegistroMediaBpm]:
        filas = self._conn.execute(
            "SELECT * FROM mediciones WHERE usuario_id = ? AND estado_sync = 'PENDIENTE' "
            "ORDER BY id LIMIT ?",
            (self._usuario_id, limite),
        ).fetchall()
        return [self._a_registro(f) for f in filas]

    def historial_por_fecha(self, dia: date) -> list[RegistroMediaBpm]:
        inicio = datetime.combine(dia, hora.min)
        fin = inicio + timedelta(days=1)
        filas = self._conn.execute(
            "SELECT * FROM mediciones WHERE usuario_id = ? AND ts >= ? AND ts < ? ORDER BY ts",
            (self._usuario_id, int(inicio.timestamp()), int(fin.timestamp())),
        ).fetchall()
        return [self._a_registro(f) for f in filas]

    def media_diaria(self, dia: date) -> Optional[float]:
        registros = self.historial_por_fecha(dia)
        if not registros:
            return None
        return sum(r.media_bpm for r in registros) / len(registros)

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
            uid=fila["uid"],
            instante=datetime.fromtimestamp(fila["ts"]),
            media_bpm=float(fila["bpm"]),
            etiqueta=fila["etiqueta"],
            estado_sync=fila["estado_sync"],
        )
