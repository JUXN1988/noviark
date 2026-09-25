# -*- coding: utf-8 -*-
"""Punto de entrada del programa (Windows .exe, macOS .app, Linux).
Noviark se abre en su PROPIA VENTANA de escritorio (no en el navegador):
  1. Ventana nativa con pywebview (Windows: WebView2 de Edge · macOS: WebKit · Linux: GTK/Qt si están).
  2. Si no se puede, una ventana de aplicación sin barras de navegador (Edge/Chrome/Chromium en modo --app).
  3. Último recurso: el navegador predeterminado.
Al cerrar la ventana, Noviark se apaga. Con --bandeja se queda en segundo plano (icono junto al reloj) para las
tareas programadas.
Opciones:  --bandeja  --no-browser  --stop  --version  --elegir-carpeta (uso interno)"""
import os
import sys


def _elegir_carpeta():
    import tkinter as tk
    from tkinter import filedialog
    r = tk.Tk()
    r.withdraw()
    r.attributes("-topmost", True)
    print(filedialog.askdirectory(title="Elige la carpeta raíz del proyecto") or "")


def _stop():
    import urllib.request
    from noviq.config import DATA_DIR
    try:
        tok = (DATA_DIR / ".token").read_text(encoding="utf-8").strip()
        req = urllib.request.Request("http://127.0.0.1:7860/api/apagar", data=b"{}", method="POST",
                                     headers={"X-Token": tok, "Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
        print("Noviark se apagó.")
    except Exception as e:
        print("Noviark no estaba abierto:", e)


def _log_si_no_hay_consola():
    if sys.stdout is None or sys.stderr is None:  # programa con ventana (sin consola): la salida va a un archivo
        from noviq.config import DATA_DIR
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        f = open(DATA_DIR / "noviq.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f


def _bandeja(url):
    """Icono en la bandeja del sistema. Si no se puede (p. ej. Linux sin soporte), devuelve False."""
    try:
        import pystray
        from PIL import Image
        from noviq.config import BASE_DIR
        import webbrowser
        img = Image.open(BASE_DIR / "static" / "noviq_icon.png")

        def abrir(icon=None, item=None):
            webbrowser.open(url)

        def apagar(icon, item):
            icon.stop()
            os._exit(0)
        icon = pystray.Icon("Noviark", img, "Noviark — agente de IA",
                            menu=pystray.Menu(pystray.MenuItem("Abrir Noviark", abrir, default=True),
                                              pystray.MenuItem("Apagar Noviark", apagar)))
        icon.run()  # bloquea (en macOS debe ser el hilo principal)
        return True
    except Exception as e:
        print("Sin icono en la bandeja:", e)
        return False


class ApiVentana:
    """Funciones que la página puede pedir a la ventana nativa (window.pywebview.api.*)."""
    def abrir_externo(self, url):
        import webbrowser
        webbrowser.open(url)
        return True


def ventana_nativa(url):
    try:
        import webview
    except Exception as e:
        print("pywebview no disponible:", e)
        return False
    try:
        from noviq.config import DATA_DIR
        try:
            webview.settings["ALLOW_DOWNLOADS"] = True
            webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        except Exception:
            pass
        webview.create_window("Noviark", url, width=1380, height=880, min_size=(900, 600), js_api=ApiVentana(),
                              text_select=True, background_color="#0a0f14")
        webview.start(private_mode=False, storage_path=str(DATA_DIR / "ventana"))  # bloquea hasta cerrar la ventana
        return True
    except Exception as e:
        print("No se pudo abrir la ventana nativa:", e)
        return False


def _buscar_navegador_app():
    import shutil
    cands = []
    if sys.platform == "win32":
        pf = [os.environ.get(k, "") for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
        for base in pf:
            cands += [os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                      os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")]
    elif sys.platform == "darwin":
        cands += ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                  "/Applications/Chromium.app/Contents/MacOS/Chromium"]
    else:
        cands += [shutil.which(n) or "" for n in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                                                   "microsoft-edge", "brave-browser")]
    return next((c for c in cands if c and os.path.exists(c)), None)


def ventana_app(url):
    """Ventana de aplicación sin barras de navegador (Edge/Chrome --app) con su propio perfil. Espera a que se cierre."""
    import subprocess
    exe = _buscar_navegador_app()
    if not exe:
        return False
    from noviq.config import DATA_DIR
    try:
        p = subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={DATA_DIR / 'ventana_app'}", "--no-first-run",
                              "--no-default-browser-check", "--window-size=1380,880", "--class=Noviark"])
        p.wait()
        return True
    except Exception as e:
        print("No se pudo abrir la ventana de aplicación:", e)
        return False


def main():
    args = sys.argv[1:]
    if "--elegir-carpeta" in args:
        return _elegir_carpeta()
    if "--version" in args:
        from noviq.config import VERSION
        return print("Noviark", VERSION)
    if "--stop" in args:
        return _stop()
    _log_si_no_hay_consola()
    import app as noviq_server
    en_segundo_plano = "--bandeja" in args or "--no-browser" in args
    url = noviq_server.main(abrir_navegador=False, bloquear=False, abrir_si_ocupado=not en_segundo_plano)
    if url is None:  # ya estaba abierto: se mostró su ventana y terminamos
        return
    if not en_segundo_plano:
        if ventana_nativa(url) or ventana_app(url):
            os._exit(0)  # se cerró la ventana: se apaga Noviark
        import webbrowser
        webbrowser.open(url)
    if "--sin-bandeja" in args or not _bandeja(url):
        import time
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()
