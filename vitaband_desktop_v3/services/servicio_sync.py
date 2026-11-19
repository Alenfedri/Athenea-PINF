"""Sincronización móvil -> escritorio por archivos de intercambio (RF-18, 20, 21, 36).

El móvil deja paquetes JSON (ver docs/contrato_sincronizacion.md) en la carpeta
de intercambio y este servicio los importa al historial del usuario activo.

* Sin duplicados (RF-20): cada archivo se identifica por el SHA-256 de su
  contenido (renombrarlo o copiarlo no lo reimporta) y, además, cada medición y
  actividad lleva un ``uid`` único que el repositorio respeta.
* Estados por archivo (RF-21): PENDIENTE, SINCRONIZADO o ERROR.
* Un archivo con errores se rechaza entero y se reintenta en cada sincronización
  (p. ej. porque la actividad a la que apunta llega en otro archivo posterior).
* Los paquetes de otro usuario se ignoran: no cuentan ni se importan.

No usa Qt ni hilos: la llamada es síncrona y la invoca el ViewModel.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Callable, Optional

from domain.paquete_sync import PaqueteInvalido, parsear_paquete, propietario_de
from domain.validacion_cuentas import normalizar_email
from services.repositorio_historial import RepositorioHistorial, ResultadoImportacion

logger = logging.getLogger(__name__)

PENDIENTE = "PENDIENTE"
SINCRONIZADO = "SINCRONIZADO"
ERROR = "ERROR"

MAX_BYTES_ARCHIVO = 64 * 1024 * 1024


@dataclass(frozen=True)
class ArchivoSync:
    nombre: str
    estado: str                    # PENDIENTE | SINCRONIZADO | ERROR
    detalle: str = ""


@dataclass(frozen=True)
class EstadoSync:
    carpeta_disponible: bool
    archivos: tuple[ArchivoSync, ...] = ()
    ultima_sync_ts: Optional[int] = None

    def _contar(self, estado: str) -> int:
        return sum(1 for a in self.archivos if a.estado == estado)

    @property
    def pendientes(self) -> int:
        return self._contar(PENDIENTE)

    @property
    def sincronizados(self) -> int:
        return self._contar(SINCRONIZADO)

    @property
    def errores(self) -> int:
        return self._contar(ERROR)


@dataclass(frozen=True)
class ResultadoSync:
    carpeta_disponible: bool
    importados: int = 0             # archivos importados en esta pasada
    rechazados: int = 0             # archivos con error
    sin_cambios: int = 0            # archivos ya sincronizados
    mediciones_nuevas: int = 0
    mediciones_duplicadas: int = 0
    actividades_nuevas: int = 0
    segundos_ecg_nuevos: int = 0
    errores: tuple[str, ...] = ()   # "archivo: motivo"

    @property
    def hubo_datos_nuevos(self) -> bool:
        return bool(self.mediciones_nuevas or self.actividades_nuevas or self.segundos_ecg_nuevos)


@dataclass(frozen=True)
class _Archivo:
    nombre: str
    ruta: str
    sha: Optional[str]              # None si no se pudo leer
    error: str = ""


def _resumen_importacion(r: ResultadoImportacion) -> str:
    return (f"{r.mediciones_nuevas} mediciones y {r.actividades_nuevas} actividades nuevas, "
            f"{r.segundos_ecg_nuevos} s de ECG; {r.mediciones_duplicadas} mediciones ya existentes")


def _resumen_errores(errores: list[str]) -> str:
    texto = "; ".join(errores[:3])
    return texto + (" (…)" if len(errores) > 3 else "")


class ServicioSync:

    def __init__(
        self,
        repositorio: RepositorioHistorial,
        carpeta: str,
        email_usuario: str,
        reloj: Callable[[], float] = time.time,
    ):
        self._repo = repositorio
        self._carpeta = carpeta
        self._email = normalizar_email(email_usuario)
        self._reloj = reloj
        # ruta -> ((tamaño, mtime_ns), sha256, propietario): evita releer archivos sin cambios
        self._cache: dict[str, tuple[tuple[int, int], str, Optional[str]]] = {}

    @property
    def carpeta(self) -> str:
        return self._carpeta

    # ------------------------------------------------------------------

    def _escanear(self) -> list[_Archivo]:
        """Archivos .json de la carpeta que pertenecen al usuario (o sin propietario legible)."""
        archivos: list[_Archivo] = []
        for nombre in sorted(os.listdir(self._carpeta)):
            if not nombre.lower().endswith(".json"):
                continue
            ruta = os.path.join(self._carpeta, nombre)
            try:
                if not os.path.isfile(ruta):
                    continue
                st = os.stat(ruta)
                if st.st_size > MAX_BYTES_ARCHIVO:
                    archivos.append(_Archivo(nombre, ruta, None, "Archivo demasiado grande"))
                    continue
                clave = (st.st_size, st.st_mtime_ns)
                cache = self._cache.get(ruta)
                if cache and cache[0] == clave:
                    sha, propietario = cache[1], cache[2]
                else:
                    with open(ruta, "rb") as f:
                        datos = f.read()
                    sha = hashlib.sha256(datos).hexdigest()
                    propietario = propietario_de(datos)
                    self._cache[ruta] = (clave, sha, propietario)
            except OSError as e:
                archivos.append(_Archivo(nombre, ruta, None, f"No se pudo leer el archivo ({e.strerror or e})"))
                continue

            if propietario is not None and propietario != self._email:
                continue        # paquete de otro usuario de este equipo
            archivos.append(_Archivo(nombre, ruta, sha))
        return archivos

    def _estado_de(self, a: _Archivo) -> ArchivoSync:
        if a.sha is None:
            return ArchivoSync(a.nombre, ERROR, a.error)
        registro = self._repo.sync_registro(a.sha)
        if registro is None:
            return ArchivoSync(a.nombre, PENDIENTE)
        estado, detalle = registro
        return ArchivoSync(a.nombre, SINCRONIZADO if estado == "IMPORTADO" else ERROR, detalle)

    def estado(self) -> EstadoSync:
        """Estado de la carpeta de intercambio sin importar nada (RF-21)."""
        if not os.path.isdir(self._carpeta):
            return EstadoSync(False)
        ultimo = self._repo.sync_ultimo()
        return EstadoSync(
            True,
            tuple(self._estado_de(a) for a in self._escanear()),
            ultimo[0] if ultimo else None,
        )

    # ------------------------------------------------------------------

    def sincronizar(self) -> ResultadoSync:
        """Importa los archivos pendientes o con error. Es idempotente."""
        if not os.path.isdir(self._carpeta):
            return ResultadoSync(False)

        archivos = self._escanear()
        ahora = int(self._reloj())

        restantes = [a for a in archivos
                     if a.sha is None or self._repo.sync_estado(a.sha) != "IMPORTADO"]
        sin_cambios = len(archivos) - len(restantes)

        importados = 0
        total = [0, 0, 0, 0]       # med nuevas, med duplicadas, act nuevas, seg ECG
        fallos: list[tuple[_Archivo, str]] = []

        # Se repite mientras haya progreso: un archivo puede depender de otro posterior.
        while restantes:
            fallos = []
            ronda = 0
            for a in restantes:
                r = self._intentar(a, ahora)
                if isinstance(r, str):
                    fallos.append((a, r))
                    continue
                ronda += 1
                importados += 1
                total[0] += r.mediciones_nuevas
                total[1] += r.mediciones_duplicadas
                total[2] += r.actividades_nuevas
                total[3] += r.segundos_ecg_nuevos
            if ronda == 0 or not fallos:
                break
            restantes = [a for a, _ in fallos]

        errores = []
        for a, motivo in fallos:
            errores.append(f"{a.nombre}: {motivo}")
            if a.sha is not None:
                self._repo.sync_registrar(a.nombre, a.sha, "ERROR", motivo, ahora)

        return ResultadoSync(
            True, importados, len(fallos), sin_cambios,
            total[0], total[1], total[2], total[3], tuple(errores),
        )

    def _intentar(self, a: _Archivo, ahora: int) -> "ResultadoImportacion | str":
        """Importa un archivo. Devuelve el resultado o, si falla, el motivo (texto)."""
        if a.sha is None:
            return a.error or "No se pudo leer el archivo"
        try:
            with open(a.ruta, "rb") as f:
                datos = f.read()
        except OSError as e:
            return f"No se pudo leer el archivo ({e.strerror or e})"

        sha = hashlib.sha256(datos).hexdigest()
        try:
            paquete = parsear_paquete(datos, ahora)
            if paquete.usuario != self._email:
                return "El paquete pertenece a otro usuario"
            resultado = self._repo.importar_paquete(paquete)
        except PaqueteInvalido as e:
            return _resumen_errores(e.errores)
        except sqlite3.Error as e:
            logger.exception("Error de base de datos importando %s", a.nombre)
            return f"Error de base de datos: {e}"

        self._repo.sync_registrar(a.nombre, sha, "IMPORTADO", _resumen_importacion(resultado), ahora)
        return resultado
