"""Repositorio local (SQLite) de datos fisiológicos, siempre acotado a UN usuario.

SQLite es el almacenamiento local de la aplicación de escritorio.

* RF-03: toda consulta y escritura filtra por ``usuario_id``.
* RF-12/13: mediciones periódicas con fecha y hora (``ts``, segundos Unix UTC).
* RF-17: persisten en disco al cerrar la aplicación.
* RF-20: ``uid`` único por usuario; reinsertar lo mismo no duplica nada.
* RF-33: ECG histórico como envolvente mín/máx por segundo (ver ecg_historico).
* RF-40/44/46: purga por vencimiento sin perder actividades conservadas.
* RF-43: ``etiqueta`` = PERIODICO, ACTIVIDAD o AMBOS.

Compatibilidad: una base de datos creada por versiones anteriores se actualiza
sola (se añade la columna ``nivel_actividad``; ``estado_sync`` se ignora).

Hilos: úsese solo desde el hilo que lo creó (el de la UI).
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional, Sequence

from domain import ecg_historico as ecg
from domain import hrv
from domain.modelos import (
    ETIQUETA_ACTIVIDAD,
    ETIQUETA_AMBOS,
    ETIQUETA_PERIODICO,
    ETIQUETAS,
    Actividad,
    Medicion,
    ObservacionGuardada,
)
from domain.paquete_sync import PaqueteInvalido, PaqueteSync

logger = logging.getLogger(__name__)

AMBITO_PERIODICO = "periodico"
AMBITO_ACTIVIDAD = "actividad"

# Tablas con datos de un usuario (todas llevan ``usuario_id``). RepositorioCuentas la usa
# para no dejar datos personales huérfanos al eliminar una cuenta (RF-39).
TABLAS_DE_USUARIO = ("mediciones", "actividades", "ecg_bloques", "observaciones", "sync_archivos", "hrv_reposo")
_LOTE = 500                                    # ids por sentencia SQL (límite de variables de SQLite)


_ESQUEMA = """
CREATE TABLE IF NOT EXISTS mediciones (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id       INTEGER NOT NULL,
    uid              TEXT    NOT NULL,
    ts               INTEGER NOT NULL,                  -- segundos Unix (UTC)
    bpm              REAL    NOT NULL,
    rpm              REAL,
    temp_c           REAL,
    etiqueta         TEXT    NOT NULL DEFAULT 'PERIODICO'
                     CHECK (etiqueta IN ('PERIODICO','ACTIVIDAD','AMBOS')),
    actividad_id     INTEGER,
    nivel_actividad  INTEGER,
    UNIQUE (usuario_id, uid)
);
CREATE INDEX IF NOT EXISTS idx_med_usuario_ts ON mediciones (usuario_id, ts);

CREATE TABLE IF NOT EXISTS actividades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id  INTEGER NOT NULL,
    uid         TEXT    NOT NULL,
    inicio_ts   INTEGER NOT NULL,
    fin_ts      INTEGER NOT NULL,
    tipo        TEXT,
    UNIQUE (usuario_id, uid)
);
CREATE INDEX IF NOT EXISTS idx_act_usuario_ini ON actividades (usuario_id, inicio_ts);

CREATE TABLE IF NOT EXISTS ecg_bloques (
    usuario_id  INTEGER NOT NULL,
    minuto      INTEGER NOT NULL,                       -- ts // 60
    datos       BLOB    NOT NULL,                       -- 60 pares min/max int16
    PRIMARY KEY (usuario_id, minuto)
);

-- HRV (RMSSD) de ventanas de 1 min en reposo, calculada en directo (no se guarda la señal)
CREATE TABLE IF NOT EXISTS hrv_reposo (
    usuario_id  INTEGER NOT NULL,
    ts          INTEGER NOT NULL,                       -- inicio de la ventana (segundos Unix)
    rmssd_ms    REAL    NOT NULL,
    fc_media    REAL    NOT NULL,
    latidos     INTEGER NOT NULL,
    PRIMARY KEY (usuario_id, ts)
);

CREATE TABLE IF NOT EXISTS observaciones (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id      INTEGER NOT NULL,
    tipo            TEXT    NOT NULL,                   -- DIARIA | ACTIVIDAD
    clave           TEXT    NOT NULL,                   -- fecha ISO o id de actividad
    actividad_id    INTEGER,
    periodo_inicio  INTEGER NOT NULL,
    periodo_fin     INTEGER NOT NULL,
    texto           TEXT    NOT NULL,
    generada_ts     INTEGER NOT NULL,
    UNIQUE (usuario_id, tipo, clave)
);

CREATE TABLE IF NOT EXISTS sync_archivos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id  INTEGER NOT NULL,
    nombre      TEXT    NOT NULL,
    sha256      TEXT    NOT NULL,
    estado      TEXT    NOT NULL CHECK (estado IN ('IMPORTADO','ERROR')),
    detalle     TEXT    NOT NULL DEFAULT '',
    ts          INTEGER NOT NULL,
    UNIQUE (usuario_id, sha256)
);
"""


@dataclass(frozen=True)
class ResultadoImportacion:
    mediciones_nuevas: int = 0
    mediciones_duplicadas: int = 0
    actividades_nuevas: int = 0
    actividades_duplicadas: int = 0
    segundos_ecg_nuevos: int = 0


@dataclass(frozen=True)
class ResultadoPurga:
    mediciones: int = 0
    actividades: int = 0
    bloques_ecg: int = 0
    observaciones: int = 0


class RepositorioHistorial:

    def __init__(self, ruta_bd: str, usuario_id: int):
        if usuario_id is None:
            raise ValueError("usuario_id es obligatorio (RF-03)")
        self._usuario_id = int(usuario_id)
        self._conn = sqlite3.connect(ruta_bd)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript(_ESQUEMA)
            self._migrar()

    def _migrar(self) -> None:
        columnas = {f["name"] for f in self._conn.execute("PRAGMA table_info(mediciones)")}
        if "nivel_actividad" not in columnas:
            self._conn.execute("ALTER TABLE mediciones ADD COLUMN nivel_actividad INTEGER")

    @property
    def usuario_id(self) -> int:
        return self._usuario_id

    # ==================================================================
    # MEDICIONES (RF-12, 13, 43)
    # ==================================================================

    def guardar_medicion(
        self,
        bpm: float,
        instante: Optional[datetime] = None,
        uid: Optional[str] = None,
        etiqueta: str = ETIQUETA_PERIODICO,
        rpm: Optional[float] = None,
        temp_c: Optional[float] = None,
        actividad_id: Optional[int] = None,
        nivel_actividad: Optional[int] = None,
    ) -> Optional[int]:
        """Guarda una medición. Devuelve su id, o None si ya existía ese ``uid``."""
        if etiqueta not in ETIQUETAS:
            raise ValueError(f"Etiqueta no válida: {etiqueta}")

        instante = instante or datetime.now()
        with self._conn:
            cursor = self._conn.execute(
                "INSERT OR IGNORE INTO mediciones "
                "(usuario_id, uid, ts, bpm, rpm, temp_c, etiqueta, actividad_id, nivel_actividad) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (self._usuario_id, uid or uuid.uuid4().hex, int(instante.timestamp()),
                 float(bpm), rpm, temp_c, etiqueta, actividad_id, nivel_actividad),
            )
        return int(cursor.lastrowid) if cursor.rowcount else None

    def guardar_media_bpm(self, media_bpm: float, instante: Optional[datetime] = None) -> Optional[int]:
        return self.guardar_medicion(media_bpm, instante)

    def contar_mediciones(self) -> int:
        fila = self._conn.execute(
            "SELECT COUNT(*) AS n FROM mediciones WHERE usuario_id = ?", (self._usuario_id,)
        ).fetchone()
        return int(fila["n"])

    def mediciones_rango(
        self, desde_ts: int, hasta_ts: int, ambito: Optional[str] = None
    ) -> list[Medicion]:
        """Mediciones con ``desde_ts <= ts < hasta_ts``, de más antigua a más reciente.

        ``ambito``: "periodico" (PERIODICO y AMBOS), "actividad" (ACTIVIDAD y AMBOS) o
        None (todas). RF-45: cada historial se consulta por separado.
        """
        filtro = ""
        if ambito == AMBITO_PERIODICO:
            filtro = " AND etiqueta IN ('PERIODICO','AMBOS')"
        elif ambito == AMBITO_ACTIVIDAD:
            filtro = " AND etiqueta IN ('ACTIVIDAD','AMBOS')"
        elif ambito is not None:
            raise ValueError(f"Ámbito desconocido: {ambito}")

        filas = self._conn.execute(
            "SELECT * FROM mediciones WHERE usuario_id = ? AND ts >= ? AND ts < ?"
            f"{filtro} ORDER BY ts, id",
            (self._usuario_id, int(desde_ts), int(hasta_ts)),
        ).fetchall()
        return [self._a_medicion(f) for f in filas]

    def mediciones_de_actividad(self, actividad_id: int) -> list[Medicion]:
        filas = self._conn.execute(
            "SELECT * FROM mediciones WHERE usuario_id = ? AND actividad_id = ? ORDER BY ts, id",
            (self._usuario_id, actividad_id),
        ).fetchall()
        return [self._a_medicion(f) for f in filas]

    def todas_las_mediciones(self) -> list[Medicion]:
        filas = self._conn.execute(
            "SELECT * FROM mediciones WHERE usuario_id = ? ORDER BY ts, id", (self._usuario_id,)
        ).fetchall()
        return [self._a_medicion(f) for f in filas]

    def rango_periodico(self) -> Optional[tuple[int, int]]:
        """(primer ts, último ts) del historial periódico, o None si está vacío."""
        fila = self._conn.execute(
            "SELECT MIN(ts) AS a, MAX(ts) AS b FROM mediciones "
            "WHERE usuario_id = ? AND etiqueta IN ('PERIODICO','AMBOS')",
            (self._usuario_id,),
        ).fetchone()
        return None if fila["a"] is None else (int(fila["a"]), int(fila["b"]))

    # ==================================================================
    # ACTIVIDADES (RF-32, 43, 44, 45)
    # ==================================================================

    def guardar_actividad(
        self, uid: str, inicio_ts: int, fin_ts: int, tipo: Optional[str] = None
    ) -> Optional[int]:
        """Guarda una actividad. Devuelve su id, o None si ya existía ese ``uid``."""
        if fin_ts < inicio_ts:
            raise ValueError("La actividad termina antes de empezar")
        with self._conn:
            cursor = self._conn.execute(
                "INSERT OR IGNORE INTO actividades (usuario_id, uid, inicio_ts, fin_ts, tipo) "
                "VALUES (?, ?, ?, ?, ?)",
                (self._usuario_id, uid, int(inicio_ts), int(fin_ts), tipo),
            )
        return int(cursor.lastrowid) if cursor.rowcount else None

    def obtener_actividad(self, actividad_id: int) -> Optional[Actividad]:
        fila = self._conn.execute(
            "SELECT * FROM actividades WHERE usuario_id = ? AND id = ?",
            (self._usuario_id, actividad_id),
        ).fetchone()
        return self._a_actividad(fila) if fila else None

    def actividades_rango(self, desde_ts: int, hasta_ts: int) -> list[Actividad]:
        """Actividades cuyo inicio está en [desde_ts, hasta_ts), de más reciente a más antigua."""
        filas = self._conn.execute(
            "SELECT * FROM actividades WHERE usuario_id = ? AND inicio_ts >= ? AND inicio_ts < ? "
            "ORDER BY inicio_ts DESC, id DESC",
            (self._usuario_id, int(desde_ts), int(hasta_ts)),
        ).fetchall()
        return [self._a_actividad(f) for f in filas]

    # ==================================================================
    # ECG HISTÓRICO (RF-33, 34)
    # ==================================================================

    def guardar_ecg_segundos(self, segundos: Sequence[ecg.SegundoEcg]) -> int:
        """Guarda envolventes de un segundo. Devuelve cuántos segundos eran nuevos."""
        with self._conn:
            return self._ecg_sin_commit(segundos)

    def _ecg_sin_commit(self, segundos: Sequence[ecg.SegundoEcg]) -> int:
        por_minuto: dict[int, list[ecg.SegundoEcg]] = {}
        for s in segundos:
            por_minuto.setdefault(ecg.minuto_de(s.ts), []).append(s)

        nuevos = 0
        for minuto, lista in por_minuto.items():
            fila = self._conn.execute(
                "SELECT datos FROM ecg_bloques WHERE usuario_id = ? AND minuto = ?",
                (self._usuario_id, minuto),
            ).fetchone()
            previo = ecg.desempaquetar(fila["datos"]) if fila else ecg.bloque_vacio()
            nuevo = ecg.fusionar(previo, lista)
            nuevos += sum(1 for a, b in zip(previo[::2], nuevo[::2]) if a == ecg.NODATA and b != ecg.NODATA)
            self._conn.execute(
                "INSERT OR REPLACE INTO ecg_bloques (usuario_id, minuto, datos) VALUES (?, ?, ?)",
                (self._usuario_id, minuto, ecg.empaquetar(nuevo)),
            )
        return nuevos

    def ecg_rango(self, desde_ts: int, hasta_ts: int) -> list[ecg.SegundoEcg]:
        """Segundos con ECG almacenado en [desde_ts, hasta_ts)."""
        if hasta_ts <= desde_ts:
            return []
        filas = self._conn.execute(
            "SELECT minuto, datos FROM ecg_bloques WHERE usuario_id = ? AND minuto >= ? AND minuto <= ? "
            "ORDER BY minuto",
            (self._usuario_id, ecg.minuto_de(desde_ts), ecg.minuto_de(hasta_ts - 1)),
        ).fetchall()
        salida: list[ecg.SegundoEcg] = []
        for f in filas:
            for s in ecg.segundos_de_bloque(f["minuto"], ecg.desempaquetar(f["datos"])):
                if desde_ts <= s.ts < hasta_ts:
                    salida.append(s)
        return salida

    def contar_segundos_ecg(self) -> int:
        total = 0
        for f in self._conn.execute(
            "SELECT datos FROM ecg_bloques WHERE usuario_id = ?", (self._usuario_id,)
        ):
            total += len(ecg.segundos_de_bloque(0, ecg.desempaquetar(f["datos"])))
        return total

    # ==================================================================
    # OBSERVACIONES (RF-24, 29, 49)
    # ==================================================================

    def guardar_hrv(self, r: hrv.ResultadoHrv) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO hrv_reposo (usuario_id, ts, rmssd_ms, fc_media, latidos) "
                "VALUES (?, ?, ?, ?, ?)",
                (self._usuario_id, r.ts, r.rmssd_ms, r.fc_media, r.latidos))

    def hrv_rango(self, desde_ts: int, hasta_ts: int) -> list[hrv.ResultadoHrv]:
        filas = self._conn.execute(
            "SELECT ts, rmssd_ms, fc_media, latidos FROM hrv_reposo "
            "WHERE usuario_id = ? AND ts >= ? AND ts < ? ORDER BY ts",
            (self._usuario_id, int(desde_ts), int(hasta_ts))).fetchall()
        return [hrv.ResultadoHrv(f["ts"], f["rmssd_ms"], f["fc_media"], f["latidos"]) for f in filas]

    def guardar_observacion(
        self,
        tipo: str,
        clave: str,
        texto: str,
        periodo_inicio_ts: int,
        periodo_fin_ts: int,
        ahora_ts: int,
        actividad_id: Optional[int] = None,
    ) -> bool:
        """Crea o actualiza la observación de un periodo/actividad. True si algo cambió."""
        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO observaciones "
                "(usuario_id, tipo, clave, actividad_id, periodo_inicio, periodo_fin, texto, generada_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (usuario_id, tipo, clave) DO UPDATE SET "
                "texto = excluded.texto, periodo_inicio = excluded.periodo_inicio, "
                "periodo_fin = excluded.periodo_fin, generada_ts = excluded.generada_ts "
                "WHERE observaciones.texto != excluded.texto",
                (self._usuario_id, tipo, clave, actividad_id, int(periodo_inicio_ts),
                 int(periodo_fin_ts), texto, int(ahora_ts)),
            )
        return cursor.rowcount > 0

    def observaciones_rango(
        self, desde_ts: int, hasta_ts: int, tipo: Optional[str] = None
    ) -> list[ObservacionGuardada]:
        """Observaciones cuyo periodo se solapa con [desde_ts, hasta_ts)."""
        filtro = " AND tipo = ?" if tipo else ""
        params = [self._usuario_id, int(hasta_ts), int(desde_ts)] + ([tipo] if tipo else [])
        filas = self._conn.execute(
            "SELECT * FROM observaciones WHERE usuario_id = ? AND periodo_inicio < ? AND periodo_fin > ?"
            f"{filtro} ORDER BY periodo_inicio DESC, id DESC",
            params,
        ).fetchall()
        return [self._a_observacion(f) for f in filas]

    def observacion_actividad(self, actividad_id: int) -> Optional[ObservacionGuardada]:
        fila = self._conn.execute(
            "SELECT * FROM observaciones WHERE usuario_id = ? AND tipo = 'ACTIVIDAD' AND actividad_id = ?",
            (self._usuario_id, actividad_id),
        ).fetchone()
        return self._a_observacion(fila) if fila else None

    # ==================================================================
    # IMPORTACIÓN DE PAQUETES (RF-18, 20)
    # ==================================================================

    def importar_paquete(self, paquete: PaqueteSync) -> ResultadoImportacion:
        """Importa un paquete ya validado, todo o nada, sin duplicar lo existente."""
        med_nuevas = med_dup = act_nuevas = act_dup = 0

        with self._conn:   # si algo falla, se deshace todo
            ids_actividad: dict[str, int] = {}

            for a in paquete.actividades:
                cursor = self._conn.execute(
                    "INSERT OR IGNORE INTO actividades (usuario_id, uid, inicio_ts, fin_ts, tipo) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (self._usuario_id, a.uid, a.inicio_ts, a.fin_ts, a.tipo),
                )
                if cursor.rowcount:
                    act_nuevas += 1
                    ids_actividad[a.uid] = int(cursor.lastrowid)
                else:
                    act_dup += 1
                    ids_actividad[a.uid] = self._id_actividad(a.uid)

            for m in paquete.mediciones:
                actividad_id = None
                if m.actividad_uid:
                    actividad_id = ids_actividad.get(m.actividad_uid) or self._id_actividad(m.actividad_uid)
                    if actividad_id is None:
                        raise PaqueteInvalido(
                            [f"La medición «{m.uid}» apunta a una actividad inexistente («{m.actividad_uid}»)."]
                        )
                cursor = self._conn.execute(
                    "INSERT OR IGNORE INTO mediciones "
                    "(usuario_id, uid, ts, bpm, rpm, temp_c, etiqueta, actividad_id, nivel_actividad) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (self._usuario_id, m.uid, m.ts, m.bpm, m.rpm, m.temp_c, m.etiqueta,
                     actividad_id, m.nivel_actividad),
                )
                if cursor.rowcount:
                    med_nuevas += 1
                else:
                    med_dup += 1

            segundos_nuevos = 0
            for b in paquete.ecg:
                segs = [ecg.SegundoEcg(b.ts_inicio + i, mn, mx)
                        for i, (mn, mx) in enumerate(zip(b.minimos, b.maximos))]
                segundos_nuevos += self._ecg_sin_commit(segs)

        return ResultadoImportacion(med_nuevas, med_dup, act_nuevas, act_dup, segundos_nuevos)

    def _id_actividad(self, uid: str) -> Optional[int]:
        fila = self._conn.execute(
            "SELECT id FROM actividades WHERE usuario_id = ? AND uid = ?", (self._usuario_id, uid)
        ).fetchone()
        return int(fila["id"]) if fila else None

    # ==================================================================
    # ARCHIVOS DE SINCRONIZACIÓN (RF-21)
    # ==================================================================

    def sync_registrar(self, nombre: str, sha256: str, estado: str, detalle: str, ts: int) -> None:
        if estado not in ("IMPORTADO", "ERROR"):
            raise ValueError(f"Estado de sincronización no válido: {estado}")
        with self._conn:
            self._conn.execute(
                "INSERT INTO sync_archivos (usuario_id, nombre, sha256, estado, detalle, ts) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (usuario_id, sha256) DO UPDATE SET "
                "nombre = excluded.nombre, estado = excluded.estado, detalle = excluded.detalle, ts = excluded.ts",
                (self._usuario_id, nombre, sha256, estado, detalle, int(ts)),
            )

    def sync_estado(self, sha256: str) -> Optional[str]:
        fila = self._conn.execute(
            "SELECT estado FROM sync_archivos WHERE usuario_id = ? AND sha256 = ?",
            (self._usuario_id, sha256),
        ).fetchone()
        return fila["estado"] if fila else None

    def sync_registro(self, sha256: str) -> Optional[tuple[str, str]]:
        """(estado, detalle) registrado para el contenido con ese hash, o None."""
        fila = self._conn.execute(
            "SELECT estado, detalle FROM sync_archivos WHERE usuario_id = ? AND sha256 = ?",
            (self._usuario_id, sha256),
        ).fetchone()
        return (fila["estado"], fila["detalle"]) if fila else None

    def sync_ultimo(self) -> Optional[tuple[int, str]]:
        """(ts, detalle) de la última importación correcta."""
        fila = self._conn.execute(
            "SELECT ts, detalle FROM sync_archivos WHERE usuario_id = ? AND estado = 'IMPORTADO' "
            "ORDER BY ts DESC, id DESC LIMIT 1",
            (self._usuario_id,),
        ).fetchone()
        return (int(fila["ts"]), fila["detalle"]) if fila else None

    def sync_contar_importados(self) -> int:
        fila = self._conn.execute(
            "SELECT COUNT(*) AS n FROM sync_archivos WHERE usuario_id = ? AND estado = 'IMPORTADO'",
            (self._usuario_id,),
        ).fetchone()
        return int(fila["n"])

    # ==================================================================
    # CONSERVACIÓN Y PURGA (RF-40, 44, 46)
    # ==================================================================

    def purgar(self, ahora_ts: int, dias_periodico: int, dias_actividades: int) -> ResultadoPurga:
        """Elimina lo vencido sin tocar nada que deba conservarse.

        * Periódico: se borra al pasar ``dias_periodico`` (RF-40).
        * Actividades: se conservan ``dias_actividades`` (> periódico) con sus
          mediciones, ECG y observación, aunque el periódico ya haya vencido (RF-44).
        * Una medición AMBOS que vence como periódica no se borra mientras su
          actividad se conserve: pasa a ser solo de actividad (RF-46).
        """
        corte_per = int(ahora_ts - dias_periodico * 86400)
        corte_act = int(ahora_ts - dias_actividades * 86400)
        u = self._usuario_id

        with self._conn:
            # 1. Actividades vencidas: caen con todo lo suyo
            vencidas = [r["id"] for r in self._conn.execute(
                "SELECT id FROM actividades WHERE usuario_id = ? AND fin_ts < ?", (u, corte_act))]
            med_borradas = 0
            for aid in vencidas:
                med_borradas += self._conn.execute(
                    "DELETE FROM mediciones WHERE usuario_id = ? AND actividad_id = ?", (u, aid)).rowcount
                self._conn.execute(
                    "DELETE FROM observaciones WHERE usuario_id = ? AND tipo = 'ACTIVIDAD' AND actividad_id = ?",
                    (u, aid))
                self._conn.execute("DELETE FROM actividades WHERE usuario_id = ? AND id = ?", (u, aid))

            # 2. Historial periódico vencido
            med_borradas += self._conn.execute(
                "DELETE FROM mediciones WHERE usuario_id = ? AND etiqueta = 'PERIODICO' AND ts < ?",
                (u, corte_per)).rowcount
            self._conn.execute(
                "UPDATE mediciones SET etiqueta = 'ACTIVIDAD' "
                "WHERE usuario_id = ? AND etiqueta = 'AMBOS' AND ts < ?", (u, corte_per))

            # 2b. HRV en reposo vencida (misma caducidad que el historial periódico)
            self._conn.execute("DELETE FROM hrv_reposo WHERE usuario_id = ? AND ts < ?", (u, corte_per))

            # 3. ECG vencido que no cae dentro de una actividad conservada
            bloques = self._conn.execute(
                "DELETE FROM ecg_bloques WHERE usuario_id = ? AND (minuto * 60 + 59) < ? "
                "AND NOT EXISTS (SELECT 1 FROM actividades a WHERE a.usuario_id = ecg_bloques.usuario_id "
                "AND a.inicio_ts <= ecg_bloques.minuto * 60 + 59 AND a.fin_ts >= ecg_bloques.minuto * 60)",
                (u, corte_per)).rowcount

            # 4. Observaciones diarias de periodos vencidos
            obs = self._conn.execute(
                "DELETE FROM observaciones WHERE usuario_id = ? AND tipo = 'DIARIA' AND periodo_fin < ?",
                (u, corte_per)).rowcount

        return ResultadoPurga(med_borradas, len(vencidas), bloques, obs)

    # ==================================================================
    # BORRADO MANUAL (RF-38) Y DE CUENTA (RF-39)
    # ==================================================================

    def borrar_mediciones(self, ids: Iterable[int]) -> int:
        """Borra del todo mediciones propias por id. Devuelve cuántas se borraron."""
        ids = [int(i) for i in ids]
        borradas = 0
        with self._conn:
            for lote in self._lotes(ids):
                borradas += self._conn.execute(
                    f"DELETE FROM mediciones WHERE usuario_id = ? AND id IN ({self._marcas(lote)})",
                    [self._usuario_id, *lote]).rowcount
            self._limpiar_observaciones_diarias()
        return borradas

    def quitar_del_periodico(self, ids: Iterable[int]) -> int:
        """Elimina mediciones del historial PERIÓDICO sin tocar el de actividades (RF-38, 45).

        Las PERIODICO se borran; las AMBOS pasan a ser solo de actividad. Devuelve
        cuántas mediciones cambiaron.
        """
        ids = [int(i) for i in ids]
        cambiadas = 0
        with self._conn:
            for lote in self._lotes(ids):
                marcas, params = self._marcas(lote), [self._usuario_id, *lote]
                cambiadas += self._conn.execute(
                    f"DELETE FROM mediciones WHERE usuario_id = ? AND etiqueta = 'PERIODICO' "
                    f"AND id IN ({marcas})", params).rowcount
                cambiadas += self._conn.execute(
                    f"UPDATE mediciones SET etiqueta = 'ACTIVIDAD' WHERE usuario_id = ? "
                    f"AND etiqueta = 'AMBOS' AND id IN ({marcas})", params).rowcount
            self._limpiar_observaciones_diarias()
        return cambiadas

    def _limpiar_observaciones_diarias(self) -> None:
        """Quita las observaciones diarias de días que ya no tienen ninguna medición periódica."""
        self._conn.execute(
            "DELETE FROM observaciones WHERE usuario_id = ? AND tipo = 'DIARIA' AND NOT EXISTS ("
            "SELECT 1 FROM mediciones m WHERE m.usuario_id = observaciones.usuario_id "
            "AND m.etiqueta IN ('PERIODICO','AMBOS') "
            "AND m.ts >= observaciones.periodo_inicio AND m.ts < observaciones.periodo_fin)",
            (self._usuario_id,))
        # La HRV de una ventana cuyas mediciones se han borrado tampoco debe quedar
        self._conn.execute(
            "DELETE FROM hrv_reposo WHERE usuario_id = ? AND NOT EXISTS ("
            "SELECT 1 FROM mediciones m WHERE m.usuario_id = hrv_reposo.usuario_id "
            "AND m.etiqueta IN ('PERIODICO','AMBOS') AND m.ts >= hrv_reposo.ts AND m.ts < hrv_reposo.ts + 70)",
            (self._usuario_id,))

    @staticmethod
    def _lotes(ids: list[int]):
        for i in range(0, len(ids), _LOTE):
            yield ids[i:i + _LOTE]

    @staticmethod
    def _marcas(lote: list[int]) -> str:
        return ",".join("?" for _ in lote)

    def borrar_actividad(self, actividad_id: int) -> bool:
        """Borra una actividad, sus mediciones exclusivas y su observación.

        Las mediciones AMBOS vuelven a ser solo del historial periódico.
        """
        u = self._usuario_id
        with self._conn:
            self._conn.execute(
                "DELETE FROM mediciones WHERE usuario_id = ? AND actividad_id = ? AND etiqueta = 'ACTIVIDAD'",
                (u, actividad_id))
            self._conn.execute(
                "UPDATE mediciones SET etiqueta = 'PERIODICO', actividad_id = NULL "
                "WHERE usuario_id = ? AND actividad_id = ?", (u, actividad_id))
            self._conn.execute(
                "DELETE FROM observaciones WHERE usuario_id = ? AND tipo = 'ACTIVIDAD' AND actividad_id = ?",
                (u, actividad_id))
            return self._conn.execute(
                "DELETE FROM actividades WHERE usuario_id = ? AND id = ?", (u, actividad_id)).rowcount > 0

    def borrar_todo(self) -> None:
        """Elimina TODOS los datos del usuario (no su cuenta)."""
        u = self._usuario_id
        with self._conn:
            for tabla in TABLAS_DE_USUARIO:
                self._conn.execute(f"DELETE FROM {tabla} WHERE usuario_id = ?", (u,))

    # ==================================================================
    # CIERRE
    # ==================================================================

    def cerrar(self) -> None:
        try:
            self._conn.close()
        except Exception:
            logger.exception("Error cerrando la base de datos del historial")

    # ------------------------------------------------------------------

    @staticmethod
    def _a_medicion(f: sqlite3.Row) -> Medicion:
        return Medicion(
            id=int(f["id"]), uid=f["uid"], ts=int(f["ts"]), bpm=float(f["bpm"]),
            rpm=None if f["rpm"] is None else float(f["rpm"]),
            temp_c=None if f["temp_c"] is None else float(f["temp_c"]),
            nivel_actividad=None if f["nivel_actividad"] is None else int(f["nivel_actividad"]),
            etiqueta=f["etiqueta"],
            actividad_id=None if f["actividad_id"] is None else int(f["actividad_id"]),
        )

    @staticmethod
    def _a_actividad(f: sqlite3.Row) -> Actividad:
        return Actividad(int(f["id"]), f["uid"], int(f["inicio_ts"]), int(f["fin_ts"]), f["tipo"])

    @staticmethod
    def _a_observacion(f: sqlite3.Row) -> ObservacionGuardada:
        return ObservacionGuardada(
            id=int(f["id"]), tipo=f["tipo"], clave=f["clave"],
            actividad_id=None if f["actividad_id"] is None else int(f["actividad_id"]),
            periodo_inicio_ts=int(f["periodo_inicio"]), periodo_fin_ts=int(f["periodo_fin"]),
            texto=f["texto"], generada_ts=int(f["generada_ts"]),
        )
