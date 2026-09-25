# -*- coding: utf-8 -*-
"""Agente de pruebas y autocorrección (sin LLM).

Revisa el código como lo haría un desarrollador y entrega a la IA un reporte MÍNIMO:
archivo, línea, qué falla, 3 líneas de código alrededor y una pista concreta de cómo arreglarlo.
Así la IA (sobre todo la local, con poco contexto) corrige SOLO esa parte, sin leer todo el proyecto.

Revisiones:
  • Python: sintaxis (compile), nombres no definidos (pyflakes), módulos faltantes (se instalan solos si se permite),
            pruebas con pytest si el proyecto tiene tests.
  • JavaScript: node --check · JSON: validez · HTML: archivos enlazados que no existen
  • PowerShell (Windows): analizador de sintaxis
"""
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import texto as TX
from .config import IS_WINDOWS, NO_WINDOW
from .indice import SKIP

PIP_MAP = {"cv2": "opencv-python", "PIL": "pillow", "sklearn": "scikit-learn", "yaml": "pyyaml", "bs4": "beautifulsoup4",
           "dotenv": "python-dotenv", "docx": "python-docx", "serial": "pyserial", "win32api": "pywin32",
           "win32com": "pywin32", "win32gui": "pywin32", "Crypto": "pycryptodome", "dateutil": "python-dateutil",
           "jwt": "pyjwt", "telegram": "python-telegram-bot", "fitz": "pymupdf", "googleapiclient": "google-api-python-client",
           "OpenSSL": "pyopenssl", "usb": "pyusb", "skimage": "scikit-image", "pptx": "python-pptx", "Levenshtein": "python-Levenshtein",
           "customtkinter": "customtkinter", "ttkbootstrap": "ttkbootstrap", "qrcode": "qrcode[pil]"}


def project_python(cwd: Path):
    """Python del proyecto si tiene su propio entorno virtual; si no, el de Noviark."""
    for cand in (cwd / ".venv" / "Scripts" / "python.exe", cwd / "venv" / "Scripts" / "python.exe",
                 cwd / ".venv" / "bin" / "python", cwd / "venv" / "bin" / "python"):
        if cand.exists():
            return str(cand)
    from .config import python_exe
    return python_exe() or "python"


def _files(root: Path, exts):
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP and not d.startswith(".")]
        for f in fns:
            if Path(f).suffix.lower() in exts and not f.startswith(".noviq_tmp"):
                yield Path(dp) / f


def _snippet(path: Path, line, ctx=2):
    try:
        lines = TX.read_text(path).splitlines()
    except OSError:
        return ""
    if not line or line > len(lines):
        return ""
    a, b = max(1, line - ctx), min(len(lines), line + ctx)
    return "\n".join(f"{'>' if i == line else ' '}{i:>4}| {lines[i - 1][:150]}" for i in range(a, b + 1))


def _run(cmd, cwd, timeout=120):
    try:
        r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, timeout=timeout, creationflags=NO_WINDOW,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1"))
        return r.returncode, (r.stdout or b"").decode("utf-8", "replace") + (r.stderr or b"").decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return -1, f"tiempo agotado ({timeout}s)"
    except FileNotFoundError as e:
        return -2, str(e)


def _similar(name, path: Path):
    try:
        ids = set(re.findall(r"\b[A-Za-z_]\w{2,}\b", TX.read_text(path)))
    except OSError:
        return []
    ids.discard(name)
    return difflib.get_close_matches(name, list(ids), n=3, cutoff=0.7)


def hint(msg, path=None):
    m = msg.lower()
    ext = Path(path).suffix.lower() if path else ""
    if ext == ".json" or "json" in m:
        return "JSON: usa comillas dobles en claves y textos, y quita comas sobrantes antes de } o ]."
    if ext in (".js", ".mjs", ".cjs") and "syntax" in m:
        return "JavaScript: falta cerrar una llave {, paréntesis ( o hay una coma/punto y coma de más cerca de esa línea."
    n = re.search(r"undefined name '(\w+)'|name '(\w+)' is not defined", msg)
    if n:
        name = n.group(1) or n.group(2)
        sim = _similar(name, path) if path else []
        return f"«{name}» no existe: defínelo o impórtalo" + (f" (¿quisiste decir {', '.join(sim)}?)" if sim else "") + "."
    if "was never closed" in m or "unexpected eof" in m or "eol while" in m or "unterminated" in m:
        return "Falta cerrar un paréntesis, corchete, llave o comilla cerca de esa línea."
    if "indent" in m:
        return "Sangría incorrecta: usa 4 espacios por nivel y no mezcles tabs."
    if "invalid syntax" in m or "syntaxerror" in m:
        return "Sintaxis inválida: revisa ':' al final de if/def/for, comas y paréntesis en esa línea o la anterior."
    if "no module named" in m or "módulo faltante" in m:
        return "Falta instalar el módulo (pip install) o el nombre del import está mal escrito."
    if "assert" in m:
        return "La prueba esperaba otro resultado: revisa la lógica de la función probada, no la prueba."
    if "attributeerror" in m:
        return "Ese objeto no tiene ese atributo/método: revisa el nombre o el tipo del objeto."
    if "typeerror" in m:
        return "Tipos o número de argumentos incorrectos en la llamada: compara con la definición de la función."
    if "keyerror" in m:
        return "La clave no existe en el diccionario: usa .get() o verifica el nombre de la clave."
    if "indexerror" in m:
        return "Índice fuera de rango: verifica el tamaño de la lista antes de acceder."
    if "zerodivision" in m:
        return "División entre cero: valida el divisor antes de dividir."
    if "filenotfound" in m or "no existe el archivo" in m:
        return "El archivo no existe: créalo o corrige la ruta (usa rutas relativas al proyecto)."
    return "Corrige solo esa línea/bloque."


def _issue(root, path, line, msg, kind):
    p = Path(path)
    rel = p.relative_to(root).as_posix() if p.is_absolute() and str(p).startswith(str(root)) else str(path)
    return {"archivo": rel, "linea": line, "msg": msg.strip()[:300], "tipo": kind, "pista": hint(msg, p),
            "fragmento": _snippet(p, line) if p.exists() else ""}


# ───────────── Revisiones estáticas (rápidas, sin ejecutar el programa) ─────────────
def check_python(root, files):
    issues = []
    for f in files:
        try:
            src = TX.read_text(f)
            compile(src, str(f), "exec")
        except SyntaxError as e:
            issues.append(_issue(root, f, e.lineno or 1, f"{type(e).__name__}: {e.msg}", "sintaxis"))
            continue
        except (OSError, ValueError):
            continue
        try:
            from pyflakes import api as fl_api
            from pyflakes import messages as FM

            class Rep:
                def __init__(self):
                    self.out = []

                def unexpectedError(self, *a):
                    pass

                def syntaxError(self, *a):
                    pass

                def flake(self, m):
                    if isinstance(m, (FM.UndefinedName, FM.UndefinedLocal, FM.UndefinedExport)):
                        self.out.append(m)
            rep = Rep()
            fl_api.check(src, str(f), rep)
            for m in rep.out[:5]:
                issues.append(_issue(root, f, m.lineno, m.message % m.message_args, "nombre"))
        except ImportError:
            pass
    return issues


def missing_modules(root, files, py):
    local = {p.stem for p in _files(root, {".py"})} | {d.name for d in root.iterdir() if d.is_dir()}
    std = set(getattr(sys, "stdlib_module_names", ()))
    mods = {}
    for f in files:
        try:
            for m in re.finditer(r"^\s*(?:from\s+([\w]+)[\w.]*\s+import|import\s+([\w]+))", TX.read_text(f), re.M):
                name = m.group(1) or m.group(2)
                if name and name not in std and name not in local and name != "__future__":
                    mods.setdefault(name, f)
        except OSError:
            continue
    if not mods:
        return {}
    code = "import importlib.util,sys;print('\\n'.join(m for m in sys.argv[1:] if importlib.util.find_spec(m) is None))"
    rc, out = _run([py, "-c", code] + sorted(mods), root, 60)
    missing = [l.strip() for l in out.splitlines() if l.strip() in mods]
    return {m: mods[m] for m in missing}


def check_js(root, files):
    node = shutil.which("node")
    issues = []
    if not node:
        return issues
    for f in files:
        if f.suffix.lower() not in (".js", ".mjs", ".cjs"):
            continue
        rc, out = _run([node, "--check", str(f)], root, 30)
        if rc not in (0, -2):
            m = re.search(r":(\d+)\n", out)
            msg = next((l for l in out.splitlines() if "Error" in l), out.strip()[:200])
            issues.append(_issue(root, f, int(m.group(1)) if m else 1, msg, "sintaxis"))
    return issues


def check_json(root, files):
    issues = []
    for f in files:
        try:
            json.loads(TX.read_text(f))
        except json.JSONDecodeError as e:
            issues.append(_issue(root, f, e.lineno, f"JSON inválido: {e.msg}", "sintaxis"))
        except OSError:
            pass
    return issues


def check_html(root, files):
    issues = []
    for f in files:
        try:
            src = TX.read_text(f)
        except OSError:
            continue
        for m in re.finditer(r'(?:src|href)=["\']([^"\'#?]+)["\']', src):
            ref = m.group(1)
            if re.match(r"(?i)^(https?:|//|data:|mailto:|tel:|javascript:)", ref) or ref.endswith("/"):
                continue
            if not (f.parent / ref).exists():
                line = src[:m.start()].count("\n") + 1
                issues.append(_issue(root, f, line, f"El archivo enlazado «{ref}» no existe", "enlace"))
    return issues[:6]


def check_ps1(root, files):
    if not IS_WINDOWS:
        return []
    issues = []
    for f in files:
        script = ("$e=$null;[void][System.Management.Automation.Language.Parser]::ParseFile('" + str(f).replace("'", "''")
                  + "',[ref]$null,[ref]$e);$e|%{\"$($_.Extent.StartLineNumber)|$($_.Message)\"}")
        rc, out = _run(["powershell", "-NoProfile", "-Command", script], root, 30)
        for l in out.splitlines()[:3]:
            if "|" in l:
                ln, msg = l.split("|", 1)
                if ln.strip().isdigit():
                    issues.append(_issue(root, f, int(ln), msg, "sintaxis"))
    return issues


# ───────────── Pruebas que ejecutan código ─────────────
FRAME_RX = re.compile(r'File "([^"]+)", line (\d+)')


def run_pytest(root, py, allow_install=False):
    tests = list(_files(root, {".py"}))
    if not any(t.name.startswith("test_") or t.name.endswith("_test.py") for t in tests):
        return None, []
    rc, out = _run([py, "-c", "import pytest"], root, 30)
    if rc != 0:
        if not allow_install:
            return None, []
        _run([py, "-m", "pip", "install", "-q", "--disable-pip-version-check", "pytest"], root, 300)
    rc, out = _run([py, "-m", "pytest", "-q", "-x", "--tb=short", "-p", "no:cacheprovider"], root, 240)
    if rc == 0:
        return True, []
    if rc == 5 or "no tests ran" in out:
        return None, []
    frames = [(f, int(l)) for f, l in FRAME_RX.findall(out) if str(root) in os.path.abspath(f) or not os.path.isabs(f)]
    frames += [(m.group(1), int(m.group(2))) for m in re.finditer(r"^([\w./\\-]+\.py):(\d+):", out, re.M)]
    err = next((l.strip() for l in reversed(out.splitlines()) if re.match(r"^(E\s+)?\w+(Error|Exception)|^E\s+assert|FAILED", l.strip())), "")
    if frames:
        f, ln = frames[-1]
        p = Path(f) if os.path.isabs(f) else root / f
        iss = [_issue(root, p, ln, err or "La prueba falló", "prueba")]
        # ubica la función probada para que la IA vaya directo a corregirla
        try:
            line = TX.read_text(p).splitlines()[ln - 1]
            for name in re.findall(r"\b([A-Za-z_]\w*)\s*\(", line):
                if name in ("assert", "len", "str", "int", "float", "print", "isinstance", "round", "abs"):
                    continue
                for src in _files(root, {".py"}):
                    if src == p:
                        continue
                    for i, l in enumerate(TX.read_text(src).splitlines(), 1):
                        if re.match(rf"\s*def\s+{name}\s*\(", l):
                            iss.append(_issue(root, src, i, f"Función probada «{name}» (probablemente aquí está el error)", "logica"))
                            iss[-1]["fragmento"] = _snippet(src, i + 1, 2)
                            raise StopIteration
        except (StopIteration, OSError, IndexError):
            pass
        return False, iss
    return False, [{"archivo": "(pruebas)", "linea": 0, "msg": (err or out.strip()[-300:])[:300], "tipo": "prueba",
                    "pista": hint(err or out), "fragmento": ""}]


def install_modules(root, py, mods, emit=None):
    from . import aprendizaje as A
    pk = [A.pip_name(m) or PIP_MAP.get(m, m) for m in mods]
    if emit:
        emit(f"📦 Agente de dependencias: instalando {', '.join(pk)}…")
    rc, out = _run([py, "-m", "pip", "install", "-q", "--disable-pip-version-check"] + pk, root, 600)
    return rc == 0, out[-400:]


# ───────────── Orquestación ─────────────
EXTS = {".py", ".js", ".mjs", ".cjs", ".json", ".html", ".htm", ".ps1"}


def run_checks(root: Path, only=None, dynamic=False, allow_install=False, emit=None, web=False):
    """Devuelve {"ok", "errores", "instalados", "pruebas"}. only = rutas relativas a revisar (None = todo).
    web=True: además abre la página principal (index.html) en el navegador invisible y revisa errores reales."""
    root = Path(root)
    if only:
        files = [root / f for f in only if (root / f).is_file() and Path(f).suffix.lower() in EXTS]
    else:
        files = list(_files(root, EXTS))[:300]
    by = lambda *e: [f for f in files if f.suffix.lower() in e]
    py = project_python(root)
    issues = []
    issues += check_python(root, by(".py"))
    issues += check_js(root, by(".js", ".mjs", ".cjs"))
    issues += check_json(root, [f for f in by(".json") if f.name not in ("package-lock.json",)])
    issues += check_html(root, by(".html", ".htm"))
    issues += check_ps1(root, by(".ps1"))
    issues += check_secrets(root, files)
    installed = []
    miss = missing_modules(root, by(".py"), py) if by(".py") else {}
    if miss:
        if allow_install:
            ok, out = install_modules(root, py, list(miss), emit)
            still = missing_modules(root, by(".py"), py) if ok else miss
            installed = [m for m in miss if m not in still]
            miss = still
        for m, f in miss.items():
            issues.append({"archivo": Path(f).relative_to(root).as_posix(), "linea": 0, "tipo": "dependencia",
                           "msg": f"Módulo faltante: {m}", "pista": f"Instala con: pip install {PIP_MAP.get(m, m)}", "fragmento": ""})
    tests_ok, humo = None, ""
    if dynamic and not issues:
        tests_ok, t_issues = run_pytest(root, py, allow_install)
        issues += t_issues
        if not issues and not only:
            ok_run, r_issues, humo = smoke_run(root)
            issues += r_issues
    if web and not issues:
        w_issues, w_desc = web_run(root, emit)
        issues += w_issues
        if w_desc:
            humo = (humo + "; " if humo else "") + w_desc
    return {"ok": not issues, "errores": issues, "instalados": installed, "pruebas": tests_ok, "humo": humo}


def web_entry(root: Path):
    """index.html principal de un proyecto web (None si no es web o es un proyecto con servidor/npm)."""
    root = Path(root)
    if (root / "package.json").exists():
        return None
    for cand in (root / "index.html", root / "public" / "index.html", root / "src" / "index.html", root / "web" / "index.html"):
        if cand.exists():
            return cand
    htmls = [f for f in _files(root, {".html", ".htm"})]
    return htmls[0] if len(htmls) == 1 else None


def web_run(root, emit=None):
    """Abre la página en el navegador invisible: errores de JS, archivos que no cargan, pantalla vacía."""
    entry = web_entry(root)
    if not entry:
        return [], ""
    try:
        from . import navegador as NAV
        if not NAV.find_browser():
            return [], ""
        if emit:
            emit("🌐 Agente de pruebas: abriendo la página en un navegador invisible…")
        r = NAV.probar(str(entry), cwd=root, captura=True, espera_ms=2000)
    except Exception as e:
        return [], f"(no se pudo abrir el navegador de pruebas: {str(e)[:80]})"
    rel = entry.relative_to(root).as_posix()
    issues = []
    for c in r.get("cargas", [])[:3]:
        issues.append({"archivo": c["archivo"], "linea": 0, "tipo": "enlace", "msg": f"Al abrir {rel} no cargó {c['archivo']} ({c['motivo']})",
                       "pista": "Corrige la ruta del <script>/<link> o crea el archivo; si es un CDN sin internet, descárgalo al proyecto.",
                       "fragmento": ""})
    for e in r.get("errores", [])[:3]:
        f = Path(root) / e["archivo"] if e.get("archivo") else entry
        i = {"archivo": e.get("archivo") or rel, "linea": e.get("linea") or 0, "tipo": "ejecución",
             "msg": f"Error al abrir {rel} en el navegador: {e['msg'][:220]}", "pista": hint(e["msg"]),
             "fragmento": _snippet(f, e.get("linea") or 0) if f.exists() else ""}
        from .diagnostico import _pista_js
        i["pista"] = _pista_js(e["msg"])
        issues.append(i)
    if not issues and r.get("blanca"):
        issues.append({"archivo": rel, "linea": 0, "tipo": "ejecución", "fragmento": "",
                       "msg": f"{rel} abre sin errores pero " + ("el canvas está VACÍO (no se dibuja nada)" if r.get("zona") == "canvas"
                                                               else "la página se ve en blanco"),
                       "pista": "Revisa que se llame a la función de inicio y al bucle de dibujo, y que haya objetos visibles."})
    desc = "" if issues else f"abrí {rel} en el navegador: sin errores" + (
        f", {r.get('contenido_pct')}% con dibujo" if r.get("contenido_pct") is not None else "")
    return issues, desc


# ───────────── Agente de seguridad: claves API escritas en el código ─────────────
SECRET_RX = re.compile(r"(nvapi-[A-Za-z0-9_\-]{20,}|sk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}|AIza[0-9A-Za-z_\-]{35}|gsk_[A-Za-z0-9]{20,}|"
                       r"hf_[A-Za-z0-9]{25,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|xai-[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|"
                       r"sk-or-v1-[a-f0-9]{30,})")


def check_secrets(root, files):
    out = []
    for f in files:
        if f.suffix.lower() in (".md", ".txt") or f.name in (".env", ".env.local"):
            continue
        try:
            for i, line in enumerate(TX.read_text(f).splitlines(), 1):
                m = SECRET_RX.search(line)
                if m:
                    out.append(_issue(root, f, i, f"Clave API escrita en el código ({m.group(1)[:8]}…): cualquiera que vea el archivo puede usarla",
                                      "seguridad"))
                    out[-1]["pista"] = ("Muévela a un archivo .env (y agrégalo a .gitignore) o a una variable de entorno, y léela con "
                                        "os.environ / process.env. Luego recomienda al usuario revocar esa clave.")
                    break
        except OSError:
            continue
    return out


# ───────────── Prueba de humo: ejecutar el programa de verdad ─────────────
GUI_SERVER = re.compile(r"^\s*(import|from)\s+(tkinter|customtkinter|pygame|PyQt\d|PySide\d|kivy|flask|fastapi|uvicorn|"
                        r"django|streamlit|gradio|http\.server|socketserver|wx|dearpygui|flet|pystray|schedule)\b", re.M)


def entry_point(root: Path):
    """(comando, descripción, es_largo) del punto de entrada del proyecto o None."""
    root = Path(root)
    pkg = root / "package.json"
    if pkg.exists():
        try:
            j = json.loads(pkg.read_text(encoding="utf-8"))
            sc = j.get("scripts") or {}
            npm = shutil.which("npm") or shutil.which("npm.cmd")
            if npm and "start" in sc:
                return [npm, "start"], "npm start", True
            main = j.get("main")
            node = shutil.which("node")
            if node and main and (root / main).exists():
                return [node, main], f"node {main}", True
        except Exception:
            pass
    for n in ("main.py", "app.py", "run.py", "manage.py", "__main__.py", "bot.py", "server.py", "gui.py"):
        f = root / n
        if f.exists():
            src = TX.read_text(f)
            args = [n, "check"] if n == "manage.py" else [n]
            return [project_python(root), *args], f"python {' '.join(args)}", bool(GUI_SERVER.search(src))
    py = [f for f in root.glob("*.py") if not f.name.startswith(("test_", ".noviq"))]
    if len(py) == 1:
        src = TX.read_text(py[0])
        return [project_python(root), py[0].name], f"python {py[0].name}", bool(GUI_SERVER.search(src))
    for n in ("index.js", "server.js", "app.js", "main.js"):
        if (root / n).exists() and shutil.which("node") and not (root / "index.html").exists():
            return [shutil.which("node"), n], f"node {n}", True
    return None


def smoke_run(root, timeout=15):
    """Ejecuta el programa como lo haría el usuario. Si arranca y sigue vivo (ventana/servidor) sin errores = OK.
    Devuelve (ok|None, issues, descripcion)."""
    root = Path(root)
    ep = entry_point(root)
    if not ep:
        return None, [], ""
    cmd, desc, largo = ep
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", NOVIQ_PRUEBA="1", PYTHONUNBUFFERED="1")
    try:
        p = subprocess.Popen(cmd, cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.PIPE,
                             env=env, creationflags=NO_WINDOW)
    except OSError as e:
        return False, [{"archivo": desc, "linea": 0, "tipo": "ejecución", "msg": f"No se pudo ejecutar: {e}", "pista": "", "fragmento": ""}], desc
    try:
        out, _ = p.communicate(input=b"", timeout=timeout)
        rc = p.returncode
        vivo = False
    except subprocess.TimeoutExpired:
        vivo = True
        try:
            if IS_WINDOWS:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True, creationflags=NO_WINDOW)
            else:
                p.kill()
            out, _ = p.communicate(timeout=5)
        except Exception:
            out = b""
        rc = 0
    txt = (out or b"").decode("utf-8", "replace")
    if "EOFError" in txt and "input" in txt:
        return True, [], desc + " (espera datos del usuario por teclado: no se puede probar sin intervención)"
    if (rc != 0 and not vivo) or "Traceback (most recent call last)" in txt or re.search(r"^\w*Error: |^Uncaught |UnhandledPromiseRejection", txt, re.M):
        iss = _trace_issues(root, txt, desc)
        return False, iss, desc
    return True, [], desc + (" (arrancó y siguió funcionando sin errores)" if vivo else " (terminó sin errores)")


def _trace_issues(root, txt, desc):
    root_s = str(Path(root).resolve()).lower()
    last = None
    for m in re.finditer(r'File "([^"]+)", line (\d+)', txt):
        if m.group(1).lower().startswith(root_s) or not os.path.isabs(m.group(1)):
            last = m
    for m in re.finditer(r"\(?([A-Za-z]:[\\/][^:()]+|/[^:()\s]+)\.(?:js|mjs|ts):(\d+)", txt):
        if m.group(1).lower().startswith(root_s):
            last = m
    err = next((l for l in reversed(txt.strip().splitlines()) if re.search(r"(Error|Exception)\b", l)), txt.strip().splitlines()[-1] if txt.strip() else "falló")
    if last:
        f = Path(last.group(1))
        f = f if f.is_absolute() else Path(root) / f
        i = _issue(root, f, int(last.group(2)), f"Al ejecutar «{desc}»: {err.strip()[:200]}", "ejecución")
        i["pista"] = hint(err)
        return [i]
    return [{"archivo": desc, "linea": 0, "tipo": "ejecución", "msg": f"Al ejecutar «{desc}»: {err.strip()[:220]}",
             "pista": hint(err), "fragmento": txt.strip()[-600:]}]


def report(res, max_errors=3):
    """Reporte ultra compacto para la IA."""
    if res["ok"]:
        s = "✅ PRUEBAS OK: sin errores de sintaxis, nombres ni dependencias"
        if res.get("pruebas"):
            s += "; las pruebas automáticas pasaron"
        if res.get("instalados"):
            s += f"; instalé {', '.join(res['instalados'])}"
        if res.get("humo"):
            s += f"; lo ejecuté: {res['humo']}"
        return s + "."
    errs = res["errores"]
    out = [f"❌ PRUEBAS: {len(errs)} problema(s)" + (f" (muestro {max_errors})" if len(errs) > max_errors else "") + ":"]
    for i, e in enumerate(errs[:max_errors], 1):
        loc = f"{e['archivo']}:{e['linea']}" if e.get("linea") else e["archivo"]
        out.append(f"{i}) {loc} — {e['msg']}\n   → {e['pista']}")
        if e.get("fragmento"):
            out.append(e["fragmento"])
    if res.get("instalados"):
        out.append(f"(Instalé automáticamente: {', '.join(res['instalados'])})")
    out.append("Corrige SOLO esas líneas con editar_archivo (texto exacto o desde_linea/hasta_linea). No reescribas el archivo.")
    return "\n".join(out)
