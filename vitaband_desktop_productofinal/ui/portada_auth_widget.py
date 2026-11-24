import math
import os
import random
from pathlib import Path
from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSequentialAnimationGroup,
    Qt,
    QTimer,
    Property,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


RUTA_LOGO = str(Path(__file__).resolve().parents[1] / "assets" / "logo_athenea.png")


def _crear_emblema_circular(ruta_imagen: str, diametro: int = 240) -> QPixmap:
    """Recorta assets/logo_athenea.png en círculo con borde radial difuminado."""
    salida = QPixmap(diametro, diametro)
    salida.fill(Qt.transparent)

    painter = QPainter(salida)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

    # Halo exterior respiratorio sutil
    halo = QRadialGradient(diametro / 2, diametro / 2, diametro / 2)
    halo.setColorAt(0.72, QColor(16, 185, 129, 55))
    halo.setColorAt(0.90, QColor(212, 175, 55, 30))
    halo.setColorAt(1.00, QColor(9, 14, 12, 0))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(halo))
    painter.drawEllipse(0, 0, diametro, diametro)

    margen = 12
    inner = diametro - margen * 2
    clip = QPainterPath()
    clip.addEllipse(margen, margen, inner, inner)
    painter.setClipPath(clip)

    if os.path.exists(ruta_imagen):
        src = QPixmap(ruta_imagen)
        if not src.isNull():
            # Recorte centrado cuadrado para mantener proporción perfecta
            lado = min(src.width(), src.height())
            x0 = (src.width() - lado) // 2
            y0 = (src.height() - lado) // 2
            cuadrado = src.copy(x0, y0, lado, lado).scaled(
                inner, inner, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            painter.drawPixmap(margen, margen, cuadrado)
    else:
        # Fallback minimalista si no existe aún el PNG en entorno aislado
        grad = QRadialGradient(diametro / 2, diametro / 2, inner / 2)
        grad.setColorAt(0.0, QColor("#1B4D3E"))
        grad.setColorAt(1.0, QColor("#090E0C"))
        painter.fillRect(margen, margen, inner, inner, grad)

    # Viñeta radial interna para fundir los bordes con el fondo Obsidiana
    vignette = QRadialGradient(diametro / 2, diametro / 2, inner / 2)
    vignette.setColorAt(0.0, QColor(9, 14, 12, 0))
    vignette.setColorAt(0.78, QColor(9, 14, 12, 0))
    vignette.setColorAt(1.0, QColor(9, 14, 12, 235))
    painter.setBrush(QBrush(vignette))
    painter.drawEllipse(margen, margen, inner, inner)

    painter.setClipping(False)
    # Aro fino doble Esmeralda + Oro Champán
    painter.setPen(QPen(QColor(16, 185, 129, 140), 1.6))
    painter.drawEllipse(margen, margen, inner, inner)
    painter.setPen(QPen(QColor(212, 175, 55, 95), 1.0))
    painter.drawEllipse(margen - 3, margen - 3, inner + 6, inner + 6)

    painter.end()
    return salida


class LuxuryGradientButton(QPushButton):
    """Botón principal con degradado Oro Champán -> Esmeralda y destello especular."""

    def __init__(self, texto: str, parent=None):
        super().__init__(texto, parent)
        self._shimmer_pos = -0.4
        self._hover_level = 0.0
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(48)

        self._anim_shimmer = QPropertyAnimation(self, b"shimmerPos", self)
        self._anim_shimmer.setDuration(750)
        self._anim_shimmer.setEasingCurve(QEasingCurve.InOutCubic)

        self._anim_hover = QPropertyAnimation(self, b"hoverLevel", self)
        self._anim_hover.setDuration(200)
        self._anim_hover.setEasingCurve(QEasingCurve.OutCubic)

    def get_shimmer_pos(self) -> float:
        return self._shimmer_pos

    def set_shimmer_pos(self, val: float):
        self._shimmer_pos = val
        self.update()

    shimmerPos = Property(float, get_shimmer_pos, set_shimmer_pos)

    def get_hover_level(self) -> float:
        return self._hover_level

    def set_hover_level(self, val: float):
        self._hover_level = val
        self.update()

    hoverLevel = Property(float, get_hover_level, set_hover_level)

    def enterEvent(self, event):
        self._anim_hover.stop()
        self._anim_hover.setEndValue(1.0)
        self._anim_hover.start()

        self._anim_shimmer.stop()
        self._anim_shimmer.setStartValue(-0.35)
        self._anim_shimmer.setEndValue(1.35)
        self._anim_shimmer.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._anim_hover.stop()
        self._anim_hover.setEndValue(0.0)
        self._anim_hover.start()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)

        grad = QLinearGradient(rect.topLeft(), rect.topRight())
        grad.setColorAt(0.0, QColor("#E2B93B") if self._hover_level > 0.5 else QColor("#D4AF37"))
        grad.setColorAt(0.45, QColor("#34D399") if self._hover_level > 0.5 else QColor("#10B981"))
        grad.setColorAt(1.0, QColor("#059669"))

        path = QPainterPath()
        path.addRoundedRect(rect, 11, 11)
        painter.fillPath(path, grad)

        # Destello especular animado tipo Apple
        if -0.3 <= self._shimmer_pos <= 1.3:
            painter.save()
            painter.setClipPath(path)
            cx = rect.width() * self._shimmer_pos
            beam = QLinearGradient(cx - 70, 0, cx + 70, rect.height())
            beam.setColorAt(0.0, QColor(255, 255, 255, 0))
            beam.setColorAt(0.5, QColor(255, 255, 255, 85))
            beam.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillRect(rect, beam)
            painter.restore()

        painter.setPen(QPen(QColor(255, 255, 255, int(45 + 65 * self._hover_level)), 1.0))
        painter.drawPath(path)

        painter.setPen(QColor("#F8FAFC"))
        font = QFont("Segoe UI", 11, QFont.Bold)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 1.2)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, self.text())
        painter.end()


class SelloGrupoAtheneaWidget(QWidget):
    """Insignia inferior con ramas de laurel doradas/esmeralda para Grupo Athenea."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(270, 56)
        self.setMaximumHeight(60)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0

        # Dibujo vectorial de laureles simétricos
        for side in (-1, 1):
            painter.save()
            painter.translate(cx + side * 96, cy + 2)
            painter.scale(side, 1)
            pen = QPen(QColor(16, 185, 129, 170), 1.4)
            painter.setPen(pen)
            arc = QPainterPath()
            arc.moveTo(-14, 14)
            arc.quadTo(4, 2, -6, -16)
            painter.drawPath(arc)

            painter.setBrush(QColor(212, 175, 55, 190))
            painter.setPen(Qt.NoPen)
            for idx, (lx, ly, ang) in enumerate(
                [(-10, 10, -35), (-5, 3, -25), (-3, -5, -15), (-5, -13, 5)]
            ):
                painter.save()
                painter.translate(lx, ly)
                painter.rotate(ang)
                painter.drawEllipse(QRectF(-2.2, -5.0, 4.4, 10.0))
                painter.restore()
            painter.restore()

        painter.setPen(QColor("#94A3B8"))
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(QRectF(0, 8, w, 18), Qt.AlignCenter, "Desarrollado por")

        painter.setPen(QColor("#F8FAFC"))
        f_bold = QFont("Segoe UI", 11, QFont.Bold)
        f_bold.setLetterSpacing(QFont.AbsoluteSpacing, 0.6)
        painter.setFont(f_bold)
        painter.drawText(QRectF(0, 26, w, 22), Qt.AlignCenter, "Grupo Athenea")
        painter.end()


class HeroBiometricCanvas(QWidget):
    """Lienzo vivo a 60 FPS con onda ECG clínica P-QRS-T, partículas y paralaje."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self._phase = 0.0
        self._beat_phase = 0.0
        self._mouse_offset = QPointF(0.0, 0.0)
        self._target_offset = QPointF(0.0, 0.0)

        rng = random.Random(42)
        self._particles = [
            {
                "x": rng.random(),
                "y": rng.random(),
                "r": rng.uniform(1.2, 3.2),
                "speed": rng.uniform(0.0004, 0.0014),
                "depth": rng.uniform(0.4, 1.4),
                "gold": rng.random() < 0.28,
            }
            for _ in range(38)
        ]

        self._timer = QTimer(self)
        self._timer.setInterval(16)  # ~60 FPS
        self._timer.timeout.connect(self._tick)       # se arranca en showEvent y se detiene en hide/closeEvent

    def detener_animaciones(self):
        if self._timer.isActive():
            self._timer.stop()

    def showEvent(self, event):
        if not self._timer.isActive():
            self._timer.start()
        super().showEvent(event)

    def mouseMoveEvent(self, event):
        if self.width() > 0 and self.height() > 0:
            nx = (event.position().x() / self.width() - 0.5) * 24.0
            ny = (event.position().y() / self.height() - 0.5) * 18.0
            self._target_offset = QPointF(nx, ny)
        super().mouseMoveEvent(event)

    def _tick(self):
        self._phase = (self._phase + 0.011) % 1.0
        self._beat_phase = (self._beat_phase + 0.018) % 1.0
        # Interpolación suave de paralaje tipo Apple
        self._mouse_offset += (self._target_offset - self._mouse_offset) * 0.08
        for p in self._particles:
            p["y"] -= p["speed"]
            if p["y"] < -0.02:
                p["y"] = 1.02
        self.update()

    @staticmethod
    def _ecg_sample(t: float) -> float:
        """Complejo fisiológico P-QRS-T normalizado en [-1, 1]."""
        u = t % 1.0
        # Onda P
        p = 0.14 * math.exp(-((u - 0.18) ** 2) / (2 * 0.018**2))
        # Onda Q
        q = -0.16 * math.exp(-((u - 0.34) ** 2) / (2 * 0.007**2))
        # Pico R agudo
        r = 1.00 * math.exp(-((u - 0.37) ** 2) / (2 * 0.008**2))
        # Onda S
        s = -0.28 * math.exp(-((u - 0.40) ** 2) / (2 * 0.009**2))
        # Onda T
        tw = 0.26 * math.exp(-((u - 0.62) ** 2) / (2 * 0.032**2))
        return p + q + r + s + tw

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()

        # Fondo Obsidiana profundo
        painter.fillRect(self.rect(), QColor("#090E0C"))

        # Halo respiratorio Verde Pino / Esmeralda centrado en la zona hero izquierda
        pulse = 0.5 + 0.5 * math.sin(self._beat_phase * 2 * math.pi)
        cx = w * 0.30 + self._mouse_offset.x()
        cy = h * 0.34 + self._mouse_offset.y()
        rad = max(w, h) * (0.42 + 0.04 * pulse)

        aurora = QRadialGradient(cx, cy, rad)
        aurora.setColorAt(0.0, QColor(27, 77, 62, int(115 + 35 * pulse)))
        aurora.setColorAt(0.45, QColor(16, 185, 129, int(36 + 18 * pulse)))
        aurora.setColorAt(1.0, QColor(9, 14, 12, 0))
        painter.fillRect(self.rect(), aurora)

        # Partículas biométricas con paralaje
        painter.setPen(Qt.NoPen)
        for p in self._particles:
            px = p["x"] * w + self._mouse_offset.x() * p["depth"]
            py = p["y"] * h + self._mouse_offset.y() * p["depth"]
            alpha = int(75 + 65 * math.sin((self._phase + p["x"]) * 2 * math.pi))
            col = QColor(212, 175, 55, alpha) if p["gold"] else QColor(16, 185, 129, alpha)
            painter.setBrush(col)
            painter.drawEllipse(QPointF(px, py), p["r"], p["r"])

        # Onda ECG P-QRS-T recorriendo el ancho del panel hero (alineada con el emblema)
        hero_w = w * 0.60
        ecg_y_base = h * 0.255 + self._mouse_offset.y() * 0.35
        amp = min(56.0, h * 0.065)

        ecg_path = QPainterPath()
        steps = 220
        cursor_x = self._phase * hero_w
        cursor_y = ecg_y_base

        for i in range(steps + 1):
            frac = i / steps
            x = frac * hero_w
            y = ecg_y_base - self._ecg_sample(frac * 2.2 - self._phase * 1.4) * amp
            if i == 0:
                ecg_path.moveTo(x, y)
            else:
                ecg_path.lineTo(x, y)
            if abs(x - cursor_x) < (hero_w / steps):
                cursor_y = y

        line_grad = QLinearGradient(0, ecg_y_base, hero_w, ecg_y_base)
        line_grad.setColorAt(0.0, QColor(16, 185, 129, 15))
        line_grad.setColorAt(0.5, QColor(16, 185, 129, 165))
        line_grad.setColorAt(1.0, QColor(16, 185, 129, 15))

        # Resplandor suave + trazo nítido
        painter.setPen(QPen(QBrush(line_grad), 5.0))
        painter.drawPath(ecg_path)
        painter.setPen(QPen(QColor(167, 243, 208, 190), 1.8))
        painter.drawPath(ecg_path)

        # Destello luminoso móvil sobre el trazado ECG
        spark = QRadialGradient(cursor_x, cursor_y, 26)
        spark.setColorAt(0.0, QColor(167, 243, 208, 220))
        spark.setColorAt(0.4, QColor(16, 185, 129, 95))
        spark.setColorAt(1.0, QColor(16, 185, 129, 0))
        painter.setBrush(spark)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(cursor_x, cursor_y), 26, 26)

        painter.end()


class SlidingTabHeader(QWidget):
    """Selector animado estilo Apple con subrayado deslizante entre Login y Sign Up."""

    tabChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._indicator_x = 0.0
        self._active_idx = 0
        self.setMinimumHeight(46)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(0)

        self.btn_tab_login = QPushButton("Iniciar Sesión")
        self.btn_tab_signup = QPushButton("Crear Cuenta")
        for idx, btn in enumerate((self.btn_tab_login, self.btn_tab_signup)):
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFlat(True)
            btn.clicked.connect(lambda _=False, i=idx: self.set_active_tab(i))
            layout.addWidget(btn)

        self._anim = QPropertyAnimation(self, b"indicatorX", self)
        self._anim.setDuration(260)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._actualizar_estilos()

    def get_indicator_x(self) -> float:
        return self._indicator_x

    def set_indicator_x(self, val: float):
        self._indicator_x = val
        self.update()

    indicatorX = Property(float, get_indicator_x, set_indicator_x)

    def resizeEvent(self, event):
        self._indicator_x = (self.width() / 2.0) * self._active_idx
        super().resizeEvent(event)

    def set_active_tab(self, index: int):
        if index == self._active_idx:
            return
        self._active_idx = index
        self._actualizar_estilos()
        self._anim.stop()
        self._anim.setEndValue((self.width() / 2.0) * index)
        self._anim.start()
        self.tabChanged.emit(index)

    def fijar(self, index: int):
        """Sincroniza el selector con la página activa sin emitir tabChanged."""
        if index == self._active_idx:
            return
        self._active_idx = index
        self._actualizar_estilos()
        self._anim.stop()
        self._anim.setEndValue((self.width() / 2.0) * index)
        self._anim.start()

    def _actualizar_estilos(self):
        activo = (
            "QPushButton { color: #F8FAFC; font-size: 15px; font-weight: 700; "
            "background: transparent; border: none; padding: 6px; }"
        )
        inactivo = (
            "QPushButton { color: #94A3B8; font-size: 15px; font-weight: 500; "
            "background: transparent; border: none; padding: 6px; } "
            "QPushButton:hover { color: #D1FAE5; }"
        )
        self.btn_tab_login.setStyleSheet(activo if self._active_idx == 0 else inactivo)
        self.btn_tab_signup.setStyleSheet(activo if self._active_idx == 1 else inactivo)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()

        # Línea base sutil
        painter.setPen(QPen(QColor("#21312B"), 1.2))
        painter.drawLine(0, h - 2, w, h - 2)

        # Barra activa deslizante Esmeralda -> Blanco
        seg_w = w / 2.0
        grad = QLinearGradient(self._indicator_x, h - 3, self._indicator_x + seg_w, h - 3)
        grad.setColorAt(0.0, QColor("#10B981"))
        grad.setColorAt(0.5, QColor("#F8FAFC"))
        grad.setColorAt(1.0, QColor("#10B981"))
        painter.setPen(Qt.NoPen)
        painter.setBrush(grad)
        painter.drawRoundedRect(QRectF(self._indicator_x + 14, h - 3.5, seg_w - 28, 3.0), 1.5, 1.5)
        painter.end()


class PortadaAuthWidget(HeroBiometricCanvas):
    """Portada a pantalla completa de VitaBand App + Tarjeta de Acceso Verde Pino."""

    def __init__(self, logo_path: str = RUTA_LOGO, parent=None, formularios: bool = True):
        super().__init__(parent)
        self._logo_path = logo_path
        self._formularios = formularios
        self._entrada_hecha = False
        self._anim_group = None
        self._form_anim = None
        self._form_destino = None
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(56, 36, 56, 36)
        root.setSpacing(40)

        # ================= PANEL IZQUIERDO: HERO VITABAND =================
        hero_col = QVBoxLayout()
        hero_col.setAlignment(Qt.AlignCenter)
        hero_col.setSpacing(10)

        hero_col.addStretch(1)

        # 1. Emblema circular Athenea con VitaBand ECG
        self.lbl_emblema = QLabel()
        self.lbl_emblema.setAlignment(Qt.AlignCenter)
        self._pixmap_emblema = _crear_emblema_circular(self._logo_path, 240)
        self.lbl_emblema.setPixmap(self._pixmap_emblema)
        hero_col.addWidget(self.lbl_emblema, alignment=Qt.AlignCenter)

        hero_col.addSpacing(8)

        # 2. Título principal protagonista: VitaBand App
        self.lbl_titulo = QLabel("VitaBand App")
        self.lbl_titulo.setAlignment(Qt.AlignCenter)
        self.lbl_titulo.setStyleSheet(
            "color: #F8FAFC; font-family: 'Georgia', 'Times New Roman', serif; "
            "font-size: 54px; font-weight: 700; letter-spacing: 0.5px; background: transparent;"
        )
        hero_col.addWidget(self.lbl_titulo)

        # 3. Subcabecera técnica
        self.lbl_subcabecera = QLabel(
            "BANDA PECTORAL ECG · TELEMETRÍA BIOMÉTRICA AVANZADA"
        )
        self.lbl_subcabecera.setWordWrap(True)
        self.lbl_subcabecera.setMaximumWidth(460)
        self.lbl_subcabecera.setAlignment(Qt.AlignCenter)
        self.lbl_subcabecera.setStyleSheet(
            "color: #A7F3D0; font-size: 13px; font-weight: 600; "
            "letter-spacing: 2.8px; background: transparent;"
        )
        hero_col.addWidget(self.lbl_subcabecera)

        hero_col.addSpacing(14)

        # 4. Frase gancho directa
        self.lbl_frase = QLabel(
            "Domina cada latido. Convierte tu fisiología en rendimiento real."
        )
        self.lbl_frase.setWordWrap(True)
        self.lbl_frase.setMaximumWidth(460)
        self.lbl_frase.setAlignment(Qt.AlignCenter)
        self.lbl_frase.setStyleSheet(
            "color: #D1FAE5; font-size: 19px; font-weight: 500; "
            "line-height: 1.35; background: transparent;"
        )
        hero_col.addWidget(self.lbl_frase)

        hero_col.addStretch(1)

        # 5. Sello inferior Desarrollado por Grupo Athenea
        self.sello_athenea = SelloGrupoAtheneaWidget()
        hero_col.addWidget(self.sello_athenea, alignment=Qt.AlignCenter)

        root.addLayout(hero_col, stretch=6)

        # ================= PANEL DERECHO: TARJETA DE ACCESO =================
        card_wrapper = QVBoxLayout()
        card_wrapper.setAlignment(Qt.AlignCenter)

        self.access_card = QFrame()
        self.access_card.setObjectName("AccessCard")
        self.access_card.setMinimumWidth(410)
        self.access_card.setMaximumWidth(460)
        self.access_card.setStyleSheet(
            """
            QFrame#AccessCard {
                background-color: rgba(15, 24, 20, 238);
                border: 1.5px solid #10B981;
                border-radius: 22px;
            }
            QLineEdit {
                background-color: rgba(9, 14, 12, 210);
                border: 1.3px solid #1B4D3E;
                border-radius: 10px;
                padding: 12px 14px;
                color: #F8FAFC;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 1.6px solid #10B981;
                background-color: rgba(12, 22, 18, 245);
            }
            QCheckBox {
                color: #CBD5E1;
                font-size: 13px;
                spacing: 8px;
                background: transparent;
            }
            QCheckBox::indicator {
                width: 17px;
                height: 17px;
                border-radius: 4px;
                border: 1.3px solid #334155;
                background: #090E0C;
            }
            QCheckBox::indicator:checked {
                background: #10B981;
                border-color: #10B981;
            }
            """
        )

        card_layout = QVBoxLayout(self.access_card)
        card_layout.setContentsMargins(34, 28, 34, 32)
        card_layout.setSpacing(18)

        self.tab_header = SlidingTabHeader()
        card_layout.addWidget(self.tab_header)

        self.stack_formularios = QStackedWidget()
        self.stack_formularios.setStyleSheet("background: transparent;")
        if self._formularios:
    
            # --- Página 0: Iniciar Sesión ---
            self.page_login = QWidget()
            l_lay = QVBoxLayout(self.page_login)
            l_lay.setContentsMargins(0, 8, 0, 0)
            l_lay.setSpacing(14)

            self.lbl_acceso_titulo = QLabel("Acceso a tu cuenta")
            self.lbl_acceso_titulo.setAlignment(Qt.AlignCenter)
            self.lbl_acceso_titulo.setStyleSheet(
                "color: #F8FAFC; font-size: 22px; font-weight: 700; background: transparent;"
            )
            l_lay.addWidget(self.lbl_acceso_titulo)
            l_lay.addSpacing(4)

            self.txt_email = QLineEdit()
            self.txt_email.setPlaceholderText("Correo Electrónico")
            l_lay.addWidget(self.txt_email)

            self.txt_password = QLineEdit()
            self.txt_password.setPlaceholderText("Contraseña")
            self.txt_password.setEchoMode(QLineEdit.Password)
            l_lay.addWidget(self.txt_password)

            self.chk_recordar = QCheckBox("Recordar sesión")
            l_lay.addWidget(self.chk_recordar)
            l_lay.addSpacing(4)

            self.btn_login = LuxuryGradientButton("INICIAR SESIÓN")
            l_lay.addWidget(self.btn_login)
            l_lay.addSpacing(6)

            self.btn_olvide = QPushButton("Olvidé mi contraseña?")
            self.btn_crear_link = QPushButton("Crear cuenta nueva")
            for link in (self.btn_olvide, self.btn_crear_link):
                link.setFlat(True)
                link.setCursor(Qt.PointingHandCursor)
                link.setStyleSheet(
                    "QPushButton { color: #CBD5E1; font-size: 13px; "
                    "text-decoration: underline; background: transparent; border: none; } "
                    "QPushButton:hover { color: #10B981; }"
                )
                l_lay.addWidget(link, alignment=Qt.AlignCenter)

            self.btn_crear_link.clicked.connect(lambda: self.tab_header.set_active_tab(1))

            # --- Página 1: Crear Cuenta ---
            self.page_signup = QWidget()
            s_lay = QVBoxLayout(self.page_signup)
            s_lay.setContentsMargins(0, 8, 0, 0)
            s_lay.setSpacing(13)

            lbl_reg = QLabel("Crea tu perfil biométrico")
            lbl_reg.setAlignment(Qt.AlignCenter)
            lbl_reg.setStyleSheet(
                "color: #F8FAFC; font-size: 21px; font-weight: 700; background: transparent;"
            )
            s_lay.addWidget(lbl_reg)

            self.txt_reg_nombre = QLineEdit()
            self.txt_reg_nombre.setPlaceholderText("Nombre completo del deportista")
            s_lay.addWidget(self.txt_reg_nombre)

            self.txt_reg_email = QLineEdit()
            self.txt_reg_email.setPlaceholderText("Correo Electrónico")
            s_lay.addWidget(self.txt_reg_email)

            self.txt_reg_password = QLineEdit()
            self.txt_reg_password.setPlaceholderText("Contraseña segura")
            self.txt_reg_password.setEchoMode(QLineEdit.Password)
            s_lay.addWidget(self.txt_reg_password)

            self.btn_signup = LuxuryGradientButton("CREAR CUENTA")
            s_lay.addWidget(self.btn_signup)

            self.btn_volver_login = QPushButton("Ya tengo cuenta · Iniciar sesión")
            self.btn_volver_login.setFlat(True)
            self.btn_volver_login.setCursor(Qt.PointingHandCursor)
            self.btn_volver_login.setStyleSheet(
                "QPushButton { color: #A7F3D0; font-size: 13px; "
                "text-decoration: underline; background: transparent; border: none; }"
            )
            self.btn_volver_login.clicked.connect(lambda: self.tab_header.set_active_tab(0))
            s_lay.addWidget(self.btn_volver_login, alignment=Qt.AlignCenter)

            self.stack_formularios.addWidget(self.page_login)
            self.stack_formularios.addWidget(self.page_signup)
            card_layout.addWidget(self.stack_formularios)


        self.tab_header.tabChanged.connect(self._animar_cambio_formulario)

        card_wrapper.addWidget(self.access_card)
        root.addLayout(card_wrapper, stretch=4)

    def montar_formularios(self, contenido: QWidget):
        """Reparenta dentro de AccessCard los formularios reales (Login / Registro / 2FA) de LoginDialog."""
        self.stack_formularios.setParent(None)
        self.stack_formularios.deleteLater()
        self.stack_formularios = contenido
        self.access_card.layout().addWidget(contenido)

    def mostrar_pagina(self, indice: int):
        """0 login · 1 registro · 2 verificación 2FA (sin selector)."""
        self.tab_header.setVisible(indice in (0, 1))
        self.tab_header.fijar(min(indice, 1))
        if self.isVisible():
            self._fundido_pagina(self.stack_formularios.currentWidget())

    def _animar_cambio_formulario(self, index: int):
        self.stack_formularios.setCurrentIndex(index)
        self._fundido_pagina(self.stack_formularios.currentWidget())

    def _fundido_pagina(self, destino):
        if destino is None:
            return
        self._limpiar_fundido()
        efecto = QGraphicsOpacityEffect(destino)
        efecto.setOpacity(0.0)
        destino.setGraphicsEffect(efecto)

        anim = QPropertyAnimation(efecto, b"opacity", self)
        anim.setDuration(240)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(lambda: destino.setGraphicsEffect(None))
        self._form_anim = anim
        self._form_destino = destino
        anim.start()

    def _limpiar_fundido(self):
        if self._form_anim is not None:
            self._form_anim.stop()
        if getattr(self, "_form_destino", None) is not None:
            self._form_destino.setGraphicsEffect(None)
            self._form_destino = None

    def iniciar_coreografia_entrada(self):
        """Cascada escalonada estilo Apple al mostrar la pantalla."""
        elementos = [
            self.lbl_emblema,
            self.lbl_titulo,
            self.lbl_subcabecera,
            self.lbl_frase,
            self.sello_athenea,
            self.access_card,
        ]
        seq = QSequentialAnimationGroup(self)
        for idx, widget in enumerate(elementos):
            efecto = QGraphicsOpacityEffect(widget)
            efecto.setOpacity(0.0)
            widget.setGraphicsEffect(efecto)

            if idx > 0:
                seq.addPause(65)
            anim = QPropertyAnimation(efecto, b"opacity", self)
            anim.setDuration(280)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.finished.connect(lambda w=widget: w.setGraphicsEffect(None))
            seq.addAnimation(anim)

        self._anim_group = seq
        seq.start()

    def limpiar_efectos(self):
        """Detiene las animaciones de opacidad y retira todo QGraphicsEffect residual."""
        if self._anim_group is not None:
            self._anim_group.stop()
        self._limpiar_fundido()
        for w in (self.lbl_emblema, self.lbl_titulo, self.lbl_subcabecera, self.lbl_frase, self.sello_athenea,
                  self.access_card):
            w.setGraphicsEffect(None)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._entrada_hecha:
            self._entrada_hecha = True
            self.iniciar_coreografia_entrada()

    def closeEvent(self, event):
        self.limpiar_efectos()
        self.detener_animaciones()
        super().closeEvent(event)

    def hideEvent(self, event):
        self.limpiar_efectos()
        self.detener_animaciones()
        super().hideEvent(event)


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    win = PortadaAuthWidget()
    win.setWindowTitle("VitaBand App · Grupo Athenea")
    win.showMaximized()
    win.iniciar_coreografia_entrada()
    sys.exit(app.exec())