"""Lógica de las funciones en vivo: pitido de latido, fantasma de sesión, piloto de zona y acoplamiento
pulso-respiración. Solo stdlib + numpy (sin Qt) para poder probarla sin pantalla ni audio."""

from __future__ import annotations

import io
import math
import struct
import wave
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

import numpy as np

from domain.zonas_actividad import FC_MAX_REFERENCIA, LIMITES_ZONAS
from services.vo2max import fc_max_tanaka

# ------------------------------------------------------------------ Pitido de latido

FRECUENCIA_HZ = 880.0
DURACION_MS = 55
TASA_HZ = 44100
ATAQUE_MS, RELAJACION_MS = 8, 25        # envolvente suave: sin chasquidos al empezar ni al acabar


def pitido_pcm(volumen: float = 1.0, frecuencia: float = FRECUENCIA_HZ, duracion_ms: int = DURACION_MS,
               tasa: int = TASA_HZ) -> bytes:
    """Onda senoidal con envolvente suave, PCM 16 bit little-endian mono. ``volumen`` 0–1."""
    volumen = max(0.0, min(1.0, float(volumen)))
    n = int(tasa * duracion_ms / 1000)
    ataque, relajacion = int(tasa * ATAQUE_MS / 1000), int(tasa * RELAJACION_MS / 1000)
    muestras = []
    for i in range(n):
        env = 1.0
        if i < ataque:
            env = math.sin(0.5 * math.pi * i / ataque) ** 2
        elif i >= n - relajacion:
            env = math.sin(0.5 * math.pi * (n - 1 - i) / relajacion) ** 2
        muestras.append(int(32767 * 0.8 * volumen * env * math.sin(2 * math.pi * frecuencia * i / tasa)))
    return struct.pack(f"<{n}h", *muestras)


def pitido_wav(volumen: float = 1.0) -> bytes:
    """El mismo pitido como archivo WAV en memoria."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TASA_HZ)
        w.writeframes(pitido_pcm(volumen))
    return buf.getvalue()


# ------------------------------------------------------------------ Detector de latidos en directo

class DetectorLatido:
    """Detecta picos R muestra a muestra (causal, con una muestra de retardo). Asume R positiva, como la
    señal filtrada de la banda; devuelve True en la muestra en que confirma un latido."""

    REFRACTARIO_S = 0.30
    CALENTAMIENTO_S = 2.0

    def __init__(self, fs: int = 100):
        self.fs = fs
        self.reiniciar()

    def reiniciar(self) -> None:
        self._base: Optional[float] = None
        self._y1 = self._y2 = 0.0
        self._pico = 0.0
        self._ruido = 0.0
        self._n = 0
        self._ultimo = -10 ** 9
        self.latidos = 0

    def agregar(self, x: float) -> bool:
        if not math.isfinite(x):
            self.reiniciar()
            return False
        self._n += 1
        if self._base is None:
            self._base = x
        self._base += (x - self._base) / (0.5 * self.fs)         # línea de base: media móvil exponencial
        y = x - self._base
        latido = False
        if self._n <= self.CALENTAMIENTO_S * self.fs:
            self._pico = max(self._pico, y)
        else:
            umbral = max(0.5 * self._pico, 4.0 * self._ruido)
            if (self._y1 > umbral and self._y1 >= self._y2 and self._y1 > y
                    and self._n - 1 - self._ultimo >= self.REFRACTARIO_S * self.fs):
                latido = True
                self._ultimo = self._n - 1
                self._pico = 0.8 * self._pico + 0.2 * self._y1
                self.latidos += 1
        self._pico *= 1 - 1 / (20 * self.fs)                       # olvido lento de la amplitud
        self._ruido += (abs(y) - self._ruido) / (2 * self.fs)
        self._y2, self._y1 = self._y1, y
        return latido


# ------------------------------------------------------------------ Fantasma de sesión

@dataclass(frozen=True)
class ComparacionFantasma:
    delta: float                 # BPM actual − BPM del fantasma en el mismo segundo
    bpm_fantasma: float
    texto: str
    nivel: str                   # "mejor" | "igual" | "algo" | "mucho"
    bpm_actual: float = 0.0

    @property
    def ratio(self) -> float:
        """Eficiencia cardíaca: pulso del fantasma / pulso actual (> 1 = vas con menos pulso)."""
        return self.bpm_fantasma / self.bpm_actual if self.bpm_actual > 0 else 1.0

    @property
    def color(self) -> str:
        return "#2ECC40" if self.delta <= 0 else "#FFC20E" if self.nivel == "algo" else "#E8231A"


class SesionFantasma:
    VENTANA_S = 5.0

    def __init__(self, fecha_ts: int, puntos: Sequence[tuple[float, float]]):
        self.fecha_ts = int(fecha_ts)
        self.puntos = sorted((float(t), float(b)) for t, b in puntos if b and b > 0 and math.isfinite(b))

    @property
    def duracion_s(self) -> float:
        return self.puntos[-1][0] if self.puntos else 0.0

    @property
    def fecha(self) -> str:
        return datetime.fromtimestamp(self.fecha_ts).strftime("%d/%m/%Y")

    def bpm_en(self, t: float) -> Optional[float]:
        """Pulso de la sesión de referencia en el segundo ``t`` (media de ±5 s); None fuera de su duración."""
        if not self.puntos or t < self.puntos[0][0] - self.VENTANA_S or t > self.puntos[-1][0] + 1:
            return None
        cerca = [b for ti, b in self.puntos if abs(ti - t) <= self.VENTANA_S]
        if cerca:
            return float(sum(cerca) / len(cerca))
        ts, bs = [p[0] for p in self.puntos], [p[1] for p in self.puntos]
        return float(np.interp(t, ts, bs))

    def comparar(self, t: float, bpm_actual: Optional[float]) -> Optional[ComparacionFantasma]:
        if bpm_actual is None or bpm_actual <= 0 or t < 0:
            return None
        ref = self.bpm_en(t)
        if ref is None:
            return None
        delta = bpm_actual - ref
        n = abs(round(delta))
        if delta <= -1:
            texto, nivel = f"Vas {n} bpm más bajo que en tu sesión del {self.fecha}", "mejor"
        elif delta < 1:
            texto, nivel = f"Vas al mismo pulso que en tu sesión del {self.fecha}", "igual"
        else:
            texto, nivel = f"Vas {n} bpm más alto que en tu sesión del {self.fecha}", "algo" if delta <= 5 else "mucho"
        return ComparacionFantasma(float(delta), ref, texto, nivel, float(bpm_actual))


def puntos_de_mediciones(inicio_ts: int, mediciones) -> list[tuple[float, float]]:
    return [(float(m.ts - inicio_ts), float(m.bpm)) for m in mediciones if m.bpm and m.bpm > 0]


# ------------------------------------------------------------------ Piloto automático de zona

OPCIONES_ZONA = ("Desactivado", "Z1", "Z2", "Z3", "Z4", "Z5")
LIMITE_INFERIOR_Z1 = 0.50
TEXTOS_PILOTO = {"sube": "Sube el ritmo", "clavado": "Ritmo clavado", "frena": "Frena un poco"}


def fc_max_usuario(edad: Optional[int]) -> float:
    """FCmáx personalizada: Tanaka con la edad del perfil; sin edad, la de referencia."""
    return fc_max_tanaka(edad) if edad else FC_MAX_REFERENCIA


def rango_zona(zona: int, fc_max: float) -> tuple[float, float]:
    """(mínimo, máximo) en BPM de la zona 0..4 (Z1..Z5); el máximo de Z5 es la FCmáx."""
    limites = (LIMITE_INFERIOR_Z1,) + tuple(LIMITES_ZONAS) + (1.0,)
    return limites[zona] * fc_max, limites[zona + 1] * fc_max


def estado_piloto(bpm: Optional[float], zona: Optional[int], fc_max: float) -> Optional[str]:
    """'sube' (por debajo), 'clavado' (dentro) o 'frena' (por encima); None sin pulso o con el piloto apagado."""
    if bpm is None or bpm <= 0 or zona is None or not 0 <= zona <= 4:
        return None
    lo, hi = rango_zona(zona, fc_max)
    if bpm < lo:
        return "sube"
    if bpm >= hi if zona < 4 else bpm > hi:
        return "frena"
    return "clavado"


# ------------------------------------------------------------------ Acoplamiento pulso-respiración

@dataclass(frozen=True)
class ResultadoAcoplamiento:
    indice: float                # 0–100: % de la variación del pulso explicada por el ritmo respiratorio
    amplitud_bpm: float          # oscilación pico a pico ajustada
    texto: str


class AcoplamientoPulsoResp:
    """Compara la oscilación del pulso con una onda cuya frecuencia sigue las RPM en vivo.

    Con solo la frecuencia respiratoria la fase absoluta es desconocida, así que se ajusta por mínimos
    cuadrados (seno + coseno): el índice es el R² del ajuste (arritmia sinusoidal respiratoria)."""

    VENTANA_S = 60.0
    MIN_S = 20.0
    MIN_MUESTRAS = 15
    MIN_AMPLITUD_BPM = 1.0

    def __init__(self):
        self.reiniciar()

    def reiniciar(self) -> None:
        self._datos: deque[tuple[float, float, float]] = deque()      # (t, bpm, fase)
        self._fase = 0.0
        self._t_ult: Optional[float] = None

    def agregar(self, t: float, bpm: Optional[float], rpm: Optional[float]) -> None:
        if not bpm or bpm <= 0 or not rpm or rpm <= 0:
            self.reiniciar()
            return
        if self._t_ult is not None:
            dt = t - self._t_ult
            if dt <= 0:
                return
            if dt > 5:
                self.reiniciar()
            else:
                self._fase += 2 * math.pi * rpm / 60.0 * dt
        self._t_ult = t
        self._datos.append((t, float(bpm), self._fase))
        while self._datos and self._datos[0][0] < t - self.VENTANA_S:
            self._datos.popleft()

    def _ajuste(self):
        if len(self._datos) < self.MIN_MUESTRAS or self._datos[-1][0] - self._datos[0][0] < self.MIN_S:
            return None
        t, b, f = (np.array(c) for c in zip(*self._datos))
        y = b - b.mean()
        X = np.column_stack([np.sin(f), np.cos(f), np.ones_like(f)])
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid = y - X @ coef
        total = float(np.sum(y * y))
        r2 = 0.0 if total < 1e-9 else max(0.0, 1.0 - float(np.sum(resid * resid)) / total)
        a, c = float(coef[0]), float(coef[1])
        return t, y, f, math.hypot(a, c), math.atan2(c, a), r2

    def resultado(self) -> Optional[ResultadoAcoplamiento]:
        aj = self._ajuste()
        if aj is None:
            return None
        _, _, _, amp, _, r2 = aj
        pico_a_pico = 2 * amp
        indice = 100.0 * r2 if pico_a_pico >= self.MIN_AMPLITUD_BPM else 0.0
        if indice >= 50:
            texto = "Arritmia sinusoidal clara: el pulso oscila al ritmo de tu respiración"
        elif indice >= 25:
            texto = "Acoplamiento parcial entre pulso y respiración"
        else:
            texto = "Sin acoplamiento claro (respira lento y regular para verlo)"
        return ResultadoAcoplamiento(indice, pico_a_pico, texto)

    def ondas(self) -> tuple[list[float], list[float], list[float]]:
        """(t relativo al último dato, onda respiratoria escalada, variación del pulso en BPM)."""
        aj = self._ajuste()
        if aj is None:
            return [], [], []
        t, y, f, _, fase0, _ = aj
        escala = max(1.0, float(np.max(np.abs(y))))
        return list(t - t[-1]), list(escala * np.sin(f + fase0)), list(y)


# ------------------------------------------------------------------ Clases de fachada

try:                                          # el audio es opcional: sin QtMultimedia o sin altavoz no hay error
    from PySide6.QtCore import QBuffer, QByteArray, QIODeviceBase
    from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices
    HAY_QT_AUDIO = True
except Exception:                             # pragma: no cover - depende del entorno
    HAY_QT_AUDIO = False


class GeneradorPitidoCardiaco:
    """Pitido de latido en memoria (PCM) reproducido con QAudioSink + QBuffer; silencioso y seguro sin audio."""

    def __init__(self, volumen: float = 0.7, silenciado: bool = False):
        self.pcm = pitido_pcm(1.0)
        self.silenciado = silenciado
        self.disparos = 0                     # pitidos pedidos (cuenten o no con altavoz)
        self.disponible = False
        self._sink = None
        self._buffer = None
        self._volumen = max(0.0, min(1.0, float(volumen)))
        self._iniciar_audio()

    @property
    def volumen(self) -> float:
        return self._volumen

    @volumen.setter
    def volumen(self, v: float) -> None:
        self._volumen = max(0.0, min(1.0, float(v)))
        if self._sink is not None:
            try:
                self._sink.setVolume(self._volumen)
            except Exception:
                self.disponible = False

    def _iniciar_audio(self) -> None:
        if not HAY_QT_AUDIO:
            return
        try:
            salida = QMediaDevices.defaultAudioOutput()
            if salida.isNull():
                return
            formato = QAudioFormat()
            formato.setSampleRate(TASA_HZ)
            formato.setChannelCount(1)
            formato.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            if not salida.isFormatSupported(formato):
                return
            self._sink = QAudioSink(salida, formato)
            self._sink.setVolume(self._volumen)
            self._buffer = QBuffer()
            self._buffer.setData(QByteArray(self.pcm))
            self._buffer.open(QIODeviceBase.OpenModeFlag.ReadOnly)
            self.disponible = True
        except Exception:
            self._sink, self._buffer, self.disponible = None, None, False

    def pitar(self) -> bool:
        """Dispara un pitido. True solo si realmente se envió al altavoz."""
        if self.silenciado or self._volumen <= 0:
            return False
        self.disparos += 1
        if not self.disponible:
            return False
        try:
            self._sink.stop()
            self._buffer.seek(0)
            self._sink.start(self._buffer)
            return True
        except Exception:
            self.disponible = False
            return False


class ControladorFantasma:
    """Sesión de referencia elegida y su comparación con la sesión en vivo, segundo a segundo."""

    def __init__(self):
        self.sesion: Optional[SesionFantasma] = None

    def cargar(self, sesion: Optional[SesionFantasma]) -> None:
        self.sesion = sesion

    @property
    def activo(self) -> bool:
        return self.sesion is not None

    def actualizar(self, t: float, bpm_actual: Optional[float]) -> Optional[ComparacionFantasma]:
        return None if self.sesion is None else self.sesion.comparar(t, bpm_actual)

    def terminado(self, t: float) -> bool:
        return self.sesion is not None and t > self.sesion.duracion_s + SesionFantasma.VENTANA_S


class CalculadorAcoplamientoRSA(AcoplamientoPulsoResp):
    """Alias descriptivo: arritmia sinusoidal respiratoria (pulso frente a fase respiratoria)."""


@dataclass(frozen=True)
class ResultadoPiloto:
    estado: str                  # "desactivado" | "sin_dato" | "sube" | "clavado" | "frena"
    texto: str
    desviacion_bpm: float        # < 0 por debajo del rango, 0 dentro, > 0 por encima
    rango: Optional[tuple[float, float]]


class PilotoZonaObjetivo:
    def __init__(self, fc_max: float = FC_MAX_REFERENCIA, zona: Optional[int] = None):
        self.fc_max = float(fc_max)
        self.zona = zona                                   # índice 0..4 o None (desactivado)

    def evaluar(self, bpm: Optional[float]) -> ResultadoPiloto:
        if self.zona is None:
            return ResultadoPiloto("desactivado", "Desactivado", 0.0, None)
        rango = rango_zona(self.zona, self.fc_max)
        estado = estado_piloto(bpm, self.zona, self.fc_max)
        if estado is None:
            return ResultadoPiloto("sin_dato", "Sin pulso", 0.0, rango)
        desv = bpm - rango[0] if estado == "sube" else bpm - rango[1] if estado == "frena" else 0.0
        return ResultadoPiloto(estado, TEXTOS_PILOTO[estado], float(desv), rango)
