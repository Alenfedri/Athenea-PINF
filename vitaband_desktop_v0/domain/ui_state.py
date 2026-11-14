from dataclasses import dataclass
from enum import Enum


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
    pendientesSync: int
    sincronizando: bool

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
            pendientesSync=0,
            sincronizando=False,
        )