"""Servicio de autenticación: registro, login con MFA y cierre de sesión.

Flujo (RF-41, RF-01, RF-42, RF-02):
  1. registrar()            -> crea la cuenta con MFA sin activar y devuelve el secreto TOTP.
  2. iniciar_sesion()       -> comprueba correo+contraseña; devuelve un DesafioMfa.
  3. verificar_mfa(codigo)  -> con un código válido abre la sesión. El primer código
                               válido de una cuenta nueva activa su MFA.
  4. cerrar_sesion()        -> destruye la sesión; sin repetir 1-3 no hay acceso.

La sesión vive solo en memoria: cerrar la aplicación también la destruye.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Optional

from domain.validacion_cuentas import normalizar_email, validar_registro
from services import totp
from services.repositorio_cuentas import EmailDuplicado, RepositorioCuentas

logger = logging.getLogger(__name__)

# Mismo mensaje para "correo inexistente" y "contraseña errónea": no revela qué cuentas existen
MENSAJE_CREDENCIALES = "Correo o contraseña incorrectos."


class ErrorAuth(Exception):
    pass


class DatosInvalidos(ErrorAuth):
    def __init__(self, errores: list[str]):
        super().__init__(" ".join(errores))
        self.errores = errores


class CuentaDuplicada(ErrorAuth):
    pass


class CredencialesInvalidas(ErrorAuth):
    pass


class CuentaBloqueada(ErrorAuth):
    def __init__(self, segundos: int):
        super().__init__(f"Cuenta bloqueada temporalmente. Inténtalo de nuevo en {segundos} s.")
        self.segundos = segundos


class CodigoMfaInvalido(ErrorAuth):
    pass


class DesafioCaducado(ErrorAuth):
    pass


class SesionNoIniciada(ErrorAuth):
    pass


@dataclass(frozen=True)
class RegistroCreado:
    usuario_id: int
    secreto: str
    uri: str


@dataclass(frozen=True)
class DesafioMfa:
    usuario_id: int
    requiere_activacion: bool           # True: hay que dar de alta el secreto en la app autenticadora
    secreto: Optional[str] = None       # solo si requiere_activacion
    uri: Optional[str] = None


@dataclass(frozen=True)
class Sesion:
    usuario_id: int
    email: str
    nombre: str


class ServicioAuth:

    def __init__(
        self,
        repo: RepositorioCuentas,
        reloj: Callable[[], float] = time.time,
        max_intentos: int = 5,
        bloqueo_s: int = 300,
        validez_desafio_s: int = 300,
    ):
        self._repo = repo
        self._reloj = reloj
        self._max_intentos = max_intentos
        self._bloqueo_s = bloqueo_s
        self._validez_desafio_s = validez_desafio_s

        self._sesion: Optional[Sesion] = None
        self._desafio: Optional[DesafioMfa] = None
        self._desafio_ts: float = 0.0

    # --------------------------------------------------
    # REGISTRO (RF-41)
    # --------------------------------------------------

    def registrar(self, nombre: str, email: str, password: str, password_repetida: str) -> RegistroCreado:
        errores = validar_registro(nombre, email, password, password_repetida)
        if errores:
            raise DatosInvalidos(errores)

        email_n = normalizar_email(email)
        if self._repo.existe_email(email_n):
            raise CuentaDuplicada("Ya existe una cuenta con ese correo.")

        secreto = totp.generar_secreto()
        try:
            usuario_id = self._repo.crear(email_n, nombre.strip(), password, secreto, self._reloj())
        except EmailDuplicado as exc:  # carrera entre la comprobación y el INSERT
            raise CuentaDuplicada("Ya existe una cuenta con ese correo.") from exc

        logger.info("Cuenta creada (id=%s)", usuario_id)
        return RegistroCreado(usuario_id, secreto, totp.uri_aprovisionamiento(secreto, email_n))

    # --------------------------------------------------
    # LOGIN: PASO 1, CREDENCIALES (RF-01)
    # --------------------------------------------------

    def iniciar_sesion(self, email: str, password: str) -> DesafioMfa:
        self._sesion = None
        self._desafio = None

        cuenta = self._repo.obtener_por_email(normalizar_email(email))
        if cuenta is None:
            # Se gasta el mismo tiempo de hash para no distinguir cuentas por latencia
            self._repo.gastar_tiempo_de_hash(password)
            raise CredencialesInvalidas(MENSAJE_CREDENCIALES)

        self._comprobar_bloqueo(cuenta.bloqueado_hasta)

        if not self._repo.password_correcta(cuenta.id, password):
            self._registrar_fallo(cuenta.id)
            raise CredencialesInvalidas(MENSAJE_CREDENCIALES)

        if cuenta.totp_activo:
            desafio = DesafioMfa(cuenta.id, requiere_activacion=False)
        else:
            # Alta de MFA sin terminar: se emite un secreto nuevo para completarla
            secreto = totp.generar_secreto()
            self._repo.reemplazar_secreto_inactivo(cuenta.id, secreto)
            desafio = DesafioMfa(
                cuenta.id, True, secreto, totp.uri_aprovisionamiento(secreto, cuenta.email)
            )

        self._desafio = desafio
        self._desafio_ts = self._reloj()
        return desafio

    # --------------------------------------------------
    # LOGIN: PASO 2, MFA (RF-42)
    # --------------------------------------------------

    def verificar_mfa(self, codigo: str) -> Sesion:
        if self._desafio is None:
            raise DesafioCaducado("Primero introduce tu correo y contraseña.")
        if self._reloj() - self._desafio_ts > self._validez_desafio_s:
            self._desafio = None
            raise DesafioCaducado("El tiempo para verificar ha caducado. Vuelve a iniciar sesión.")

        cuenta = self._repo.obtener_por_id(self._desafio.usuario_id)
        if cuenta is None:
            self._desafio = None
            raise DesafioCaducado("La cuenta ya no existe.")

        self._comprobar_bloqueo(cuenta.bloqueado_hasta)

        paso = totp.verificar(
            cuenta.totp_secreto, codigo, self._reloj(),
            ultimo_paso_usado=cuenta.totp_ultimo_paso,
        )
        if paso is None:
            self._registrar_fallo(cuenta.id)
            raise CodigoMfaInvalido("Código de verificación incorrecto.")

        self._repo.guardar_ultimo_paso(cuenta.id, paso, activar=not cuenta.totp_activo)
        self._repo.limpiar_fallos(cuenta.id)

        self._desafio = None
        self._sesion = Sesion(cuenta.id, cuenta.email, cuenta.nombre)
        logger.info("Sesión iniciada (id=%s)", cuenta.id)
        return self._sesion

    # --------------------------------------------------
    # SESIÓN (RF-02)
    # --------------------------------------------------

    @property
    def sesion_actual(self) -> Optional[Sesion]:
        return self._sesion

    def requerir_sesion(self) -> Sesion:
        """Las operaciones protegidas llaman aquí: sin sesión no hay acceso."""
        if self._sesion is None:
            raise SesionNoIniciada("Debes iniciar sesión.")
        return self._sesion

    def cerrar_sesion(self) -> None:
        if self._sesion is not None:
            logger.info("Sesión cerrada (id=%s)", self._sesion.usuario_id)
        self._sesion = None
        self._desafio = None

    # --------------------------------------------------
    # ELIMINACIÓN DE CUENTA (RF-39)
    # --------------------------------------------------

    def eliminar_cuenta(self, password: str) -> None:
        """Elimina la cuenta de la sesión actual y todos sus datos, y cierra la sesión.

        Exige la contraseña otra vez: una sesión abierta y desatendida no basta para
        destruir una cuenta. Los fallos cuentan para el bloqueo por intentos.
        """
        sesion = self.requerir_sesion()
        cuenta = self._repo.obtener_por_id(sesion.usuario_id)
        if cuenta is None:
            self.cerrar_sesion()
            raise SesionNoIniciada("La cuenta ya no existe.")

        self._comprobar_bloqueo(cuenta.bloqueado_hasta)
        if not self._repo.password_correcta(cuenta.id, password):
            self._registrar_fallo(cuenta.id)
            raise CredencialesInvalidas("Contraseña incorrecta.")

        self._repo.eliminar(cuenta.id)
        logger.info("Cuenta eliminada (id=%s)", cuenta.id)
        self.cerrar_sesion()

    # --------------------------------------------------
    # BLOQUEO POR INTENTOS
    # --------------------------------------------------

    def _comprobar_bloqueo(self, bloqueado_hasta: float) -> None:
        restante = bloqueado_hasta - self._reloj()
        if restante > 0:
            raise CuentaBloqueada(int(restante) + 1)

    def _registrar_fallo(self, usuario_id: int) -> None:
        self._repo.registrar_fallo(usuario_id, self._max_intentos, self._bloqueo_s, self._reloj())
