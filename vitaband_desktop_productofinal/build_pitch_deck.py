"""Genera VitaBand_Presentacion_Comercial.pptx (16:9, estética Keynote, Verde Pino & Obsidiana) con gráficos a 300 DPI,
transiciones y animaciones de entrada nativas OpenXML."""
import math
import os
import random

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Ellipse, FancyBboxPatch, Rectangle
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml import parse_xml
from pptx.util import Emu, Inches, Pt

OUT = "VitaBand_Presentacion_Comercial.pptx"
IMG = os.path.join("assets", "pitch")
os.makedirs(IMG, exist_ok=True)
DPI = 300
ESM, ESM2, ORO, AMB, PINO = "#10B981", "#34D399", "#D4AF37", "#F59E0B", "#132A23"
CARD, BORDE, BLANCO, GRIS = "#162C25", "#264B3F", "#F8FAFC", "#9DB3A8"
FUENTE = "Segoe UI"


def rgb(h): return RGBColor.from_string(h.lstrip("#").upper())


# ====================== GRÁFICOS (matplotlib, fondo transparente, 300 DPI) ======================
def _estilo(ax):
    ax.set_facecolor("none")
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(colors=GRIS, labelsize=8)


def _g(u, mu, sd): return np.exp(-((u - mu) ** 2) / (2 * sd ** 2))


def pqrst(u): return 0.14 * _g(u, .18, .025) - 0.16 * _g(u, .34, .010) + _g(u, .37, .012) - 0.28 * _g(u, .40, .013) + 0.26 * _g(u, .62, .045)


def grafico_ecg():
    fs, seg = 100, 6.0
    t = np.arange(0, seg, 1 / fs)
    rr = 0.8
    y = np.array([pqrst((x % rr) / rr) for x in t]) + np.random.default_rng(3).normal(0, 0.012, len(t))
    fig, ax = plt.subplots(figsize=(13.333, 2.6), dpi=DPI)
    fig.patch.set_alpha(0)
    _estilo(ax)
    ax.axis("off")
    for lw, a in ((14, .05), (8, .10), (4, .22)):
        ax.plot(t, y, color=ESM, lw=lw, alpha=a, solid_capstyle="round")
    ax.plot(t, y, color=ESM2, lw=1.9)
    picos = [i for i in range(1, len(y) - 1) if y[i] > 0.8 and y[i] >= y[i - 1] and y[i] > y[i + 1]]
    ax.scatter(t[picos], y[picos], s=46, color="#ECFDF5", zorder=5, edgecolor=ESM, linewidth=1.4)
    xp = t[picos[-2]] + 0.33
    ax.scatter([xp], [y[int(xp * fs)]], s=700, color=ESM, alpha=.18, zorder=4)
    ax.scatter([xp], [y[int(xp * fs)]], s=90, color="#FFFFFF", zorder=6)
    ax.set_xlim(0, seg)
    ax.set_ylim(-0.5, 1.2)
    fig.subplots_adjust(0, 0, 1, 1)
    p = os.path.join(IMG, "g1_ecg.png"); fig.savefig(p, transparent=True, dpi=DPI); plt.close(fig); return p


def grafico_calor_tsb():
    rnd = np.random.default_rng(5)
    fig = plt.figure(figsize=(9.2, 4.2), dpi=DPI)
    fig.patch.set_alpha(0)
    ax = fig.add_axes([0.02, 0.12, 0.40, 0.76])
    cargas = np.clip(rnd.normal(0.55, 0.35, (7, 12)), 0, 1)
    cargas[rnd.random((7, 12)) < 0.25] = 0
    cm = matplotlib.colors.LinearSegmentedColormap.from_list("v", ["#1B2E28", "#0E7A55", ESM, "#A7F3D0"])
    ax.imshow(cargas, cmap=cm, aspect="equal")
    ax.set_xticks(np.arange(-.5, 12, 1), minor=True); ax.set_yticks(np.arange(-.5, 7, 1), minor=True)
    ax.grid(which="minor", color="#0B1713", lw=2.2); ax.tick_params(which="both", length=0)
    ax.set_xticks([]); ax.set_yticks(range(7)); ax.set_yticklabels(list("LMXJVSD"), color=GRIS, fontsize=8)
    for s in ax.spines.values(): s.set_visible(False)
    ax.set_title("Mapa de calor · 12 semanas", color=BLANCO, fontsize=11, loc="left", pad=8, fontweight="bold")
    ax2 = fig.add_axes([0.50, 0.12, 0.48, 0.76])
    _estilo(ax2)
    x = np.arange(0, 60)
    ctl = 40 + 5 * np.sin(x / 11) + x * 0.15
    atl = 40 + 9 * np.sin(x / 5.5 + .6) + x * 0.15
    tsb = ctl - atl
    ax2.axhspan(3, 20, color=ESM, alpha=.14); ax2.axhspan(-20, -3, color=AMB, alpha=.14)
    ax2.plot(x, tsb, color=ORO, lw=2.4)
    ax2.fill_between(x, tsb, 0, where=tsb >= 0, color=ESM, alpha=.35); ax2.fill_between(x, tsb, 0, where=tsb < 0, color=AMB, alpha=.35)
    ax2.axhline(0, color=GRIS, lw=.8, ls="--"); ax2.set_ylim(-20, 20); ax2.set_xticks([])
    ax2.text(1, 15, "FORMA · listo para rendir", color=ESM2, fontsize=8.5, fontweight="bold")
    ax2.text(1, -18, "FATIGA · toca recuperar", color=AMB, fontsize=8.5, fontweight="bold")
    ax2.set_title("Balance fatiga / forma (TSB)", color=BLANCO, fontsize=11, loc="left", pad=8, fontweight="bold")
    p = os.path.join(IMG, "g2_calor_tsb.png"); fig.savefig(p, transparent=True, dpi=DPI); plt.close(fig); return p


def grafico_poincare_trimmer():
    rnd = np.random.default_rng(9)
    fig = plt.figure(figsize=(8.4, 4.6), dpi=DPI)
    fig.patch.set_alpha(0)
    ax = fig.add_axes([0.04, 0.12, 0.36, 0.74]); _estilo(ax)
    rr = 800 + np.cumsum(rnd.normal(0, 18, 400)) * 0.35 + rnd.normal(0, 22, 400)
    rr = np.clip(rr, 640, 960)
    x, y = rr[:-1], rr[1:]
    ax.scatter(x, y, s=7, color=ESM, alpha=.55)
    ax.scatter([700, 905], [905, 690], s=36, color="#F43F5E", marker="x", zorder=5)
    ax.add_patch(Ellipse((np.mean(x), np.mean(y)), 190, 70, angle=45, fill=False, ec=ORO, lw=1.8))
    ax.plot([620, 980], [620, 980], color=GRIS, lw=.8, ls="--")
    ax.set_xlim(620, 980); ax.set_ylim(620, 980); ax.set_xticks([]); ax.set_yticks([])
    ax.set_title("Diagrama de Poincaré", color=BLANCO, fontsize=11, loc="left", pad=8, fontweight="bold")
    ax2 = fig.add_axes([0.47, 0.12, 0.51, 0.74]); _estilo(ax2)
    t = np.linspace(0, 60, 600)
    bpm = 95 + 40 * (1 - np.exp(-t / 6)) * (t < 48) + 25 * np.exp(-(t - 48) / 3) * (t >= 48) * 0 - np.where(t > 48, (t - 48) * 4, 0) + rnd.normal(0, 1.5, 600)
    ax2.plot(t, bpm, color=ESM2, lw=1.6); ax2.set_ylim(70, 165)
    ax2.axvspan(0, 8, color="#64748B", alpha=.25); ax2.axvspan(50, 60, color="#64748B", alpha=.25)
    ax2.axvspan(8, 50, color=ESM, alpha=.10)
    for xc in (8, 50):
        ax2.axvline(xc, color=ORO, lw=2.4); ax2.scatter([xc], [78], s=90, color=ORO, zorder=6)
    ax2.text(1, 156, "calentamiento", color=GRIS, fontsize=8); ax2.text(51, 156, "enfriar", color=GRIS, fontsize=8)
    ax2.text(20, 156, "tramo que conservas", color=ESM2, fontsize=9, fontweight="bold")
    ax2.set_xticks([]); ax2.set_yticks([])
    ax2.set_title("Session Trimmer · arrastra los cursores", color=BLANCO, fontsize=11, loc="left", pad=8, fontweight="bold")
    p = os.path.join(IMG, "g3_poincare_trimmer.png"); fig.savefig(p, transparent=True, dpi=DPI); plt.close(fig); return p


def grafico_coach():
    fig = plt.figure(figsize=(5.6, 6.1), dpi=DPI)
    fig.patch.set_alpha(0)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 100); ax.set_ylim(0, 110); ax.axis("off")
    ax.add_patch(FancyBboxPatch((2, 2), 96, 106, boxstyle="round,pad=0,rounding_size=5", fc="#0E1C17", ec=ESM, lw=2))
    ax.add_patch(FancyBboxPatch((2, 96), 96, 12, boxstyle="round,pad=0,rounding_size=5", fc=PINO, ec="none"))
    ax.text(7, 102, "Coach IA · Motor: Ollama (vitaband-coach)", color=BLANCO, fontsize=8.5, fontweight="bold", va="center")
    ax.add_patch(FancyBboxPatch((38, 80), 59, 11, boxstyle="round,pad=0,rounding_size=4", fc="#1E3A31", ec="none"))
    ax.text(42, 85.5, "¿Estoy recuperado para entrenar hoy?", color=BLANCO, fontsize=7.8, va="center")
    ax.add_patch(FancyBboxPatch((5, 38), 86, 38, boxstyle="round,pad=0,rounding_size=4", fc=CARD, ec=BORDE, lw=1))
    lineas = ["Tu batería está al 62 %: pulso en reposo +4 y", "RMSSD algo bajo. Hoy rinde mejor un rodaje suave.",
              "Te propongo 40 min en Zona 2, a ritmo cómodo.", "", "Tras «Mucha pantalla», tu recuperación del día",
              "siguiente baja un 18 %."]
    for i, l in enumerate(lineas):
        ax.text(9, 71 - i * 5.3, l, color="#E2E8F0", fontsize=7.6, va="center")
    ax.add_patch(FancyBboxPatch((9, 21), 62, 10, boxstyle="round,pad=0,rounding_size=4", fc=ESM, ec="none"))
    ax.text(40, 26, "✓ Añadido al plan de hoy", color="#06231A", fontsize=9, fontweight="bold", ha="center", va="center")
    for i, h in enumerate(["Dormí mal", "Café tarde", "Mucha pantalla", "Buena hidratación"]):
        x0 = 6 + [0, 21, 43, 71][i] if False else [6, 27, 48, 74][i]
        w = [19, 19, 24, 21][i]
        ax.add_patch(FancyBboxPatch((x0, 8), w, 8, boxstyle="round,pad=0,rounding_size=4", fc="none", ec=ORO, lw=1))
        ax.text(x0 + w / 2, 12, h, color=ORO, fontsize=5.8, ha="center", va="center")
    p = os.path.join(IMG, "g4_coach.png"); fig.savefig(p, transparent=True, dpi=DPI); plt.close(fig); return p


# ====================== PPTX: utilidades ======================
prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
BLANK = prs.slide_layouts[6]


def nueva():
    s = prs.slides.add_slide(BLANK)
    f = s.background.fill
    f.gradient()
    f.gradient_angle = 90
    f.gradient_stops[0].color.rgb = rgb("#0B1713"); f.gradient_stops[0].position = 0
    f.gradient_stops[1].color.rgb = rgb("#132A23"); f.gradient_stops[1].position = 1
    s._anim = []
    return s


def texto(cont, x, y, w, h, t, size=16, color=BLANCO, bold=False, align="l", anchor="t", italic=False):
    tb = cont.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = {"t": MSO_ANCHOR.TOP, "m": MSO_ANCHOR.MIDDLE, "b": MSO_ANCHOR.BOTTOM}[anchor]
    lineas = t if isinstance(t, list) else [t]
    for i, l in enumerate(lineas):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = {"l": PP_ALIGN.LEFT, "c": PP_ALIGN.CENTER, "r": PP_ALIGN.RIGHT}[align]
        r = p.add_run(); r.text = l
        r.font.size = Pt(size); r.font.bold = bold; r.font.italic = italic; r.font.name = FUENTE; r.font.color.rgb = rgb(color)
    return tb


def rect(cont, x, y, w, h, fill=CARD, borde=BORDE, radio=0.08, forma=None, lw=1.0):
    sh = cont.shapes.add_shape(forma or MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    if forma is None:
        sh.adjustments[0] = radio
    if fill:
        sh.fill.solid(); sh.fill.fore_color.rgb = rgb(fill)
    else:
        sh.fill.background()
    if borde:
        sh.line.color.rgb = rgb(borde); sh.line.width = Pt(lw)
    else:
        sh.line.fill.background()
    sh.shadow.inherit = False
    return sh


def anim(slide, shape):
    slide._anim.append(shape.shape_id)


def tarjeta(slide, x, y, w, h, titulo=None, cuerpo=None, ts=15, cs=12, borde=BORDE, cifra=None, cs_cifra=40, icono=None, animar=True):
    g = slide.shapes.add_group_shape()
    rect(g, x, y, w, h, borde=borde)
    yy = y + 0.2
    if icono is not None:
        c = rect(g, x + 0.22, yy, 0.62, 0.62, fill="#0F3D2F", borde=ESM, forma=MSO_SHAPE.OVAL)
        ic = rect(g, x + 0.37, yy + 0.15, 0.32, 0.32, fill=ESM, borde=None, forma=icono)
        yy += 0.82
    if cifra:
        texto(g, x + 0.22, yy - 0.02, w - 0.44, 0.9, cifra, cs_cifra, ESM, True)
        yy += cs_cifra / 72 * 1.25
    if titulo:
        texto(g, x + 0.22, yy, w - 0.44, 0.5, titulo, ts, BLANCO, True)
        yy += ts / 72 * 1.55
    if cuerpo:
        texto(g, x + 0.22, yy, w - 0.44, h - (yy - y) - 0.1, cuerpo, cs, GRIS)
    if animar:
        anim(slide, g)
    return g


def titular(slide, kicker, titulo, sub=None):
    t1 = texto(slide, 0.6, 0.42, 12, 0.3, kicker.upper(), 12, ESM, True)
    t2 = texto(slide, 0.6, 0.72, 12.1, 0.9, titulo, 34, BLANCO, True)
    anim(slide, t1); anim(slide, t2)
    if sub:
        t3 = texto(slide, 0.6, 1.5, 11.5, 0.5, sub, 16, GRIS)
        anim(slide, t3)


def imagen(slide, ruta, x, y, w=None, h=None, animar=True):
    pic = slide.shapes.add_picture(ruta, Inches(x), Inches(y), Inches(w) if w else None, Inches(h) if h else None)
    if animar:
        anim(slide, pic)
    return pic


# ====================== Animación + transición OpenXML ======================
NS = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'


def inyectar(slide, transicion="fade"):
    sld = slide._element
    tr = ('<p:transition %s spd="med"><p:fade/></p:transition>' % NS) if transicion == "fade" else \
         ('<p:transition %s spd="med"><p:push dir="u"/></p:transition>' % NS)
    sld.append(parse_xml(tr))
    ids = slide._anim
    if not ids:
        return
    n = [4]

    def nid():
        n[0] += 1
        return n[0]
    efectos = ""
    for i, sp in enumerate(ids):
        tipo = "afterEffect" if i == 0 else "withEffect"
        delay = 0 if i == 0 else i * 300
        efectos += (
            f'<p:par><p:cTn id="{nid()}" presetID="10" presetClass="entr" presetSubtype="0" fill="hold" nodeType="{tipo}">'
            f'<p:stCondLst><p:cond delay="{delay}"/></p:stCondLst><p:childTnLst>'
            f'<p:set><p:cBhvr><p:cTn id="{nid()}" dur="1" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst></p:cTn>'
            f'<p:tgtEl><p:spTgt spid="{sp}"/></p:tgtEl><p:attrNameLst><p:attrName>style.visibility</p:attrName></p:attrNameLst></p:cBhvr>'
            f'<p:to><p:strVal val="visible"/></p:to></p:set>'
            f'<p:animEffect transition="in" filter="fade"><p:cBhvr><p:cTn id="{nid()}" dur="600"/>'
            f'<p:tgtEl><p:spTgt spid="{sp}"/></p:tgtEl></p:cBhvr></p:animEffect></p:childTnLst></p:cTn></p:par>')
    xml = (f'<p:timing {NS}><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>'
           f'<p:seq concurrent="1" nextAc="seek"><p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>'
           f'<p:par><p:cTn id="3" fill="hold"><p:stCondLst><p:cond delay="indefinite"/><p:cond evt="onBegin" delay="0"><p:tn val="2"/></p:cond></p:stCondLst>'
           f'<p:childTnLst><p:par><p:cTn id="4" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>{efectos}'
           f'</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn>'
           f'<p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst>'
           f'<p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst></p:seq>'
           f'</p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>')
    sld.append(parse_xml(xml))


# ====================== Contenido ======================
g1, g2, g3, g4 = grafico_ecg(), grafico_calor_tsb(), grafico_poincare_trimmer(), grafico_coach()
SLIDES = []

# --- 1 Portada ---
s = nueva()
b = rect(s, 0.6, 1.1, 3.9, 0.42, fill="#0F3D2F", borde=ESM, radio=0.5)
tb = texto(s, 0.6, 1.1, 3.9, 0.42, "EDICIÓN ESCRITORIO  •  ECG 100 HZ", 11.5, ESM2, True, "c", "m")
anim(s, b); anim(s, tb)
anim(s, texto(s, 0.6, 1.75, 12, 1.3, "VITABAND", 80, BLANCO, True))
anim(s, texto(s, 0.6, 3.05, 9.6, 1.1, "Tu corazón a 100 Hz. Precisión clínica, IA privada y rendimiento real en tu escritorio", 22, "#CFE8DD"))
imagen(s, g1, 0, 4.55, w=13.333)
anim(s, texto(s, 0.6, 6.95, 8, 0.3, "Desarrollado por Grupo Athenea", 12, GRIS))
SLIDES.append((s, "fade"))

# --- 2 Problema vs revolución ---
s = nueva()
titular(s, "El problema", "Los relojes adivinan. VitaBand mide.")
tarjeta(s, 0.6, 1.9, 5.9, 4.7, "Relojes convencionales", None, 22, borde="#3A4B45")
for i, (a, b2) in enumerate([("Estimación óptica", "con retraso"), ("Datos sueltos", "sin contexto"), ("Nube de pago", "tus datos fuera")]):
    c = rect(s, 0.95, 3.0 + i * 1.15, 5.2, 0.95, fill="#1A2420", borde="#33423C")
    anim(s, c)
    anim(s, texto(s, 1.2, 3.1 + i * 1.15, 4.7, 0.4, a, 19, "#CBD5E1", True))
    anim(s, texto(s, 1.2, 3.55 + i * 1.15, 4.7, 0.4, b2, 14, "#7C8B85"))
tarjeta(s, 6.85, 1.9, 5.9, 4.7, "VitaBand + Banda Pectoral ECG", None, 22, borde=ESM)
anim(s, texto(s, 7.2, 2.95, 5.2, 1.1, "100", 66, ESM, True))
anim(s, texto(s, 7.2, 4.05, 5.2, 0.4, "muestras por segundo", 17, BLANCO, True))
for i, t in enumerate(["Latido a latido, real", "Control total en tu PC"]):
    c = rect(s, 7.2, 4.75 + i * 0.85, 5.2, 0.65, fill="#0F3D2F", borde=ESM)
    anim(s, c); anim(s, texto(s, 7.45, 4.75 + i * 0.85, 4.8, 0.65, t, 17, BLANCO, True, "l", "m"))
SLIDES.append((s, "fade"))

# --- 3 Perfiles ---
s = nueva()
titular(s, "Para quién", "4 perfiles, 1 ecosistema")
perf = [("Deportistas", "Zonas exactas y recuperación medida", MSO_SHAPE.LIGHTNING_BOLT),
        ("Oficina", "Control de estrés sin dejar el trabajo", MSO_SHAPE.WAVE),
        ("Entrenadores", "Gestión multi-atleta en una tabla", MSO_SHAPE.STAR_5_POINT),
        ("Médicos", "Informes PDF y trazados ECG limpios", MSO_SHAPE.MATH_PLUS)]
for i, (t, c, ic) in enumerate(perf):
    tarjeta(s, 0.6 + i * 3.09, 2.1, 2.9, 4.2, t, c, 24, 18, icono=ic)
SLIDES.append((s, "fade"))

# --- 4 Puesta en marcha ---
s = nueva()
titular(s, "Puesta en marcha", "Tres pasos y estás midiendo")
pasos = [("1", "Perfil fisiológico", "Calorías Keytel y zonas Z1–Z5 a tu medida"),
         ("2", "Banda o Demo", "Simulador: Reposo, Esfuerzo Z3, Estrés"),
         ("3", "Sync móvil", "Importa sesiones con escudo anti-duplicados")]
for i, (n, t, c) in enumerate(pasos):
    x = 0.6 + i * 4.2
    tarjeta(s, x, 2.1, 3.7, 4.0, t, c, 24, 18, cifra=n, cs_cifra=64)
    if i < 2:
        fl = rect(s, x + 3.78, 3.75, 0.36, 0.5, fill=ESM, borde=None, forma=MSO_SHAPE.RIGHT_ARROW)
        anim(s, fl)
SLIDES.append((s, "push"))

# --- 5 Tiempo real ---
s = nueva()
titular(s, "Tiempo real", "Entrena y trabaja con ventaja")
tr = [("ECG a 100 Hz", "Tu latido dibujado en directo"), ("Pitido de latido", "Siente el ritmo sin mirar"),
      ("Modo Fantasma", "Compite contra tu mejor sesión"), ("Susurrador en Vivo", "Avisa si te sales de zona"),
      ("Modo Overlay", "Mini-ventana sobre otras apps"), ("Coherencia Cardíaca", "Respiración guiada anti-estrés")]
for i, (t, c) in enumerate(tr):
    tarjeta(s, 0.6 + (i % 3) * 4.2, 1.95 + (i // 3) * 2.45, 3.9, 2.2, t, c, 24, 18)
SLIDES.append((s, "fade"))

# --- 6 Historial ---
s = nueva()
titular(s, "Historial periódico", "Domina tu fatiga y tu forma")
imagen(s, g2, 0.6, 1.85, w=8.4)
tarjeta(s, 9.35, 1.95, 3.4, 1.6, "Verde = rendir", "Listo para el máximo", 22, 16, borde=ESM)
tarjeta(s, 9.35, 3.75, 3.4, 1.6, "Ámbar = recuperar", "Toca descansar hoy", 22, 16, borde=AMB)
tarjeta(s, 9.35, 5.55, 3.4, 1.35, "TRIMP semanal", "Tu carga, en un número", 22, 16)
SLIDES.append((s, "fade"))

# --- 7 Laboratorio ---
s = nueva()
titular(s, "Laboratorio ECG y actividades", "Cada sesión, al detalle")
imagen(s, g3, 0.6, 1.85, w=7.6)
chips = ["Recorte de calentamiento", "Zoom latido a latido", "Detección de cortes de señal", "Recuperación HRR-60",
         "Desacoplamiento cardíaco", "Esfuerzo percibido RPE 1–10", "Sesiones parciales del móvil"]
for i, t in enumerate(chips):
    c = rect(s, 8.55, 1.95 + i * 0.7, 4.2, 0.58, fill=CARD, borde=BORDE, radio=0.4)
    anim(s, c)
    anim(s, texto(s, 8.85, 1.95 + i * 0.7, 3.8, 0.58, t, 15, BLANCO, True, "l", "m"))
SLIDES.append((s, "fade"))

# --- 8 Exportación ---
s = nueva()
titular(s, "Exportación", "Listo para compartir en 1 clic")
ex = [("PDF", "Informe clínico", "Para tu médico o entrenador"), ("PNG", "Tarjeta resumen", "Lista para redes o WhatsApp"),
      ("CSV", "Tablas de datos", "Ábrelas en Excel"), ("TCX", "Entrenamiento", "Sube a Strava o Garmin")]
for i, (f, t, c) in enumerate(ex):
    tarjeta(s, 0.6 + i * 3.09, 2.1, 2.9, 4.0, t, c, 22, 16, cifra=f, cs_cifra=60)
anim(s, texto(s, 0.6, 6.5, 12, 0.4, "Además: copia de seguridad .zip y anonimización de datos personales.", 14, GRIS))
SLIDES.append((s, "fade"))

# --- 9 Planificación ---
s = nueva()
titular(s, "Planificación y Modo Entrenador", "Diseña. Lanza. Supervisa.")
bl = [("Workout Builder", "Bloques, minutos, zonas y repeticiones"), ("Iniciar ahora", "Salta a Tiempo real con el objetivo cargado"),
      ("Modo Entrenador", "Varios deportistas en una sola tabla")]
for i, (t, c) in enumerate(bl):
    tarjeta(s, 0.6 + i * 4.2, 2.0, 3.9, 2.3, t, c, 24, 17)
bloques = [("Calentar", "10 min · Z1", "#3B7F6A", 2.0), ("Series", "5 × 3 min · Z4", AMB, 4.4), ("Rodaje", "20 min · Z2", ESM, 3.6),
           ("Enfriar", "5 min · Z1", "#3B7F6A", 1.8)]
x = 0.6
tot = sum(b[3] for b in bloques)
for t, d, col, w in bloques:
    w2 = w / tot * 12.15
    r = rect(s, x, 4.75, w2 - 0.08, 1.7, fill=col, borde=None, radio=0.12)
    anim(s, r)
    anim(s, texto(s, x + 0.15, 4.95, w2 - 0.4, 0.5, t, 17, "#06231A", True))
    anim(s, texto(s, x + 0.15, 5.5, w2 - 0.4, 0.5, d, 15, "#06231A"))
    x += w2
SLIDES.append((s, "push"))

# --- 10 Coach IA ---
s = nueva()
titular(s, "El gran diferenciador", "Coach IA local. No es ChatGPT.")
filas = [("", "VitaBand", "ChatGPT"), ("Funciona", "100 % offline (Ollama)", "Requiere internet"), ("Cuotas", "0 €", "Suscripción"),
         ("Privacidad", "Médica total", "Datos en la nube"), ("Tus datos", "Lee latidos y fatiga", "No los conoce"),
         ("Hábitos", "1 clic", "—"), ("Informe médico", "Resumen en 1 clic", "—")]
g = s.shapes.add_group_shape()
rect(g, 0.6, 1.9, 7.2, 5.0)
for i, (a, b2, c) in enumerate(filas):
    yy = 2.05 + i * 0.68
    if i == 0:
        texto(g, 3.1, yy, 2.4, 0.4, b2, 15, ESM, True); texto(g, 5.6, yy, 2.1, 0.4, c, 15, GRIS, True)
        continue
    if i % 2 == 0:
        rect(g, 0.75, yy - 0.06, 6.9, 0.58, fill="#1B352D", borde=None, radio=0.2)
    texto(g, 0.95, yy, 2.1, 0.45, a, 14, "#CBD5E1", True)
    texto(g, 3.1, yy, 2.5, 0.45, b2, 14, ESM2, True)
    texto(g, 5.6, yy, 2.1, 0.45, c, 14, "#7C8B85")
anim(s, g)
imagen(s, g4, 8.15, 1.8, w=4.75)
SLIDES.append((s, "fade"))

# --- 11 Cierre ---
s = nueva()
titular(s, "VitaBand", "Domina cada latido")
cifras = [("100 Hz", "Precisión ECG"), ("100 %", "Privacidad local"), ("6", "Módulos clínicos y deportivos"), ("0 €", "Suscripciones")]
for i, (c, t) in enumerate(cifras):
    tarjeta(s, 0.6 + i * 3.09, 1.95, 2.9, 2.2, t, None, 15, cifra=c, cs_cifra=46)
anim(s, texto(s, 0.6, 4.8, 12.1, 1.4, "Deja de adivinar lo que siente tu corazón.", 40, BLANCO, True, "c"))
anim(s, texto(s, 0.6, 5.7, 12.1, 1.0, "Empieza a verlo.", 40, ESM, True, "c"))
anim(s, texto(s, 0.6, 6.9, 12.1, 0.3, "Grupo Athenea  ·  VitaBand App", 12, GRIS, False, "c"))
SLIDES.append((s, "fade"))

for sl, tr in SLIDES:
    inyectar(sl, tr)
prs.core_properties.title = "VitaBand — Presentación comercial"
prs.core_properties.author = "Grupo Athenea"
prs.save(OUT)
print(OUT, len(prs.slides))
