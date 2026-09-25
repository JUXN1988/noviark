# -*- coding: utf-8 -*-
"""Entornos y herramientas de sistema para que la IA tenga control total de las pruebas:
  - Linux dentro de Windows (WSL): ejecutar comandos bash, instalar paquetes con apt (como root, sin contraseña).
  - Contenedores Docker: probar en un sistema limpio y aislado.
  - Entornos virtuales por proyecto (Python .venv, Node node_modules).
  - Agente instalador (sin IA): instala programas con winget / apt / pip / npm con un catálogo de nombres conocidos.
  - Puntos de restauración (git "en la sombra" dentro de .noviq, o zip si no hay git): volver atrás si algo sale mal.
  - Peticiones HTTP para probar APIs y servidores locales.
Todo se ejecuta en segundo plano con la salida en vivo en el chat."""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

from .config import IS_WINDOWS, python_exe

NO_WINDOW = 0x08000000 if IS_WINDOWS else 0

# ───────────── Linux (WSL) ─────────────
def _run(cmd, timeout=30, **kw):
    return subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=NO_WINDOW, **kw)


def wsl_estado():
    """{"disponible": bool, "distros": [...], "motivo": str}"""
    if not IS_WINDOWS:
        return {"disponible": bool(shutil.which("bash")), "distros": ["(este sistema ya es Linux/macOS)"], "nativo": True}
    if not shutil.which("wsl"):
        return {"disponible": False, "distros": [], "motivo": "WSL no está instalado."}
    try:
        r = _run(["wsl", "-l", "-q"], timeout=20)
        txt = r.stdout.decode("utf-16-le", "ignore") if b"\x00" in r.stdout else r.stdout.decode("utf-8", "ignore")
        distros = [d.strip() for d in txt.replace("\x00", "").splitlines() if d.strip()]
        return {"disponible": bool(distros), "distros": distros,
                "motivo": "" if distros else "WSL está, pero no hay ninguna distribución de Linux instalada."}
    except Exception as e:
        return {"disponible": False, "distros": [], "motivo": f"No pude consultar WSL: {e}"}


def instalar_wsl():
    """Abre la instalación de WSL + Ubuntu (Windows pide permiso de administrador y luego reiniciar)."""
    if not IS_WINDOWS:
        return "Este sistema ya es Linux/macOS: no hace falta WSL."
    subprocess.Popen(["powershell", "-NoProfile", "-Command",
                      "Start-Process wsl -Verb RunAs -ArgumentList '--install -d Ubuntu'"], creationflags=NO_WINDOW)
    return ("Se abrió la instalación de Linux (WSL + Ubuntu). Acepta el permiso de administrador de Windows; al terminar "
            "reinicia el PC y abre «Ubuntu» una vez para crear tu usuario. Después la IA podrá usar Linux.")


def t_ejecutar_linux(a, ctx):
    from .tools import run_background, run_streaming
    cmd = a.get("comando", "")
    if not cmd.strip():
        return "ERROR: falta el comando."
    root = bool(a.get("como_root"))
    if IS_WINDOWS:
        st = wsl_estado()
        if not st["disponible"]:
            return (f"ERROR: Linux (WSL) no está disponible: {st.get('motivo')}\nSolución: usa entorno(accion='instalar_linux') "
                    "para instalarlo (el usuario acepta el permiso de Windows y reinicia), o usa ejecutar_powershell / contenedor.")
        full = ["wsl", "--cd", str(ctx.cwd)] + (["-u", "root"] if root else []) + ["-e", "bash", "-lc", cmd]
    else:
        full = ["bash", "-lc", cmd]
    if a.get("segundo_plano"):
        return run_background(full, ctx, "linux: " + cmd[:180])
    return run_streaming(full, ctx, timeout=min(int(a.get("timeout_segundos") or 600), 3600))


# ───────────── Docker ─────────────
def docker_ok():
    if not shutil.which("docker"):
        return False, "Docker no está instalado (instálalo con instalar_herramienta nombre='docker')."
    try:
        r = _run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=20)
        if r.returncode != 0:
            return False, "Docker está instalado pero no está en marcha: abre Docker Desktop."
        return True, r.stdout.decode().strip()
    except Exception as e:
        return False, str(e)


def t_contenedor(a, ctx):
    """Ejecuta un comando dentro de un contenedor limpio con la carpeta del proyecto montada en /work."""
    from .tools import run_streaming
    ok, info = docker_ok()
    if not ok:
        return "ERROR: " + info
    img = a.get("imagen") or "python:3.12-slim"
    cmd = a.get("comando") or "ls -la"
    full = ["docker", "run", "--rm", "-v", f"{ctx.cwd}:/work", "-w", "/work"]
    if not a.get("red", True):
        full += ["--network", "none"]
    for p in (a.get("puertos") or [])[:5]:
        full += ["-p", str(p)]
    full += [img, "sh", "-lc", cmd]
    return run_streaming(full, ctx, timeout=min(int(a.get("timeout_segundos") or 900), 3600))


# ───────────── Entornos virtuales ─────────────
def _venv_python(root: Path):
    for c in (root / ".venv" / "Scripts" / "python.exe", root / ".venv" / "bin" / "python"):
        if c.exists():
            return c
    return None


def t_entorno(a, ctx):
    from .tools import run_streaming
    acc = (a.get("accion") or "info").lower()
    lang = (a.get("lenguaje") or "python").lower()
    root = ctx.cwd
    paquetes = [p for p in (a.get("paquetes") or []) if re.fullmatch(r"[\w.\-\[\]=<>~!@/:+]+", str(p))]
    if acc == "info":
        vp = _venv_python(root)
        st = wsl_estado()
        dk = docker_ok()
        tools_ = {n: bool(shutil.which(n)) for n in ("git", "node", "npm", "py", "python", "uv", "winget", "docker", "wsl", "java", "dotnet", "go", "cargo")}
        return (f"Proyecto: {root}\nPython del proyecto: {vp or 'sin .venv (usa: ' + str(python_exe() or 'NINGUNO: instala Python con instalar_herramienta nombre=python') + ')'}\n"
                f"node_modules: {'sí' if (root / 'node_modules').exists() else 'no'}\n"
                f"Linux (WSL): {'✔ ' + ', '.join(st['distros']) if st['disponible'] else '✖ ' + st.get('motivo', '')}\n"
                f"Docker: {'✔ ' + dk[1] if dk[0] else '✖ ' + dk[1]}\n"
                "Programas en el PATH: " + ", ".join(f"{k} {'✔' if v else '✖'}" for k, v in tools_.items()))
    if acc == "instalar_linux":
        return instalar_wsl()
    if lang == "python":
        if acc == "crear":
            if _venv_python(root):
                return f"Ya existe el entorno virtual {root / '.venv'}."
            base = shutil.which("py") and ["py", "-3"] or [python_exe() or "python"]
            out = run_streaming(base + ["-m", "venv", ".venv"], ctx, timeout=300)
            vp = _venv_python(root)
            if vp and paquetes:
                out += "\n" + run_streaming([str(vp), "-m", "pip", "install", *paquetes], ctx, timeout=1200)
            return out + ("\n✔ Entorno creado: las pruebas y ejecutar_python usarán .venv automáticamente." if vp else "")
        if acc == "instalar":
            vp = _venv_python(root) or Path(python_exe() or "python")
            if not paquetes and (root / "requirements.txt").exists():
                return run_streaming([str(vp), "-m", "pip", "install", "-r", "requirements.txt"], ctx, timeout=1800)
            return run_streaming([str(vp), "-m", "pip", "install", *paquetes], ctx, timeout=1800)
        if acc == "congelar":
            vp = _venv_python(root) or Path(python_exe() or "python")
            r = _run([str(vp), "-m", "pip", "freeze"], timeout=60)
            (root / "requirements.txt").write_bytes(r.stdout)
            return "requirements.txt actualizado:\n" + r.stdout.decode()[:3000]
    if lang in ("node", "javascript", "js"):
        npm = shutil.which("npm") or shutil.which("npm.cmd")
        if not npm:
            return "ERROR: Node.js no está instalado. Usa instalar_herramienta nombre='node'."
        if acc == "crear" and not (root / "package.json").exists():
            run_streaming([npm, "init", "-y"], ctx, timeout=120)
        if paquetes or acc == "instalar":
            return run_streaming([npm, "install", *paquetes], ctx, timeout=1800)
        return "✔ package.json listo."
    return "ERROR: acción o lenguaje no soportado (acciones: info, crear, instalar, congelar, instalar_linux; lenguajes: python, node)."


# ───────────── Agente instalador ─────────────
WINGET = {"git": "Git.Git", "node": "OpenJS.NodeJS.LTS", "nodejs": "OpenJS.NodeJS.LTS", "python": "Python.Python.3.12",
          "java": "EclipseAdoptium.Temurin.21.JDK", "jdk": "EclipseAdoptium.Temurin.21.JDK", "dotnet": "Microsoft.DotNet.SDK.8",
          "go": "GoLang.Go", "rust": "Rustlang.Rustup", "ffmpeg": "Gyan.FFmpeg", "7zip": "7zip.7zip", "gh": "GitHub.cli",
          "docker": "Docker.DockerDesktop", "uv": "astral-sh.uv", "vscode": "Microsoft.VisualStudioCode", "cmake": "Kitware.CMake",
          "arduino-cli": "ArduinoSA.CLI", "php": "PHP.PHP.8.3", "maven": "Apache.Maven", "gradle": "Gradle.Gradle",
          "sqlite": "SQLite.SQLite", "postgresql": "PostgreSQL.PostgreSQL.16", "mysql": "Oracle.MySQL", "ollama": "Ollama.Ollama",
          "lmstudio": "ElementLabs.LMStudio", "android-studio": "Google.AndroidStudio", "chrome": "Google.Chrome",
          "powershell": "Microsoft.PowerShell", "curl": "cURL.cURL", "make": "GnuWin32.Make", "nvm": "CoreyButler.NVMforWindows",
          "pnpm": "pnpm.pnpm", "bun": "Oven-sh.Bun", "deno": "DenoLand.Deno", "llvm": "LLVM.LLVM", "mingw": "BrechtSanders.WinLibs.POSIX.UCRT"}
APT = {"node": "nodejs npm", "nodejs": "nodejs npm", "python": "python3 python3-pip python3-venv", "java": "openjdk-21-jdk",
       "go": "golang", "rust": "rustc cargo", "gcc": "build-essential", "make": "build-essential", "cmake": "cmake", "git": "git",
       "ffmpeg": "ffmpeg", "sqlite": "sqlite3", "php": "php-cli", "dotnet": "dotnet-sdk-8.0", "curl": "curl"}


def t_instalar_herramienta(a, ctx):
    from .tools import run_streaming
    nombre = (a.get("nombre") or "").strip().lower()
    gestor = (a.get("gestor") or "auto").lower()
    if not re.fullmatch(r"[\w.\-@/+]+", nombre or ""):
        return "ERROR: nombre inválido."
    if nombre == "wsl" or nombre == "linux":
        return instalar_wsl()
    if gestor == "pip":
        from .pruebas import project_python
        return run_streaming([project_python(ctx.cwd), "-m", "pip", "install", nombre], ctx, timeout=1800)
    if gestor == "npm":
        npm = shutil.which("npm") or shutil.which("npm.cmd")
        return run_streaming([npm, "install", "-g", nombre], ctx, timeout=1800) if npm else "ERROR: falta Node.js (instala 'node')."
    if gestor == "apt" or (gestor == "auto" and not IS_WINDOWS):
        pk = APT.get(nombre, nombre)
        if IS_WINDOWS:
            if not wsl_estado()["disponible"]:
                return "ERROR: Linux (WSL) no está instalado; instala primero 'wsl'."
            cmd = ["wsl", "-u", "root", "-e", "bash", "-lc", f"apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y {pk}"]
        else:
            cmd = ["bash", "-lc", f"sudo -n apt-get install -y {pk} || apt-get install -y {pk}"]
        return run_streaming(cmd, ctx, timeout=1800)
    # Windows: winget
    if not shutil.which("winget"):
        return "ERROR: winget no está disponible en este Windows. Instala «App Installer» desde Microsoft Store."
    wid = WINGET.get(nombre)
    if not wid:
        r = _run(["winget", "search", nombre, "--accept-source-agreements"], timeout=60)
        txt = r.stdout.decode("utf-8", "replace")
        return (f"No tengo «{nombre}» en mi catálogo. Resultados de winget (elige el Id exacto y vuelve a llamar con nombre=<Id> y gestor='winget'):\n"
                + txt[-2500:]) if gestor != "winget" else run_streaming(
            ["winget", "install", "--id", nombre, "-e", "--accept-package-agreements", "--accept-source-agreements", "--silent"], ctx, 1800)
    out = run_streaming(["winget", "install", "--id", wid, "-e", "--accept-package-agreements", "--accept-source-agreements",
                         "--silent"], ctx, timeout=1800)
    return out + "\n(Si el programa no aparece en el PATH, puede hacer falta reiniciar Noviark.)"


# ───────────── Puntos de restauración ─────────────
SNAP_EXCL = ["node_modules/", ".venv/", "venv/", "__pycache__/", ".noviq/", ".noviq_logs/", "dist/", "build/", ".git/",
             "*.pyc", ".noviq_tmp_*", "capturas/", "*.log"]


def _git(root: Path, *args, timeout=60):
    gd = root / ".noviq" / "snapshots.git"
    env = dict(os.environ, GIT_DIR=str(gd), GIT_WORK_TREE=str(root), GIT_AUTHOR_NAME="Noviark", GIT_AUTHOR_EMAIL="noviq@local",
               GIT_COMMITTER_NAME="Noviark", GIT_COMMITTER_EMAIL="noviq@local")
    return subprocess.run(["git", *args], capture_output=True, timeout=timeout, env=env, cwd=str(root), creationflags=NO_WINDOW)


def snapshot(root: Path, mensaje="punto automático"):
    """Crea un punto de restauración. Devuelve id o None. Nunca toca el .git propio del proyecto."""
    root = Path(root)
    try:
        if not root.exists():
            return None
        if shutil.which("git"):
            try:
                gd = root / ".noviq" / "snapshots.git"
                if not gd.exists():
                    gd.parent.mkdir(parents=True, exist_ok=True)
                    _git(root, "init", "-q")
                    (gd / "info").mkdir(parents=True, exist_ok=True)
                    (gd / "info" / "exclude").write_text("\n".join(SNAP_EXCL) + "\n", encoding="utf-8")
                _git(root, "add", "-A", timeout=120)
                r = _git(root, "commit", "-q", "-m", mensaje[:200], "--allow-empty")
                if r.returncode == 0:
                    return _git(root, "rev-parse", "--short", "HEAD").stdout.decode().strip()
                _log_snap(f"git commit falló en {root}: {(r.stderr or b'').decode('utf-8', 'replace')[:300]}")
            except Exception as e:  # si git falla, se usa el respaldo en zip
                _log_snap(f"git falló en {root}: {type(e).__name__}: {e}")
        # sin git: zip de los archivos de código (máx. 40 MB)
        d = root / ".noviq" / "snapshots"
        d.mkdir(parents=True, exist_ok=True)
        sid = datetime.now().strftime("%Y%m%d_%H%M%S")
        total = 0
        with zipfile.ZipFile(d / f"{sid}.zip", "w", zipfile.ZIP_DEFLATED) as z:
            for dp, dns, fns in os.walk(root):
                dns[:] = [x for x in dns if x not in ("node_modules", ".venv", "venv", "__pycache__", ".noviq", ".git", "dist", "build")]
                for f in fns:
                    p = Path(dp) / f
                    try:
                        sz = p.stat().st_size
                    except OSError:
                        continue
                    if sz > 5_000_000 or f.startswith(".noviq_tmp"):
                        continue
                    total += sz
                    if total > 40_000_000:
                        break
                    z.write(p, p.relative_to(root).as_posix())
        (d / f"{sid}.txt").write_text(mensaje, encoding="utf-8")
        snaps = sorted(d.glob("*.zip"))
        for old in snaps[:-15]:
            old.unlink(missing_ok=True)
        return sid
    except Exception as e:
        _log_snap(f"no se pudo crear el punto de restauración en {root}: {type(e).__name__}: {e}")
        return None


def _log_snap(msg):
    try:
        from .config import DATA_DIR
        with open(DATA_DIR / "registro.log", "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} | puntos de restauración | {msg}\n")
    except Exception:
        pass


def t_puntos_restauracion(a, ctx):
    root = ctx.cwd
    acc = (a.get("accion") or "listar").lower()
    usa_git = (root / ".noviq" / "snapshots.git").exists() and shutil.which("git")
    if acc == "crear":
        sid = snapshot(root, a.get("mensaje") or "punto manual")
        return f"✔ Punto de restauración {sid} creado." if sid else "ERROR: no pude crear el punto de restauración."
    if acc == "listar":
        if usa_git:
            r = _git(root, "log", "--date=format:%Y-%m-%d %H:%M", "--pretty=%h | %ad | %s", "-n", "25")
            return "Puntos de restauración (id | fecha | descripción):\n" + (r.stdout.decode() or "(ninguno)")
        d = root / ".noviq" / "snapshots"
        zs = sorted(d.glob("*.zip"), reverse=True) if d.exists() else []
        return "Puntos (zip):\n" + "\n".join(f"{z.stem} | {(d / (z.stem + '.txt')).read_text(encoding='utf-8') if (d / (z.stem + '.txt')).exists() else ''}" for z in zs) or "(ninguno)"
    sid = (a.get("id") or "").strip()
    if not re.fullmatch(r"[\w]+", sid):
        return "ERROR: indica el id del punto (usa accion='listar')."
    if acc == "diferencias":
        if not usa_git:
            return "Las diferencias solo están disponibles con git instalado."
        r = _git(root, "diff", "--stat", sid)
        r2 = _git(root, "diff", sid, "--", *(a.get("archivos") or []))
        return (r.stdout.decode() + "\n" + r2.stdout.decode(errors="replace")[:12000]) or "Sin diferencias."
    if acc == "volver":
        snapshot(root, f"antes de volver a {sid}")  # siempre se puede deshacer la vuelta atrás
        if usa_git:
            files = a.get("archivos") or ["."]
            r = _git(root, "checkout", sid, "--", *files, timeout=120)
            return (f"✔ Archivos restaurados al punto {sid}." if r.returncode == 0 else "ERROR: " + r.stderr.decode()[:500])
        z = root / ".noviq" / "snapshots" / f"{sid}.zip"
        if not z.exists():
            return "ERROR: no existe ese punto."
        with zipfile.ZipFile(z) as zz:
            names = [n for n in zz.namelist() if not a.get("archivos") or n in a["archivos"]]
            for n in names:
                zz.extract(n, root)
        return f"✔ Restaurados {len(names)} archivos del punto {sid}."
    return "ERROR: accion debe ser crear, listar, diferencias o volver."


# ───────────── HTTP ─────────────
def t_peticion_http(a, ctx):
    import requests
    url = a.get("url", "")
    if not re.match(r"https?://", url):
        return "ERROR: la URL debe empezar con http:// o https://"
    metodo = (a.get("metodo") or "GET").upper()
    hdrs = a.get("cabeceras") or {}
    body = a.get("cuerpo")
    t0 = time.time()
    try:
        kw = {"headers": hdrs, "timeout": min(int(a.get("timeout_segundos") or 30), 300), "allow_redirects": True}
        if isinstance(body, (dict, list)):
            kw["json"] = body
        elif body:
            kw["data"] = str(body).encode("utf-8")
        r = requests.request(metodo, url, **kw)
    except requests.RequestException as e:
        return f"ERROR: {type(e).__name__}: {e}. (¿Está el servidor en marcha? Revisa procesos.)"
    ms = int((time.time() - t0) * 1000)
    ct = r.headers.get("content-type", "")
    txt = r.text
    if "json" in ct:
        try:
            txt = json.dumps(r.json(), ensure_ascii=False, indent=1)
        except ValueError:
            pass
    head = "\n".join(f"{k}: {v}" for k, v in list(r.headers.items())[:15])
    return f"HTTP {r.status_code} {r.reason} · {ms} ms · {len(r.content)} bytes\n{head}\n\n{txt[:8000]}"
