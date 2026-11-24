# -*- mode: python ; coding: utf-8 -*-
# Compilar:  pyinstaller --clean --noconfirm VitaBand.spec   ->  dist/VitaBand/VitaBand.exe  (Windows)
import importlib.util
from PyInstaller.utils.hooks import collect_all

datas = [("assets", "assets"), ("styles", "styles"), ("settings.json", ".")]
binaries, hiddenimports = [], []
for pkg in ("bleak", "matplotlib", "sounddevice", "onnxruntime", "faster_whisper", "piper"):
    if importlib.util.find_spec(pkg):                       # solo los paquetes realmente instalados
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h

a = Analysis(["main.py"], pathex=["."], binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             hookspath=[], runtime_hooks=[], excludes=["tkinter", "pkg_resources", "setuptools"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="VitaBand", debug=False, strip=False, upx=False,
          console=False, icon="assets/vitaband.ico")
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="VitaBand")
