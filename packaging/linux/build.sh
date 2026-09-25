#!/usr/bin/env bash
# ============================================================
#  Noviark - crea los paquetes para Ubuntu/Debian (y cualquier Linux)
#  Resultado: dist/noviark_4.2.0_amd64.deb  y  dist/Noviark-Linux-x86_64.tar.gz
#  Requisitos: python3 (3.10+), python3-venv, python3-tk, dpkg-deb
#     sudo apt install python3 python3-venv python3-tk dpkg
# ============================================================
set -euo pipefail
cd "$(dirname "$0")/../.."
VERSION=4.2.0
ARCH=$(dpkg --print-architecture 2>/dev/null || echo amd64)
echo "[1/4] Entorno de compilación…"
[ -x .build-venv/bin/python ] || python3 -m venv .build-venv
.build-venv/bin/python -m pip install -q --upgrade pip
.build-venv/bin/python -m pip install -q -r packaging/requirements-build.txt
echo "[2/4] Compilando con PyInstaller…"
.build-venv/bin/python -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging/noviq.spec
echo "[3/4] Paquete .deb…"
PKG=build/deb/noviark_${VERSION}_${ARCH}
rm -rf "$PKG"; mkdir -p "$PKG/DEBIAN" "$PKG/opt/noviark" "$PKG/usr/bin" "$PKG/usr/share/applications" "$PKG/usr/share/icons/hicolor/256x256/apps"
cp -r dist/Noviark/* "$PKG/opt/noviark/"
ln -sf /opt/noviark/Noviark "$PKG/usr/bin/noviark"
cp static/noviq_icon.png "$PKG/usr/share/icons/hicolor/256x256/apps/noviark.png"
cp packaging/linux/noviq.desktop "$PKG/usr/share/applications/noviark.desktop"
SIZE=$(du -sk "$PKG/opt" | cut -f1)
cat > "$PKG/DEBIAN/control" <<CTRL
Package: noviark
Version: ${VERSION}
Section: devel
Priority: optional
Architecture: ${ARCH}
Installed-Size: ${SIZE}
Depends: libc6, xdg-utils
Recommends: python3, python3-venv, git, gir1.2-ayatanaappindicator3-0.1
Maintainer: Noviark Labs <ventas@noviark.com>
Homepage: https://github.com/JUXN1988/noviark
Description: Noviark - agente de IA de escritorio para programar
 Crea, prueba y corrige programas con IA gratis (NVIDIA, Gemini, OpenRouter,
 Groq…) o con IA local (Ollama, LM Studio), con respaldo automático entre IAs.
CTRL
cat > "$PKG/DEBIAN/postinst" <<'POST'
#!/bin/sh
command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q /usr/share/icons/hicolor || true
exit 0
POST
chmod 755 "$PKG/DEBIAN/postinst"
dpkg-deb --build --root-owner-group "$PKG" "dist/noviark_${VERSION}_${ARCH}.deb"
cp "dist/noviark_${VERSION}_${ARCH}.deb" "dist/Noviark-Linux-${ARCH}.deb"   # nombre fijo para el enlace de descarga de la web
echo "[4/4] Versión portable (.tar.gz)…"
tar -C dist -czf "dist/Noviark-Linux-$(uname -m).tar.gz" Noviark
echo
echo "LISTO:"; ls -lh dist/*.deb dist/*.tar.gz
echo "Instalar:  sudo apt install ./dist/noviark_${VERSION}_${ARCH}.deb      Abrir: noviark (o desde el menú de aplicaciones)"
