"""Salida limpia: el teardown de PySide6 con muchas ventanas sin cerrar puede dar un segfault intermitente
al finalizar el intérprete (también en versiones anteriores). Se sale con el código real de pytest."""
import os
import sys

_estado = {"code": 0}


def pytest_sessionfinish(session, exitstatus):
    _estado["code"] = int(exitstatus)


def pytest_unconfigure(config):
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_estado["code"])
