#!/usr/bin/env bash
# ============================================================
#  Noviark - crea la app y el instalador .dmg para macOS
#  Resultado: dist/Noviark.app  y  dist/Noviark-macOS-<arquitectura>.dmg
#  Requisitos: Python 3.10+ de python.org o Homebrew (brew install python python-tk)
#  Nota: sin firma de Apple, la primera vez abre con clic derecho → Abrir (o
#  Ajustes del Sistema → Privacidad y seguridad → «Abrir igualmente»).
# ============================================================
set -euo pipefail
cd "$(dirname "$0")/../.."
ARCH=$(uname -m)
echo "[1/4] Icono .icns…"
ICONSET=build/Noviark.iconset; rm -rf "$ICONSET"; mkdir -p "$ICONSET"
for s in 16 32 64 128 256; do
  sips -z $s $s static/noviq_icon.png --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  d=$((s*2)); [ $d -le 512 ] && sips -z $d $d static/noviq_icon.png --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null || true
done
iconutil -c icns "$ICONSET" -o packaging/macos/Noviark.icns || echo "(sin .icns, se usará el icono por defecto)"
echo "[2/4] Entorno de compilación…"
[ -x .build-venv/bin/python ] || python3 -m venv .build-venv
.build-venv/bin/python -m pip install -q --upgrade pip
.build-venv/bin/python -m pip install -q -r packaging/requirements-build.txt
echo "[3/4] Compilando Noviark.app con PyInstaller…"
.build-venv/bin/python -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging/noviq.spec
codesign --force --deep -s - dist/Noviark.app 2>/dev/null || true   # firma local (ad-hoc)
echo "[4/4] Instalador .dmg…"
STAGE=build/dmg; rm -rf "$STAGE"; mkdir -p "$STAGE"
cp -R dist/Noviark.app "$STAGE/"
ln -s /Applications "$STAGE/Aplicaciones"
hdiutil create -volname "Noviark" -srcfolder "$STAGE" -ov -format UDZO "dist/Noviark-macOS-${ARCH}.dmg"
echo; echo "LISTO: dist/Noviark-macOS-${ARCH}.dmg  (arrastra Noviark a Aplicaciones)"
