"""Portada de lujo (emblema Athenea, AccessCard con 2FA) y animaciones globales sin fugas de efectos ni timers."""
import os
import tempfile
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QGraphicsEffect, QLabel, QProgressBar, QTabWidget, QWidget

from services.repositorio_cuentas import RepositorioCuentas
from services.repositorio_historial import RepositorioHistorial
from services.servicio_auth import ServicioAuth
from ui import animaciones_vitaband as an
from ui.login_dialog import LoginDialog, PAG_LOGIN, PAG_MFA, PAG_REGISTRO
from ui.main_window import MainWindow
from ui.portada_auth_widget import RUTA_LOGO, PortadaAuthWidget, _crear_emblema_circular
from viewmodel.vitaband_vm import VitaBandViewModel

_app = QApplication.instance() or QApplication([])


def _esperar(anim, ms=1500):
    import time
    t = time.time()
    while anim is not None and anim.state() == anim.State.Running and time.time() - t < ms / 1000:
        _app.processEvents()
    _app.processEvents()


def _textos(w):
    return [l.text() for l in w.findChildren(QLabel)]


def _sin_efectos(w):
    return all(x.graphicsEffect() is None for x in w.findChildren(QWidget))


class TestPortada(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.auth = ServicioAuth(RepositorioCuentas(os.path.join(d, "c.db")))
        self.dlg = LoginDialog(self.auth)

    def tearDown(self):
        self.dlg.close()

    def test_emblema_real_y_textos_de_la_portada(self):
        self.assertTrue(os.path.exists(RUTA_LOGO) and RUTA_LOGO.endswith("assets/logo_athenea.png"))
        pm = _crear_emblema_circular(RUTA_LOGO, 240)
        self.assertEqual((pm.width(), pm.height()), (240, 240))
        self.assertFalse(self.dlg.portada.lbl_emblema.pixmap().isNull())
        self.assertGreater(pm.toImage().pixelColor(120, 120).alpha(), 0)
        t = " | ".join(_textos(self.dlg))
        for k in ("VitaBand App", "BANDA PECTORAL ECG · TELEMETRÍA BIOMÉTRICA AVANZADA",
                  "Domina cada latido. Convierte tu fisiología en rendimiento real.", "Acceso a tu cuenta"):
            self.assertIn(k, t)
        self.assertIn("54px", self.dlg.portada.lbl_titulo.styleSheet())
        self.assertIn("#10B981", self.dlg.portada.access_card.styleSheet())
        self.assertEqual(self.dlg.portada.access_card.objectName(), "AccessCard")
        self.assertEqual(self.dlg.btn_entrar.text(), "INICIAR SESIÓN")
        self.assertEqual(self.dlg.chk_recordar.text(), "Recordar sesión")
        self.assertEqual(self.dlg.btn_olvide.text(), "Olvidé mi contraseña?")
        self.assertEqual(self.dlg.btn_ir_registro.text(), "Crear cuenta nueva")
        self.assertEqual(self.dlg.portada.tab_header.btn_tab_login.text(), "Iniciar Sesión")
        self.assertEqual(self.dlg.portada.tab_header.btn_tab_signup.text(), "Crear Cuenta")

    def test_sello_grupo_athenea_y_formularios_reales_dentro_de_la_tarjeta(self):
        self.assertIsNotNone(self.dlg.portada.sello_athenea)
        card = self.dlg.portada.access_card
        for w in (self.dlg.login_email, self.dlg.login_password, self.dlg.reg_nombre, self.dlg.mfa_codigo, self.dlg.mfa_qr):
            self.assertTrue(card.isAncestorOf(w))
        self.assertIs(self.dlg.portada.stack_formularios, self.dlg._paginas)

    def test_ventana_maximizada_y_timer_solo_mientras_se_ve(self):
        self.assertTrue(self.dlg.windowState() & Qt.WindowState.WindowMaximized)
        t = self.dlg.portada._timer
        self.assertFalse(t.isActive())
        self.dlg.show()
        _app.processEvents()
        self.assertTrue(t.isActive())
        self.dlg.hide()
        self.assertFalse(t.isActive())
        self.assertTrue(_sin_efectos(self.dlg))

    def test_coreografia_de_entrada_limpia_efectos(self):
        self.dlg.show()
        _app.processEvents()
        grupo = self.dlg.portada._anim_group
        self.assertIsNotNone(grupo)
        grupo.setCurrentTime(grupo.totalDuration())
        _app.processEvents()
        self.assertTrue(_sin_efectos(self.dlg))
        self.dlg.hide()
        self.assertTrue(_sin_efectos(self.dlg))

    def test_conmutacion_login_registro_2fa_sin_fugas(self):
        self.dlg.show()
        _app.processEvents()
        p = self.dlg.portada
        p.tab_header.btn_tab_signup.click()
        self.assertEqual(self.dlg._paginas.currentIndex(), PAG_REGISTRO)
        _esperar(p._form_anim)
        self.assertTrue(_sin_efectos(self.dlg._paginas))
        self.dlg.btn_volver_login.click()
        self.assertEqual(self.dlg._paginas.currentIndex(), PAG_LOGIN)
        self.assertEqual(p.tab_header._active_idx, 0)
        self.dlg.btn_ir_registro.click()
        self.assertEqual(p.tab_header._active_idx, 1)
        self.dlg._ir_a(PAG_MFA)                                 # el paso 2FA no muestra el selector
        self.assertFalse(p.tab_header.isVisible())
        _esperar(p._form_anim)
        self.assertTrue(_sin_efectos(self.dlg._paginas))
        self.dlg._ir_a(PAG_LOGIN)
        self.assertTrue(p.tab_header.isVisible())
        self.dlg.hide()
        self.assertTrue(_sin_efectos(self.dlg))
        self.assertFalse(p._timer.isActive())

    def test_olvide_mi_contrasena_informa_sin_romper(self):
        self.dlg.btn_olvide.click()
        self.assertIn("contraseña", self.dlg.login_error.text())

    def test_widget_autonomo_con_formularios_propios(self):
        w = PortadaAuthWidget()
        for n in ("txt_email", "txt_password", "chk_recordar", "btn_login", "btn_signup", "txt_reg_email"):
            self.assertTrue(hasattr(w, n))
        w.close()


class TestAnimaciones(unittest.TestCase):
    def test_fundido_retira_el_efecto_al_terminar_o_interrumpirse(self):
        w = QWidget()
        w.show()
        a = an.fundido(w, 40)
        self.assertIsInstance(w.graphicsEffect(), QGraphicsEffect)
        _esperar(a)
        self.assertIsNone(w.graphicsEffect())
        an.fundido(w, 5000)
        an.detener_fundido(w)
        self.assertIsNone(w.graphicsEffect())
        w.close()

    def test_transiciones_de_pestanas_globales_y_subpestanas(self):
        repo = RepositorioHistorial(os.path.join(tempfile.mkdtemp(), "t.db"), usuario_id=1)
        v = MainWindow(VitaBandViewModel(MagicMock(), repositorio=repo), "Ana")
        v.show()
        _app.processEvents()
        v.animador.habilitado = True
        tabs = [v.pestanas, *[t for t in v.findChildren(QTabWidget) if t is not v.pestanas]]
        self.assertTrue(all(t.property("_fundido") for t in tabs))
        v.pestanas.setCurrentIndex(1)
        pagina = v.pestanas.currentWidget()
        anim = getattr(pagina, "_vb_fade", None)
        if anim is not None:
            _esperar(anim)
        # Páginas con gráficas (Historial): nunca llevan QGraphicsEffect (evita cierres nativos al hacer scroll)
        self.assertIsNone(pagina.graphicsEffect())
        v.close()

    def test_kpi_interpola_conservando_unidades(self):
        w = QWidget()
        a = an.AnimadorVitaBand(w, habilitado=True)
        lbl = QLabel("FC: 60 BPM", w)
        w.show()
        a.texto_kpi(lbl, "FC: 100 BPM", ms=120)
        _app.processEvents()
        anim = a._kpis[lbl]
        anim.setCurrentTime(60)
        self.assertTrue(lbl.text().startswith("FC: ") and lbl.text().endswith(" BPM"))
        self.assertNotIn(lbl.text(), ("FC: 60 BPM", "FC: 100 BPM"))
        _esperar(anim)
        self.assertEqual(lbl.text(), "FC: 100 BPM")
        a.texto_kpi(lbl, "FC: N/D")                                       # sin número: sin interpolar
        self.assertEqual(lbl.text(), "FC: N/D")
        w.close()

    def test_pulso_hover_y_limpieza_en_cierre(self):
        repo = RepositorioHistorial(os.path.join(tempfile.mkdtemp(), "t.db"), usuario_id=1)
        v = MainWindow(VitaBandViewModel(MagicMock(), repositorio=repo), "Ana")
        v.show()
        v.animador.habilitado = True
        punto = v.lbl_punto_conexion
        v.animador.pulso(punto, True, "#94A3B8", "#34D399", lambda c: f"color: {c};")
        anim = v.animador._pulsos[punto]
        self.assertEqual(anim.state(), anim.State.Running)
        self.assertEqual(anim.loopCount(), -1)
        v.animador.hover_tarjeta(v.tarjeta_bpm)
        base = v.tarjeta_bpm.styleSheet()
        v.hide()                                                          # hideEvent detiene todo
        self.assertEqual(anim.state(), anim.State.Stopped)
        self.assertEqual(v.animador._pulsos, {})
        self.assertEqual(v.tarjeta_bpm.styleSheet(), base)
        v.close()

    def test_barra_y_panel_colapsable_sin_estado_residual(self):
        w = QWidget()
        w.show()
        b = QProgressBar(w)
        an.suavizar_barra(b, 80)
        self.assertEqual(b.value(), 80)                                   # offscreen: inmediato
        p = QWidget(w)
        an.desplegar(p, True)
        self.assertTrue(p.isVisible())
        an.desplegar(p, False)
        self.assertFalse(p.isVisible())
        self.assertEqual(p.maximumHeight(), 16777215)
        w.close()

    def test_animaciones_apagadas_en_pruebas_sin_pantalla(self):
        self.assertFalse(an.animaciones_activas())


if __name__ == "__main__":
    unittest.main()
