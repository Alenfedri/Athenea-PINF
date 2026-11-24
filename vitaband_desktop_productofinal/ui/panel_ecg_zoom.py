"""ECG histórico con vista general y ampliación de un intervalo (RF-35).

Arriba, la vista general con un intervalo arrastrable; abajo, el detalle de ese
intervalo. Botones para acercar, alejar y desplazar. El detalle no puede ir más
allá de lo almacenado: el ECG se guarda como envolvente de 1 s, así que la máxima
ampliación es de 1 s por intervalo.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from domain.ecg_historico import EcgReducido
from ui.formato import fecha_hora
from ui.grafica_ecg import GraficaEcg, MIN_SELECCION_S

MAX_BINS_DETALLE = 1200
RESOLUCION_MAXIMA_S = 1

Proveedor = Callable[[int, int, int], Optional[EcgReducido]]


# --- Aritmética del intervalo (pura, sin Qt) ---

def _ajustar(inicio: int, ancho: int, minimo: int, maximo: int) -> tuple[int, int]:
    ancho = min(ancho, maximo - minimo)
    inicio = min(max(inicio, minimo), maximo - ancho)
    return inicio, inicio + ancho


def ventana_inicial(minimo: int, maximo: int) -> tuple[int, int]:
    """Intervalo por defecto: ~20 % del rango (al menos 60 s), centrado."""
    total = maximo - minimo
    ancho = min(total, max(total // 5, 60))
    return _ajustar(minimo + (total - ancho) // 2, ancho, minimo, maximo)


def acercar(a: int, b: int, minimo: int, maximo: int) -> tuple[int, int]:
    ancho = max(MIN_SELECCION_S, (b - a) // 2)
    return _ajustar((a + b) // 2 - ancho // 2, ancho, minimo, maximo)


def alejar(a: int, b: int, minimo: int, maximo: int) -> tuple[int, int]:
    return _ajustar((a + b) // 2 - (b - a), (b - a) * 2, minimo, maximo)


def desplazar(a: int, b: int, minimo: int, maximo: int, direccion: int) -> tuple[int, int]:
    paso = max(1, (b - a) // 2)
    return _ajustar(a + direccion * paso, b - a, minimo, maximo)


class PanelEcgZoom(QWidget):

    def __init__(self, proveedor: Proveedor, parent=None):
        super().__init__(parent)
        self._proveedor = proveedor
        self._rango = (0, 1)
        self._con_datos = False

        self.vista_general = GraficaEcg(titulo="ECG histórico", con_seleccion=True)
        self.vista_detalle = GraficaEcg(titulo="Detalle del ECG")
        self.vista_detalle.setMouseEnabled(x=True, y=False)

        self.btn_acercar = QPushButton("Acercar")
        self.btn_alejar = QPushButton("Alejar")
        self.btn_izquierda = QPushButton("◀")
        self.btn_derecha = QPushButton("▶")
        self.btn_restablecer = QPushButton("Restablecer")
        self.lbl_detalle = QLabel()

        fila = QHBoxLayout()
        for b in (self.btn_acercar, self.btn_alejar, self.btn_izquierda, self.btn_derecha, self.btn_restablecer):
            fila.addWidget(b)
        fila.addWidget(self.lbl_detalle, stretch=1)

        capa = QVBoxLayout(self)
        capa.setContentsMargins(0, 0, 0, 0)
        capa.addWidget(self.vista_general, stretch=1)
        capa.addLayout(fila)
        capa.addWidget(self.vista_detalle, stretch=1)

        self.btn_acercar.clicked.connect(lambda: self._mover(acercar))
        self.btn_alejar.clicked.connect(lambda: self._mover(alejar))
        self.btn_izquierda.clicked.connect(lambda: self._mover(lambda a, b, lo, hi: desplazar(a, b, lo, hi, -1)))
        self.btn_derecha.clicked.connect(lambda: self._mover(lambda a, b, lo, hi: desplazar(a, b, lo, hi, 1)))
        self.btn_restablecer.clicked.connect(self.restablecer)
        self.vista_general.region_cambiada.connect(self._on_region)
        self._habilitar(False)

    # ------------------------------------------------------------------

    def seleccion(self) -> Optional[tuple[int, int]]:
        return self.vista_general.seleccion()

    def mostrar(self, reducido: Optional[EcgReducido], desde_ts: int, hasta_ts: int,
                mensaje: Optional[str] = None) -> None:
        self._rango = (desde_ts, hasta_ts)
        self.vista_general.mostrar(reducido, desde_ts, hasta_ts, mensaje)
        self._con_datos = mensaje is None and reducido is not None and reducido.tiene_datos
        self._habilitar(self._con_datos)

        if not self._con_datos:
            self.lbl_detalle.setText("")
            self.vista_detalle.mostrar(None, 0, 1, "Detalle del ECG: no hay señal que ampliar")
            return

        previa = self.seleccion()
        # Una selección degenerada (el rango cambió y la región quedó recortada) no sirve
        if previa is None or previa[0] < desde_ts or previa[1] > hasta_ts \
                or previa[1] - previa[0] < min(MIN_SELECCION_S, hasta_ts - desde_ts):
            previa = ventana_inicial(desde_ts, hasta_ts)
        self._aplicar(*previa)

    @Slot()
    def restablecer(self) -> None:
        if self._con_datos:
            self._aplicar(*ventana_inicial(*self._rango))

    # ------------------------------------------------------------------

    def _habilitar(self, activo: bool) -> None:
        for b in (self.btn_acercar, self.btn_alejar, self.btn_izquierda, self.btn_derecha, self.btn_restablecer):
            b.setEnabled(activo)

    def _mover(self, operacion) -> None:
        actual = self.seleccion()
        if not self._con_datos or actual is None:
            return
        self._aplicar(*operacion(actual[0], actual[1], *self._rango))

    def _on_region(self, a: int, b: int) -> None:
        self._cargar_detalle(a, b)

    def _aplicar(self, a: int, b: int) -> None:
        self.vista_general.fijar_seleccion(a, b)
        self._cargar_detalle(a, b)

    def _cargar_detalle(self, a: int, b: int) -> None:
        if b <= a:
            b = a + 1
        reducido = self._proveedor(a, b, min(b - a, MAX_BINS_DETALLE))
        self.vista_detalle.mostrar(reducido, a, b)
        resolucion = max(RESOLUCION_MAXIMA_S, round((b - a) / min(b - a, MAX_BINS_DETALLE)))
        nota = " (máxima ampliación)" if resolucion <= RESOLUCION_MAXIMA_S else ""
        self.lbl_detalle.setText(f"{fecha_hora(a)} → {fecha_hora(b)} · {b - a} s · {resolucion} s/intervalo{nota}")
