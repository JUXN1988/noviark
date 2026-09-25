# -*- coding: utf-8 -*-
"""Navegador de pruebas integrado (no hay que instalar nada).

Abre páginas web, juegos o el servidor del proyecto en Edge/Chrome INVISIBLE (headless) y habla con él por el
protocolo DevTools (CDP) con un cliente WebSocket mínimo propio. Así la IA prueba una web como lo haría un
desarrollador con las herramientas de desarrollo abiertas:

  • errores de JavaScript y excepciones con archivo:línea y el código de esa línea
  • archivos que no cargan (404, CDN caído, ruta mal escrita)
  • mensajes de la consola (console.log / warn / error)
  • captura de pantalla y detección de «pantalla en blanco» (el juego no dibuja nada)
  • acciones: teclas (flechas, espacio, WASD…), clics, arrastrar el mouse, rueda, escribir, JavaScript
  • comparar la imagen antes y después de cada acción (¿los controles hacen algo?)
"""
import base64
import io
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

from .config import IS_WINDOWS, NO_WINDOW


# ───────────── Buscar Edge / Chrome / Chromium ─────────────
def find_browser():
    env = os.environ.get("NOVIQ_NAVEGADOR")
    if env and os.path.exists(env):
        return env
    cands = []
    if IS_WINDOWS:
        for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
            base = os.environ.get(k, "")
            if base:
                cands += [os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                          os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"),
                          os.path.join(base, "BraveSoftware", "Brave-Browser", "Application", "brave.exe")]
    elif sys.platform == "darwin":
        cands += ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                  "/Applications/Chromium.app/Contents/MacOS/Chromium",
                  "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"]
    else:
        cands += [shutil.which(n) or "" for n in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                                                   "microsoft-edge", "microsoft-edge-stable", "brave-browser")]
        pw = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        if pw and os.path.isdir(pw):
            for d in sorted(Path(pw).glob("chromium-*"), reverse=True):
                cands += [str(d / "chrome-linux" / "chrome"), str(d / "chrome-linux64" / "chrome")]
    return next((c for c in cands if c and os.path.exists(c)), None)


def browser_name(path):
    p = (path or "").lower()
    return "Edge" if "edge" in p else "Brave" if "brave" in p else "Chrome" if "chrome" in p and "chromium" not in p else "Chromium"


# ───────────── Cliente WebSocket mínimo (RFC 6455) ─────────────
class WSError(Exception):
    pass


class WS:
    def __init__(self, url, timeout=15):
        u = urlparse(url)
        self.sock = socket.create_connection((u.hostname, u.port or 80), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        path = u.path + (("?" + u.query) if u.query else "")
        req = (f"GET {path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise WSError("el navegador cerró la conexión")
            buf += chunk
        head, self.buf = buf.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise WSError("el navegador rechazó la conexión: " + head[:120].decode("latin-1"))
        self.frag = b""

    def send(self, text):
        data = text.encode("utf-8")
        n = len(data)
        head = bytearray([0x81])
        if n < 126:
            head.append(0x80 | n)
        elif n < 65536:
            head.append(0x80 | 126)
            head += struct.pack(">H", n)
        else:
            head.append(0x80 | 127)
            head += struct.pack(">Q", n)
        mask = os.urandom(4)
        head += mask
        body = bytes(b ^ mask[i % 4] for i, b in enumerate(data)) if n < 4096 else _xor(data, mask)
        self.sock.sendall(bytes(head) + body)

    def _exact(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(max(65536, n - len(self.buf)))
            if not chunk:
                raise WSError("conexión cerrada")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self, timeout):
        """Devuelve un mensaje de texto o None si no llega nada en `timeout` segundos."""
        self.sock.settimeout(timeout)
        try:
            while True:
                b0, b1 = self._exact(2)
                fin, op = b0 & 0x80, b0 & 0x0F
                n = b1 & 0x7F
                if n == 126:
                    n = struct.unpack(">H", self._exact(2))[0]
                elif n == 127:
                    n = struct.unpack(">Q", self._exact(8))[0]
                mask = self._exact(4) if b1 & 0x80 else None
                data = self._exact(n)
                if mask:
                    data = _xor(data, mask)
                if op == 0x8:
                    raise WSError("conexión cerrada por el navegador")
                if op == 0x9:  # ping → pong
                    self.sock.sendall(bytes([0x8A, 0x80]) + os.urandom(4))
                    continue
                if op == 0xA:
                    continue
                self.frag += data
                if fin:
                    msg, self.frag = self.frag, b""
                    return msg.decode("utf-8", "replace")
        except socket.timeout:
            return None

    def close(self):
        try:
            self.sock.sendall(bytes([0x88, 0x80]) + os.urandom(4))
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


def _xor(data, mask):
    m = (mask * (len(data) // 4 + 1))[:len(data)]
    return (int.from_bytes(data, "big") ^ int.from_bytes(m, "big")).to_bytes(len(data), "big") if data else b""


class CDP:
    def __init__(self, ws_url):
        self.ws = WS(ws_url)
        self.n = 0
        self.events = []

    def call(self, method, params=None, timeout=20):
        self.n += 1
        mid = self.n
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        end = time.time() + timeout
        while time.time() < end:
            raw = self.ws.recv(max(0.05, end - time.time()))
            if raw is None:
                continue
            msg = json.loads(raw)
            if msg.get("id") == mid:
                if "error" in msg:
                    raise WSError(f"{method}: {msg['error'].get('message')}")
                return msg.get("result") or {}
            if "method" in msg:
                self.events.append(msg)
        raise WSError(f"{method}: el navegador no respondió en {timeout} s")

    def pump(self, secs, until=None):
        """Recibe eventos durante `secs` segundos (o hasta que llegue el evento `until`)."""
        end = time.time() + secs
        while time.time() < end:
            raw = self.ws.recv(max(0.05, min(0.25, end - time.time())))
            if raw is None:
                continue
            msg = json.loads(raw)
            if "method" in msg:
                self.events.append(msg)
                if until and msg["method"] == until:
                    return True
        return False

    def close(self):
        self.ws.close()


# ───────────── Teclas ─────────────
KEYS = {"arrowleft": ("ArrowLeft", 37), "arrowright": ("ArrowRight", 39), "arrowup": ("ArrowUp", 38),
        "arrowdown": ("ArrowDown", 40), "izquierda": ("ArrowLeft", 37), "derecha": ("ArrowRight", 39),
        "arriba": ("ArrowUp", 38), "abajo": ("ArrowDown", 40), "space": (" ", 32), "espacio": (" ", 32), " ": (" ", 32),
        "enter": ("Enter", 13), "escape": ("Escape", 27), "esc": ("Escape", 27), "tab": ("Tab", 9),
        "backspace": ("Backspace", 8), "shift": ("Shift", 16), "control": ("Control", 17), "ctrl": ("Control", 17),
        "alt": ("Alt", 18), "p": ("p", 80)}
CODES = {"ArrowLeft": "ArrowLeft", "ArrowRight": "ArrowRight", "ArrowUp": "ArrowUp", "ArrowDown": "ArrowDown", " ": "Space",
         "Enter": "Enter", "Escape": "Escape", "Tab": "Tab", "Backspace": "Backspace", "Shift": "ShiftLeft",
         "Control": "ControlLeft", "Alt": "AltLeft"}


def _key(name):
    k = str(name or "").strip()
    if k.lower() in KEYS:
        key, vk = KEYS[k.lower()]
    elif len(k) == 1:
        key, vk = k, ord(k.upper()) if k.isalnum() else ord(k)
    else:
        key, vk = k, 0
    code = CODES.get(key) or (("Key" + key.upper()) if len(key) == 1 and key.isalpha() else
                              ("Digit" + key) if len(key) == 1 and key.isdigit() else key)
    return key, code, vk


# ───────────── Utilidades ─────────────
def to_url(target, cwd=None):
    """Ruta local, URL o nombre de archivo → URL."""
    t = str(target or "").strip().strip('"').strip("'")
    if not t:
        t = "index.html"
    if t.startswith(("http://", "https://", "file://", "about:", "data:")):
        return t
    if t.startswith(("localhost", "127.0.0.1")):
        return "http://" + t
    p = Path(t)
    if not p.is_absolute() and cwd:
        p = Path(cwd) / p
    return p.resolve().as_uri()


def local_path(url):
    """file:///C:/x/juego.js → Path (o None si no es local)."""
    if not url or not url.startswith("file://"):
        return None
    p = unquote(urlparse(url).path)
    if re.match(r"^/[A-Za-z]:", p):
        p = p[1:]
    return Path(p)



def _line_of(url, line):
    p = local_path(url)
    if not p or not line or not p.exists():
        return ""
    try:
        from .tools import _read_text
        lines = _read_text(p).splitlines()
        if 0 < line <= len(lines):
            return lines[line - 1].strip()[:160]
    except Exception:
        pass
    return ""


def _short(url, cwd=None):
    if not url:
        return ""
    p = local_path(url)
    if p:
        try:
            return p.resolve().relative_to(Path(cwd).resolve()).as_posix() if cwd else p.name
        except (ValueError, OSError):
            return p.name
    return url if len(url) < 90 else url[:87] + "…"


def _arg_text(a):
    if "value" in a:
        v = a["value"]
        return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return a.get("description") or a.get("unserializableValue") or a.get("type", "")


def _crop(im, box):
    if not box:
        return im
    x, y, w, h = [int(round(v)) for v in box]
    x, y = max(0, x), max(0, y)
    w, h = min(im.width - x, w), min(im.height - y, h)
    return im.crop((x, y, x + w, y + h)) if w > 8 and h > 8 else im


def _img_stats(png, box=None):
    """Fracción de la imagen (o de la zona box) que NO es del color de fondo dominante (0-1), o None sin Pillow."""
    try:
        from PIL import Image
        im = _crop(Image.open(io.BytesIO(png)), box).convert("L")
        im = im.resize((400, max(1, int(400 * im.height / max(1, im.width)))))
        hist = im.histogram()
        mode = hist.index(max(hist))
        total = float(sum(hist) or 1)
        otros = sum(c for v, c in enumerate(hist) if abs(v - mode) > 12)
        return otros / total
    except Exception:
        return None


def _img_diff(a, b, box=None):
    """% de píxeles que cambiaron entre dos capturas (0-100) o None."""
    try:
        from PIL import Image, ImageChops
        ia = _crop(Image.open(io.BytesIO(a)), box).convert("L").resize((200, 125))
        ib = _crop(Image.open(io.BytesIO(b)), box).convert("L").resize((200, 125))
        d = ImageChops.difference(ia, ib).point(lambda v: 255 if v > 18 else 0)
        return round(100.0 * d.histogram()[255] / (200 * 125), 1)
    except Exception:
        return None


def _canvas_box(s):
    """Rectángulo del canvas visible más grande (el juego), o None."""
    v, _ = s.js("(()=>{let b=null,a=0;for(const c of document.querySelectorAll('canvas')){const r=c.getBoundingClientRect();"
                "if(r.width*r.height>a&&r.width>40&&r.height>40){a=r.width*r.height;b=[r.left,r.top,r.width,r.height];}}return b;})()")
    return v if isinstance(v, list) and len(v) == 4 else None


# ───────────── Sesión de prueba ─────────────
class Sesion:
    def __init__(self, width=1280, height=800):
        self.exe = find_browser()
        if not self.exe:
            raise RuntimeError("No encontré Microsoft Edge, Google Chrome ni Chromium en este equipo.")
        self.dir = tempfile.mkdtemp(prefix="noviq_nav_")
        args = [self.exe, "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={self.dir}", "--no-first-run",
                "--no-default-browser-check", "--disable-extensions", "--disable-background-networking", "--disable-sync",
                "--disable-component-update", "--mute-audio", "--hide-scrollbars", f"--window-size={width},{height}",
                "--allow-file-access-from-files", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist",
                "--autoplay-policy=no-user-gesture-required", "about:blank"]
        if not IS_WINDOWS and hasattr(os, "geteuid") and os.geteuid() == 0:
            args.insert(1, "--no-sandbox")
        extra = (os.environ.get("NOVIQ_NAV_ARGS") or "").split()
        if extra:
            args[1:1] = extra
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                                     creationflags=NO_WINDOW)
        port_file = Path(self.dir) / "DevToolsActivePort"
        t0 = time.time()
        while not port_file.exists() or not port_file.read_text(errors="ignore").strip():
            if self.proc.poll() is not None or time.time() - t0 > 25:
                self.close()
                raise RuntimeError("El navegador no arrancó en modo de pruebas (headless).")
            time.sleep(0.1)
        self.port = int(port_file.read_text().split()[0])
        ws_url = None
        import requests
        ses = requests.Session()
        ses.trust_env = False  # nunca pasar por el proxy del sistema para hablar con el navegador local
        for _ in range(40):
            try:
                pages = ses.get(f"http://127.0.0.1:{self.port}/json/list", timeout=3).json()
                ws_url = next((p["webSocketDebuggerUrl"] for p in pages if p.get("type") == "page"), None)
                if ws_url:
                    break
            except Exception:
                pass
            time.sleep(0.15)
        if not ws_url:
            self.close()
            raise RuntimeError("No pude conectarme a la pestaña del navegador de pruebas.")
        self.cdp = CDP(ws_url)
        for m in ("Runtime.enable", "Log.enable", "Network.enable", "Page.enable"):
            self.cdp.call(m)

    def navegar(self, url, espera_ms=2500, timeout=25):
        t0 = time.time()
        self.cdp.events = []
        res = self.cdp.call("Page.navigate", {"url": url}, timeout=timeout)
        if res.get("errorText"):
            return False, res["errorText"], time.time() - t0
        loaded = any(e.get("method") == "Page.loadEventFired" for e in self.cdp.events) or \
            self.cdp.pump(timeout, until="Page.loadEventFired")
        carga = time.time() - t0
        self.cdp.pump(max(0.2, espera_ms / 1000.0))
        return loaded, "", carga

    def js(self, expr, timeout=10):
        r = self.cdp.call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True,
                                               "userGesture": True}, timeout=timeout)
        if r.get("exceptionDetails"):
            ex = r["exceptionDetails"]
            return None, (ex.get("exception") or {}).get("description") or ex.get("text") or "error"
        return (r.get("result") or {}).get("value"), None

    def captura(self):
        r = self.cdp.call("Page.captureScreenshot", {"format": "png"}, timeout=20)
        return base64.b64decode(r.get("data") or "")

    def tecla(self, name, veces=1):
        key, code, vk = _key(name)
        for _ in range(max(1, min(int(veces or 1), 50))):
            base = {"key": key, "code": code, "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}
            self.cdp.call("Input.dispatchKeyEvent", dict(base, type="keyDown", text=key if len(key) == 1 else ""))
            self.cdp.call("Input.dispatchKeyEvent", dict(base, type="keyUp"))
            self.cdp.pump(0.06)

    def _centro(self, selector):
        v, err = self.js("(()=>{const e=document.querySelector(%s);if(!e)return null;e.scrollIntoView({block:'center'});"
                         "const r=e.getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2];})()" % json.dumps(selector))
        return v

    def clic(self, x=None, y=None, selector=None, boton="left", dobles=1):
        if selector:
            c = self._centro(selector)
            if not c:
                return f"no existe ningún elemento «{selector}»"
            x, y = c
        if x is None or y is None:
            x, y = 640, 400
        self.cdp.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        for i in range(dobles):
            self.cdp.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": boton, "clickCount": i + 1})
            self.cdp.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": boton, "clickCount": i + 1})
        self.cdp.pump(0.1)
        return ""

    def arrastrar(self, x1, y1, x2, y2, pasos=12):
        self.cdp.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x1, "y": y1})
        self.cdp.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x1, "y": y1, "button": "left", "clickCount": 1})
        for i in range(1, pasos + 1):
            x, y = x1 + (x2 - x1) * i / pasos, y1 + (y2 - y1) * i / pasos
            self.cdp.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "button": "left", "buttons": 1})
            self.cdp.pump(0.02)
        self.cdp.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x2, "y": y2, "button": "left", "clickCount": 1})

    def rueda(self, x, y, dy):
        self.cdp.call("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": x, "y": y, "deltaX": 0, "deltaY": dy})

    def escribir(self, texto, selector=None):
        if selector:
            v, err = self.js("(()=>{const e=document.querySelector(%s);if(!e)return false;e.focus();return true;})()" % json.dumps(selector))
            if not v:
                return f"no existe ningún elemento «{selector}»"
        self.cdp.call("Input.insertText", {"text": str(texto)})
        return ""

    def close(self):
        try:
            if getattr(self, "cdp", None):
                try:
                    self.cdp.call("Browser.close", timeout=3)
                except Exception:
                    pass
                self.cdp.close()
        except Exception:
            pass
        try:
            if self.proc.poll() is None:
                if IS_WINDOWS:
                    subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.proc.pid)], capture_output=True, creationflags=NO_WINDOW)
                else:
                    self.proc.kill()
            self.proc.wait(timeout=5)
        except Exception:
            pass
        for _ in range(5):
            try:
                shutil.rmtree(self.dir)
                break
            except FileNotFoundError:
                break
            except OSError:
                time.sleep(0.3)


def _eventos(events, cwd=None):
    """Convierte los eventos CDP en listas legibles: errores, fallos de carga, consola."""
    errores, cargas, consola, reqs = [], [], [], {}
    seen = set()
    for e in events:
        m, p = e.get("method"), e.get("params") or {}
        if m == "Network.requestWillBeSent":
            reqs[p.get("requestId")] = (p.get("request") or {}).get("url", "")
        elif m == "Runtime.exceptionThrown":
            d = p.get("exceptionDetails") or {}
            desc = ((d.get("exception") or {}).get("description") or d.get("text") or "").split("\n")[0]
            if d.get("text") and d["text"] not in desc and d["text"] != "Uncaught":
                desc = d["text"] + " " + desc
            url = d.get("url") or ""
            line = (d.get("lineNumber") or 0) + 1
            frames = ((d.get("stackTrace") or {}).get("callFrames") or [])
            if frames and not url:
                url, line = frames[0].get("url", ""), frames[0].get("lineNumber", 0) + 1
            key = (desc, url, line)
            if key not in seen:
                seen.add(key)
                errores.append({"msg": desc.strip() or "Error de JavaScript", "url": url, "archivo": _short(url, cwd),
                                "linea": line, "codigo": _line_of(url, line)})
        elif m == "Runtime.consoleAPICalled":
            tipo = p.get("type")
            txt = " ".join(_arg_text(a) for a in p.get("args") or [])[:300]
            frames = ((p.get("stackTrace") or {}).get("callFrames") or [])
            url, line = (frames[0].get("url", ""), frames[0].get("lineNumber", 0) + 1) if frames else ("", 0)
            if tipo in ("error", "assert"):
                key = (txt, url, line)
                if key not in seen:
                    seen.add(key)
                    errores.append({"msg": "console.error: " + txt, "url": url, "archivo": _short(url, cwd), "linea": line,
                                    "codigo": _line_of(url, line)})
            else:
                consola.append(f"[{tipo}] {txt}" + (f" ({_short(url, cwd)}:{line})" if url else ""))
        elif m == "Log.entryAdded":
            en = p.get("entry") or {}
            if en.get("level") == "error" and en.get("source") in ("network", "security", "javascript", "other"):
                url = en.get("url") or ""
                txt = en.get("text", "")
                if en.get("source") == "network" or "Failed to load" in txt:
                    key = ("carga", url)
                    if key not in seen:
                        seen.add(key)
                        cargas.append({"url": url, "archivo": _short(url, cwd), "motivo": txt[:160]})
                elif (txt, url) not in seen:
                    seen.add((txt, url))
                    errores.append({"msg": txt[:300], "url": url, "archivo": _short(url, cwd), "linea": en.get("lineNumber", 0) + 1 if en.get("lineNumber") is not None else 0,
                                    "codigo": ""})
            elif en.get("level") == "warning" and not re.search(r"GL Driver Message|GPU stall|\[\.WebGL-", en.get("text", "")):
                consola.append("[aviso] " + en.get("text", "")[:200])
        elif m == "Network.loadingFailed":
            url = reqs.get(p.get("requestId"), "")
            if p.get("canceled") or not url or url.startswith("data:"):
                continue
            key = ("carga", url)
            if key not in seen:
                seen.add(key)
                cargas.append({"url": url, "archivo": _short(url, cwd), "motivo": p.get("errorText", "")})
        elif m == "Network.responseReceived":
            r = p.get("response") or {}
            if int(r.get("status") or 0) >= 400:
                url = r.get("url", "")
                key = ("carga", url)
                if key not in seen:
                    seen.add(key)
                    cargas.append({"url": url, "archivo": _short(url, cwd), "motivo": f"HTTP {r.get('status')}"})
    return errores, cargas, consola


PAGE_INFO = r"""(()=>{const b=document.body;const cs=[...document.querySelectorAll('canvas')].map(c=>({id:c.id||'',w:c.width,h:c.height,
 vis:c.getBoundingClientRect().width>0}));const txt=(b&&b.innerText||'').replace(/\s+/g,' ').trim();
 return {title:document.title,text:txt.slice(0,600),canvas:cs,n:document.querySelectorAll('*').length,
 w:innerWidth,h:innerHeight,botones:[...document.querySelectorAll('button,a[href],input[type=button],input[type=submit]')].slice(0,12)
 .map(x=>(x.innerText||x.value||x.id||'').trim().slice(0,30)).filter(Boolean)};})()"""


def probar(target, cwd=None, acciones=None, evaluar="", captura=True, espera_ms=2500, width=1280, height=800):
    """Prueba una página. Devuelve dict con todo lo observado (para formatear o para decidir)."""
    url = to_url(target, cwd)
    out = {"url": url, "ok": False, "errores": [], "cargas": [], "consola": [], "acciones": [], "info": {}, "png": b"",
           "blanca": None, "eval": None, "eval_error": None, "navegador": "", "carga_s": 0}
    p = local_path(url)
    if p is not None and not p.exists():
        out["fatal"] = f"No existe el archivo {p}"
        return out
    s = Sesion(width, height)
    out["navegador"] = browser_name(s.exe)
    try:
        loaded, err, carga = s.navegar(url, espera_ms)
        out["carga_s"] = round(carga, 2)
        if err:
            out["fatal"] = f"No se pudo abrir la página: {err}"
            return out
        if not loaded:
            out["lenta"] = True
        box = _canvas_box(s)
        out["canvas_box"] = box
        before = s.captura() if captura or acciones else b""
        for i, ac in enumerate((acciones or [])[:25], 1):
            if not isinstance(ac, dict):
                ac = {"tipo": "tecla", "tecla": str(ac)}
            t = (ac.get("tipo") or ac.get("accion") or "").lower()
            nota = ""
            n_ev = len(s.cdp.events)
            try:
                if t in ("tecla", "teclas", "key"):
                    s.tecla(ac.get("tecla") or ac.get("key") or ac.get("valor"), ac.get("veces", 1))
                    desc = f"tecla {ac.get('tecla') or ac.get('key') or ac.get('valor')}" + (f" ×{ac.get('veces')}" if ac.get("veces", 1) != 1 else "")
                elif t in ("clic", "click", "doble_clic"):
                    nota = s.clic(ac.get("x"), ac.get("y"), ac.get("selector"), dobles=2 if t == "doble_clic" else 1)
                    desc = f"clic en {ac.get('selector') or (ac.get('x'), ac.get('y'))}"
                elif t in ("arrastrar", "drag"):
                    x1, y1 = ac.get("x", width // 2), ac.get("y", height // 2)
                    x2, y2 = ac.get("x2", x1 + 150), ac.get("y2", y1)
                    s.arrastrar(x1, y1, x2, y2)
                    desc = f"arrastrar mouse de ({x1},{y1}) a ({x2},{y2})"
                elif t in ("rueda", "wheel", "scroll"):
                    s.rueda(ac.get("x", width // 2), ac.get("y", height // 2), ac.get("delta", ac.get("dy", 300)))
                    desc = f"rueda del mouse {ac.get('delta', ac.get('dy', 300))}"
                elif t in ("escribir", "texto", "type"):
                    nota = s.escribir(ac.get("texto", ""), ac.get("selector"))
                    desc = f"escribir «{str(ac.get('texto', ''))[:40]}»"
                elif t in ("esperar", "wait"):
                    desc = f"esperar {int(ac.get('ms', 1000))} ms"
                elif t in ("js", "javascript", "evaluar"):
                    v, e = s.js(ac.get("codigo") or ac.get("js") or "")
                    nota = ("error: " + e) if e else ("→ " + json.dumps(v, ensure_ascii=False)[:300])
                    desc = "JavaScript"
                else:
                    out["acciones"].append({"n": i, "desc": f"acción desconocida «{t}»", "nota": "usa tecla/clic/arrastrar/rueda/escribir/esperar/js"})
                    continue
                s.cdp.pump(max(0.15, min(int(ac.get("ms", 400 if t not in ("esperar", "wait") else 1000)), 10000) / 1000.0))
            except Exception as e:
                nota = f"falló: {type(e).__name__}: {e}"
                desc = t
            cambio = None
            if before:
                after = s.captura()
                cambio = _img_diff(before, after, box)
                before = after
            nuevos = len([e for e in s.cdp.events[n_ev:] if e.get("method") in ("Runtime.exceptionThrown",)])
            out["acciones"].append({"n": i, "desc": desc, "nota": nota, "cambio": cambio, "errores_nuevos": nuevos})
        info, _ = s.js(PAGE_INFO)
        out["info"] = info or {}
        if evaluar:
            out["eval"], out["eval_error"] = s.js(evaluar)
        s.cdp.pump(0.3)
        if captura:
            out["png"] = s.captura()
            box = _canvas_box(s) or box
            st = _img_stats(out["png"], box)
            if st is not None:
                out["contenido_pct"] = round(st * 100, 2)
                out["blanca"] = st < 0.0003
                out["casi_vacia"] = 0.0003 <= st < 0.004
                out["zona"] = "canvas" if box else "pantalla"
        out["errores"], out["cargas"], out["consola"] = _eventos(s.cdp.events, cwd)
        out["ok"] = not out["errores"] and not out["cargas"]
        return out
    finally:
        s.close()


def reporte(r, max_items=6):
    """Texto claro para la IA (y el usuario)."""
    if r.get("fatal"):
        return "❌ " + r["fatal"]
    L = [f"🌐 Probé {r['url']} en {r.get('navegador') or 'el navegador'} invisible (cargó en {r.get('carga_s', 0)} s"
         + ("; la carga no terminó a tiempo" if r.get("lenta") else "") + ")."]
    if r["errores"]:
        L.append(f"\n❌ {len(r['errores'])} ERROR(ES) DE JAVASCRIPT (el primero suele ser la causa de los demás):")
        for i, e in enumerate(r["errores"][:max_items], 1):
            loc = f" — {e['archivo']}:{e['linea']}" if e.get("archivo") else ""
            L.append(f"{i}) {e['msg'][:260]}{loc}")
            if e.get("codigo"):
                L.append(f"   > {e['linea']}| {e['codigo']}")
    if r["cargas"]:
        L.append(f"\n❌ {len(r['cargas'])} ARCHIVO(S) NO CARGARON:")
        for c in r["cargas"][:max_items]:
            L.append(f"- {c['archivo']} ({c['motivo']})")
    if not r["errores"] and not r["cargas"]:
        L.append("\n✅ Sin errores de JavaScript ni archivos que fallen al cargar.")
    info = r.get("info") or {}
    if info:
        cv = info.get("canvas") or []
        partes = [f"título «{info.get('title', '')}»"]
        if cv:
            partes.append(f"{len(cv)} canvas (" + ", ".join(f"{c.get('id') or 'sin id'} {c.get('w')}x{c.get('h')}" for c in cv[:3]) + ")")
        if info.get("botones"):
            partes.append("botones: " + ", ".join(info["botones"][:8]))
        L.append("\n📄 Página: " + "; ".join(partes))
        if info.get("text"):
            L.append(f"   Texto visible: {info['text'][:300]}")
    if r.get("blanca") is True:
        zona = "El CANVAS del juego" if r.get("zona") == "canvas" else "La pantalla"
        L.append(f"\n⚠ {zona} se ve VACÍO o de un solo color: no se está dibujando nada (revisa los errores de arriba, "
                 "que el canvas/escena se cree, que el bucle de dibujo se ejecute y que la cámara apunte a los objetos).")
    elif r.get("casi_vacia"):
        zona = "del canvas" if r.get("zona") == "canvas" else "de la pantalla"
        L.append(f"\n⚠ Solo el {r.get('contenido_pct')}% {zona} tiene algo dibujado: casi vacío (¿cámara muy lejos, objetos muy "
                 "pequeños o fuera de la vista, o falta luz?).")
    elif r.get("blanca") is False and r.get("png"):
        L.append(f"\n🖼 La página muestra contenido ({r.get('contenido_pct')}% {'del canvas' if r.get('zona') == 'canvas' else 'de la pantalla'} "
                 "tiene dibujo).")
    if r.get("acciones"):
        L.append("\n🕹 Acciones de prueba:")
        for a in r["acciones"]:
            cambio = a.get("cambio")
            ef = "" if cambio is None else (f" → la imagen cambió {cambio}%" if cambio >= 0.3 else " → ⚠ la imagen NO cambió (¿el control no hace nada?)")
            extra = f" ({a['nota']})" if a.get("nota") else ""
            err = f" ⚠ provocó {a['errores_nuevos']} error(es)" if a.get("errores_nuevos") else ""
            L.append(f"{a['n']}. {a['desc']}{ef}{extra}{err}")
    if r.get("eval") is not None or r.get("eval_error"):
        L.append("\n🧪 Resultado de evaluar: " + (("ERROR " + r["eval_error"]) if r.get("eval_error")
                                                 else json.dumps(r["eval"], ensure_ascii=False)[:1500]))
    cons = [c for c in r.get("consola") or [] if c]
    if cons:
        L.append(f"\n📋 Consola ({len(cons)} mensajes; últimos):\n" + "\n".join(cons[-8:]))
    return "\n".join(L)
