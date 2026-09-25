# -*- mode: python ; coding: utf-8 -*-
# Receta de PyInstaller para Noviark (la usan los scripts de windows/, linux/ y macos/).
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent
ICON_WIN = str(ROOT / "static" / "noviq.ico")
ICON_MAC = str(ROOT / "packaging" / "macos" / "Noviark.icns")

hidden = collect_submodules("noviq") + ["app", "pystray", "PIL.Image", "tkinter", "tkinter.filedialog"]
if sys.platform == "win32":
    hidden += ["pystray._win32"]
elif sys.platform == "darwin":
    hidden += ["pystray._darwin"]
else:
    hidden += ["pystray._xorg", "pystray._appindicator", "pystray._gtk"]

a = Analysis(
    [str(ROOT / "noviq_app.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "static"), "static"), (str(ROOT / "LEEME.md"), "."), (str(ROOT / "LICENSE.md"), ".")],
    hiddenimports=hidden,
    excludes=["pytest", "IPython", "matplotlib", "numpy", "pandas"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Noviark",
    console=False,                      # sin ventana negra: Noviark vive en la bandeja del sistema
    icon=ICON_WIN if sys.platform == "win32" else (ICON_MAC if sys.platform == "darwin" and Path(ICON_MAC).exists() else None),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Noviark", upx=False)
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Noviark.app",
        icon=ICON_MAC if Path(ICON_MAC).exists() else None,
        bundle_identifier="com.noviarklabs.noviark",
        info_plist={"CFBundleShortVersionString": "4.2.0", "CFBundleVersion": "4.2.0", "NSHighResolutionCapable": True,
                    "LSUIElement": False, "CFBundleDisplayName": "Noviark"},
    )
