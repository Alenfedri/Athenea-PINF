import os
import tempfile
import time

from services import datos_ejemplo
from services.repositorio_historial import RepositorioHistorial


def _repo():
    return RepositorioHistorial(os.path.join(tempfile.mkdtemp(), "t.db"), usuario_id=1)


def test_datos_ejemplo_llenan_todas_las_vistas_y_son_idempotentes():
    repo, ahora = _repo(), int(time.time())
    r1 = datos_ejemplo.cargar(repo, ahora)
    assert r1["actividades"] >= 30 and r1["mediciones"] > 10000
    assert len(repo.actividades_rango(ahora - 90 * 86400, ahora)) == r1["actividades"]
    assert repo.rr_rango(ahora - 86400, ahora) and repo.hrv_rango(ahora - 30 * 86400, ahora)
    assert repo.contar_segundos_ecg() > 0 and repo.perfil() is not None and repo.disciplinas()
    assert datos_ejemplo.cargar(repo, ahora) == {"actividades": 0, "mediciones": 0}


def test_datos_ejemplo_no_pisan_un_perfil_existente():
    repo = _repo()
    repo.guardar_perfil(50, "Mujer", 60.0, 200)
    datos_ejemplo.cargar(repo)
    assert repo.perfil()["edad"] == 50


def test_vm_carga_ejemplo_y_boton_visible():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QApplication, QMessageBox
    from ui.main_window import MainWindow
    from viewmodel.vitaband_vm import VitaBandViewModel
    _app = QApplication.instance() or QApplication([])
    repo = _repo()
    vm = VitaBandViewModel(MagicMock(), repositorio=repo)
    avisos = []
    vm.historial_actualizado.connect(lambda: avisos.append(1))
    v = MainWindow(vm, "Ana")
    assert v.btn_ejemplo.text() == "Datos de ejemplo"
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    v.btn_ejemplo.click()
    now = int(time.time())
    assert len(repo.actividades_rango(now - 90 * 86400, now)) >= 30 and avisos
    v.close()


def test_demo_no_se_bloquea_sin_banda_real_y_se_reinicia():
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QApplication
    from domain.ui_state import ConexionEstado
    from viewmodel.vitaband_vm import VitaBandViewModel
    _app = QApplication.instance() or QApplication([])
    vm = VitaBandViewModel(MagicMock(), repositorio=_repo())
    assert vm.iniciar_demo("Reposo") and vm.demo_active and not vm.ble_connected
    assert vm.iniciar_demo("Esfuerzo Z3") and vm.demo_active          # reinicio limpio, sin aviso
    vm.detener_demo()
    assert not vm.demo_active and vm._timer_demo is None
    vm._emitir_nuevo_estado(conexionEstado=ConexionEstado.ERROR_COMUNICACION)   # intento de conexión fallido
    assert vm.iniciar_demo("Estrés Escritorio") and vm.demo_active
    vm.detener_demo()
    vm._emitir_nuevo_estado(conexionEstado=ConexionEstado.CONECTADO)           # banda real conectada
    assert vm.ble_connected and not vm.iniciar_demo("Reposo")


def test_animaciones_numero_toast_y_efecto_retirado():
    from PySide6.QtWidgets import QApplication, QLabel, QWidget
    from ui import animations
    _app = QApplication.instance() or QApplication([])
    w, lbl = QWidget(), QLabel()
    animations.animate_number(lbl, 0, 72.4, " lpm", 1)
    assert lbl.text() == "72.4 lpm"
    animations.fade_slide_in(w)
    assert w.graphicsEffect() is None
    w.resize(300, 200)
    w.show()
    t = animations.show_toast(w, "ok")
    assert t is not None and t.isVisible()
    w.close()
    w.deleteLater()
    _app.processEvents()


def test_demo_sigue_vivo_con_pip_y_restaurar():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QApplication
    from ui.main_window import MainWindow
    from viewmodel.vitaband_vm import VitaBandViewModel
    app = QApplication.instance() or QApplication([])
    vm = VitaBandViewModel(MagicMock(), repositorio=_repo())
    v = MainWindow(vm, "Ana")
    v.show()
    vm.iniciar_demo("Reposo") if vm.iniciar_demo.__code__.co_argcount > 1 else vm.iniciar_demo()
    for _ in range(40):
        app.processEvents(); time.sleep(0.02)
    v._abrir_pip()
    app.processEvents()
    assert vm.demo_active and v.pip.isVisible()
    for _ in range(40):
        app.processEvents(); time.sleep(0.02)
    assert vm.demo_active
    assert v.pip.lbl_bpm.text() != "--" and "Sin zona" not in v.pip.zona_texto
    v.pip.btn_restaurar.click()
    app.processEvents()
    assert vm.demo_active and not v.pip.isVisible()
    vm.detener_demo()
    v.close()
