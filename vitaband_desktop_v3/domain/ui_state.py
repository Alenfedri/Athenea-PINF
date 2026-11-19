from dataclasses import dataclass
from enum import Enum

from domain.calidad_contacto import CalidadContacto


class ConexionEstado(Enum):
    DESCONECTADO = "DESCONECTADO"
    CONECTANDO = "CONECTANDO"
    CALIBRANDO = "CALIBRANDO"          # Ventana inicial de 6 s de respiración
    CONECTADO = "CONECTADO"
    ERROR_COMUNICACION = "ERROR_COMUNICACION"


@dataclass(frozen=True)
class VitaBandUiState:
    conexionEstado: ConexionEstado
    ecgMuestras: tuple[float, ...]
    modoEcgCrudo: bool
    bpmTexto: str
    rpmTexto: str
    tempTexto: str
    nivelActividad: str
    avisoExperimental: str
    # Sincronización con el móvil (RF-21)
    syncPendientes: int = 0
    syncSincronizados: int = 0
    syncErrores: int = 0
    syncTexto: str = "Sin sincronizar"
    # Calidad de contacto de la banda pectoral, según el ECG reciente
    calidadContacto: CalidadContacto = CalidadContacto.SIN_SENAL

    @staticmethod
    def inicial() -> "VitaBandUiState":
        return VitaBandUiState(
            conexionEstado=ConexionEstado.DESCONECTADO,
            ecgMuestras=(),
            modoEcgCrudo=False,
            bpmTexto="--",
            rpmTexto="--",
            tempTexto="-- °C",
            nivelActividad="Sin datos",
            avisoExperimental="Sin avisos",
        )