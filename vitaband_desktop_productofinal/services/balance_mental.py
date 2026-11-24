"""Balance de carga mental de la jornada: segundos diarios en foco calmado, tensión y estrés (SQLite ligero)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS balance_carga_mental (
    usuario  INTEGER NOT NULL,
    fecha    TEXT    NOT NULL,
    calma_s  REAL    NOT NULL DEFAULT 0,
    tension_s REAL   NOT NULL DEFAULT 0,
    estres_s REAL    NOT NULL DEFAULT 0,
    PRIMARY KEY (usuario, fecha)
);
"""
_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS borrar_balance_mental_usuario AFTER DELETE ON usuarios
BEGIN DELETE FROM balance_carga_mental WHERE usuario = OLD.id; END;
"""


@dataclass(frozen=True)
class BalanceDia:
    fecha: str
    calma_s: float = 0.0
    tension_s: float = 0.0
    estres_s: float = 0.0

    @property
    def total_s(self) -> float:
        return self.calma_s + self.tension_s + self.estres_s

    def porcentajes(self) -> tuple[float, float, float]:
        """(% foco calmado, % tensión, % estrés); (0, 0, 0) si aún no hay datos."""
        t = self.total_s
        if t <= 0:
            return 0.0, 0.0, 0.0
        return tuple(100.0 * x / t for x in (self.calma_s, self.tension_s, self.estres_s))

    def texto(self) -> str:
        if self.total_s <= 0:
            return "Aún sin datos de hoy"
        c, t, e = self.porcentajes()
        return f"Foco calmado {c:.0f} % · Tensión {t:.0f} % · Estrés {e:.0f} %"


class BalanceCargaMental:
    def __init__(self, repo):
        self._c, self._u = repo.conexion, repo.usuario_id
        with self._c:
            self._c.executescript(_ESQUEMA)
            if self._c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='usuarios'").fetchone():
                self._c.executescript(_TRIGGER)

    def sumar(self, calma_s: float, tension_s: float, estres_s: float, fecha: str | None = None) -> None:
        if calma_s <= 0 and tension_s <= 0 and estres_s <= 0:
            return
        fecha = fecha or date.today().isoformat()
        with self._c:
            self._c.execute(
                "INSERT INTO balance_carga_mental (usuario, fecha, calma_s, tension_s, estres_s) VALUES (?,?,?,?,?) "
                "ON CONFLICT(usuario, fecha) DO UPDATE SET calma_s = calma_s + excluded.calma_s, "
                "tension_s = tension_s + excluded.tension_s, estres_s = estres_s + excluded.estres_s",
                (self._u, fecha, max(0.0, calma_s), max(0.0, tension_s), max(0.0, estres_s)))

    def dia(self, fecha: str | None = None) -> BalanceDia:
        fecha = fecha or date.today().isoformat()
        f = self._c.execute("SELECT calma_s, tension_s, estres_s FROM balance_carga_mental "
                            "WHERE usuario = ? AND fecha = ?", (self._u, fecha)).fetchone()
        return BalanceDia(fecha, *f) if f else BalanceDia(fecha)
