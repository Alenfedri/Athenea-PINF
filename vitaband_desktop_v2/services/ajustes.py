"""Ajustes de la aplicación leídos de ``settings.json``, validados y con valores por defecto.

Un ``settings.json`` antiguo (sin las secciones nuevas) sigue funcionando: lo que
falta toma el valor por defecto. Un valor inválido se rechaza al arrancar con un
mensaje claro, en vez de fallar más tarde.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

# Valores por defecto (los usa también el ViewModel)
DIAS_PERIODICO = 30                     # RF-40
DIAS_ACTIVIDADES = 365                  # RF-44 (no menor que el periódico)
INTERVALO_REGISTRO_S = 10
CARPETA_INTERCAMBIO = "intercambio"
INTERVALO_SYNC_S = 60
INTERVALO_OBSERVACIONES_MIN = 60


class AjustesInvalidos(ValueError):
    pass


def _seccion(config: Mapping[str, Any], nombre: str) -> Mapping[str, Any]:
    valor = config.get(nombre, {})
    if not isinstance(valor, Mapping):
        raise AjustesInvalidos(f"settings.json: «{nombre}» debe ser un objeto.")
    return valor


def _numero(sec: Mapping[str, Any], seccion: str, clave: str, defecto: float, minimo: float,
            entero: bool = False) -> float:
    valor = sec.get(clave, defecto)
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or valor != valor:
        raise AjustesInvalidos(f"settings.json: {seccion}.{clave} debe ser un número.")
    if entero and valor != int(valor):
        raise AjustesInvalidos(f"settings.json: {seccion}.{clave} debe ser un número entero.")
    if valor < minimo:
        raise AjustesInvalidos(f"settings.json: {seccion}.{clave} debe ser como mínimo {minimo:g}.")
    return int(valor) if entero else float(valor)


@dataclass(frozen=True)
class Ajustes:
    registro_intervalo_s: float = INTERVALO_REGISTRO_S         # RF-12
    periodico_dias: int = DIAS_PERIODICO                       # RF-40
    actividades_dias: int = DIAS_ACTIVIDADES                   # RF-44
    carpeta_intercambio: str = CARPETA_INTERCAMBIO             # RF-18
    sync_intervalo_s: float = INTERVALO_SYNC_S                 # 0 = solo manual y al arrancar
    observaciones_intervalo_min: float = INTERVALO_OBSERVACIONES_MIN   # 0 = solo al arrancar/sincronizar

    @property
    def registro_intervalo_ms(self) -> int:
        return int(self.registro_intervalo_s * 1000)

    @property
    def sync_intervalo_ms(self) -> int:
        return int(self.sync_intervalo_s * 1000)

    @property
    def observaciones_intervalo_ms(self) -> int:
        return int(self.observaciones_intervalo_min * 60_000)

    @staticmethod
    def desde_config(config: Mapping[str, Any]) -> "Ajustes":
        reg = _seccion(config, "registro")
        con = _seccion(config, "conservacion")
        inter = _seccion(config, "intercambio")
        obs = _seccion(config, "observaciones")

        periodico = int(_numero(con, "conservacion", "periodico_dias", DIAS_PERIODICO, 1, entero=True))
        actividades = int(_numero(con, "conservacion", "actividades_dias", DIAS_ACTIVIDADES, 1, entero=True))
        if actividades < periodico:
            raise AjustesInvalidos(
                "settings.json: conservacion.actividades_dias no puede ser menor que periodico_dias.")

        carpeta = inter.get("carpeta", CARPETA_INTERCAMBIO)
        if not isinstance(carpeta, str) or not carpeta.strip():
            raise AjustesInvalidos("settings.json: intercambio.carpeta debe ser una ruta (texto no vacío).")

        return Ajustes(
            registro_intervalo_s=_numero(reg, "registro", "intervalo_s", INTERVALO_REGISTRO_S, 1),
            periodico_dias=periodico,
            actividades_dias=actividades,
            carpeta_intercambio=carpeta.strip(),
            sync_intervalo_s=_numero(inter, "intercambio", "intervalo_comprobacion_s", INTERVALO_SYNC_S, 0),
            observaciones_intervalo_min=_numero(obs, "observaciones", "intervalo_min", INTERVALO_OBSERVACIONES_MIN, 0),
        )
