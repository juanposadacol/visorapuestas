# -*- mode: python ; coding: utf-8 -*-
"""Receta de PyInstaller para generar VisorUnder.exe (requisito 2, fase 12).

Se genera con:
    pyinstaller visorunder.spec --noconfirm

Puntos delicados que resuelve este fichero:

* RapidOCR guarda sus modelos .onnx DENTRO del paquete: hay que copiarlos al
  ejecutable o el OCR fallara al arrancar en un equipo limpio.
* onnxruntime carga librerias nativas que PyInstaller no detecta solo.
* Se excluyen modulos pesados de Qt que la aplicacion no usa, para que el
  ejecutable no crezca sin motivo.
"""

from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = []
binaries = []
hiddenimports = ["visorunder"]

# Modelos y configuracion de RapidOCR (imprescindible para que lea sin internet).
for package in ("rapidocr_onnxruntime", "rapidocr", "onnxruntime"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    except Exception:
        continue
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

hiddenimports += collect_submodules("visorunder")

a = Analysis(
    ["src/visorunder/__main__.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
        "PySide6.QtMultimedia", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtCharts",
        "matplotlib", "tkinter", "scipy", "pandas",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VisorUnder",
    debug=False,
    strip=False,
    upx=False,
    console=False,          # sin ventana negra de consola
    disable_windowed_traceback=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="VisorUnder",
)
