# -*- coding: utf-8 -*-
"""Agente de diagnóstico (sin LLM): revisa un proyecto como lo haría un programador experto antes de tocar nada
y entrega una lista PRIORIZADA de problemas concretos (archivo:línea, código, causa y cómo arreglarlo).

Pensado sobre todo para IAs pequeñas/locales, que no saben por dónde empezar cuando el usuario dice «no funciona»:
  1. Codificación: archivos en ANSI/UTF-16, bytes nulos, acentos dañados (se reparan solos a UTF-8, con respaldo).
  2. Código incompleto: «// ... resto del código», «TODO implementar», archivos casi vacíos.
  3. Web (HTML + JS): funciones que se llaman pero no existen o están en un archivo que la página no carga,
     orden de carga de los <script>, getElementById de ids que no existen en el HTML, librerías (THREE, jQuery,
     Phaser…) usadas sin cargarlas, módulos ES abiertos con doble clic (file://).
  4. Lo que ya revisaba el agente de pruebas: sintaxis Python/JS/JSON/PowerShell, nombres no definidos,
     módulos que faltan, claves API en el código.
  5. Dinámico: abre la página en un navegador invisible (errores de consola, archivos que no cargan, pantalla en
     blanco) y, si está permitido, ejecuta el programa (prueba de humo).
"""
import difflib
import os
import re
from pathlib import Path

from . import texto as TX

SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".gradle", "bin", "obj",
        ".idea", ".vs", ".noviq", ".noviq_logs", ".pytest_cache", ".mypy_cache", "imagenes", "capturas"}
TEXT_EXT = {".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".html", ".htm", ".css", ".json", ".cs", ".java", ".kt",
            ".php", ".ps1", ".go", ".rs", ".dart", ".ino", ".cpp", ".c", ".h", ".vue", ".sql", ".bat", ".cmd", ".sh",
            ".toml", ".yml", ".yaml", ".ini", ".xml", ".md", ".txt", ".svg"}
CODE_EXT = TEXT_EXT - {".md", ".txt", ".json", ".xml", ".svg", ".ini", ".toml", ".yml", ".yaml"}
JS_EXT = {".js", ".mjs", ".cjs", ".jsx"}

# ───────────── Utilidades ─────────────


def _files(root: Path, exts, limit=400):
    out = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP and not d.startswith(".")]
        for f in fns:
            if Path(f).suffix.lower() in exts and not f.startswith(".noviq_tmp"):
                out.append(Path(dp) / f)
                if len(out) >= limit:
                    return out
    return out


def _rel(root, p):
    try:
        return Path(p).resolve().relative_to(Path(root).resolve()).as_posix()
    except (ValueError, OSError):
        return Path(p).name


def _snip(lines, line, ctx=1):
    if not line or line > len(lines):
        return ""
    a, b = max(1, line - ctx), min(len(lines), line + ctx)
    return "\n".join(f"{'>' if i == line else ' '}{i:>4}| {lines[i - 1][:150]}" for i in range(a, b + 1))


def _issue(archivo, linea, msg, pista, tipo, prioridad=2, fragmento=""):
    return {"archivo": archivo, "linea": linea, "msg": msg, "pista": pista, "tipo": tipo, "prioridad": prioridad,
            "fragmento": fragmento}


# ───────────── JavaScript: quitar comentarios y textos (conservando las líneas) ─────────────
_REGEX_PREV = set("(,=:[!&|?{};+-*%<>~^") | {""}


def strip_js(src):
    """Reemplaza comentarios, cadenas y regex por espacios (mantiene saltos de línea y posiciones)."""
    out = []
    i, n = 0, len(src)
    prev = ""  # último carácter significativo de código
    while i < n:
        c = src[i]
        nx = src[i + 1] if i + 1 < n else ""
        if c == "/" and nx == "/":
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
            continue
        if c == "/" and nx == "*":
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("".join("\n" if ch == "\n" else " " for ch in src[i:j]))
            i = j
            continue
        if c in "'\"`":
            q, j = c, i + 1
            depth = 0
            while j < n:
                ch = src[j]
                if ch == "\\":
                    j += 2
                    continue
                if q == "`" and ch == "$" and j + 1 < n and src[j + 1] == "{":
                    depth += 1
                    j += 2
                    continue
                if q == "`" and ch == "}" and depth:
                    depth -= 1
                elif ch == q and not depth:
                    break
                elif ch == "\n" and q != "`":
                    break
                j += 1
            j = min(n, j + 1)
            out.append(q + "".join("\n" if ch == "\n" else " " for ch in src[i + 1:j - 1]) + (q if j - 1 > i else ""))
            i = j
            prev = q
            continue
        if c == "/" and prev in _REGEX_PREV:
            # literal de expresión regular
            j, cls = i + 1, False
            while j < n and src[j] != "\n":
                ch = src[j]
                if ch == "\\":
                    j += 2
                    continue
                if ch == "[":
                    cls = True
                elif ch == "]":
                    cls = False
                elif ch == "/" and not cls:
                    break
                j += 1
            if j < n and src[j] == "/":
                j += 1
                while j < n and src[j].isalpha():
                    j += 1
                out.append(" " * (j - i))
                i = j
                prev = "x"
                continue
        out.append(c)
        if not c.isspace():
            prev = c if not (c.isalnum() or c in "_$") else "x"
            if prev == "x":
                # palabras clave tras las que puede venir una regex: return /x/, typeof /x/ …
                k = i
                while k >= 0 and (src[k].isalnum() or src[k] in "_$"):
                    k -= 1
                if src[k + 1:i + 1] in ("return", "typeof", "case", "in", "of", "delete", "void", "throw", "new", "else"):
                    prev = ""
        i += 1
    return "".join(out)


KEYWORDS = {"if", "for", "while", "switch", "catch", "function", "return", "typeof", "void", "delete", "await", "yield",
            "else", "do", "try", "with", "in", "of", "instanceof", "super", "import", "this", "async", "class", "const",
            "let", "var", "new", "throw", "case", "default", "export", "extends", "static", "get", "set", "constructor"}
BUILTINS = set("""
alert confirm prompt setTimeout setInterval clearTimeout clearInterval requestAnimationFrame cancelAnimationFrame
requestIdleCallback cancelIdleCallback parseInt parseFloat isNaN isFinite fetch encodeURIComponent decodeURIComponent
encodeURI decodeURI escape unescape atob btoa structuredClone queueMicrotask getComputedStyle matchMedia open close
print postMessage eval require Number String Boolean Symbol BigInt Array Object Function Proxy Reflect Date Map Set
WeakMap WeakSet WeakRef Promise RegExp Error TypeError RangeError SyntaxError ReferenceError EvalError URIError
AggregateError JSON Math Intl URL URLSearchParams Blob File FileReader FormData Headers Request Response AbortController
WebSocket Worker SharedWorker XMLHttpRequest Event CustomEvent KeyboardEvent MouseEvent PointerEvent TouchEvent
WheelEvent FocusEvent InputEvent IntersectionObserver ResizeObserver MutationObserver PerformanceObserver AudioContext
OfflineAudioContext Audio Image Option OffscreenCanvas Path2D ImageData ImageBitmap createImageBitmap DOMParser
XMLSerializer TextEncoder TextDecoder Float32Array Float64Array Int8Array Int16Array Int32Array Uint8Array
Uint8ClampedArray Uint16Array Uint32Array BigInt64Array BigUint64Array ArrayBuffer SharedArrayBuffer DataView
Notification BroadcastChannel MessageChannel EventSource Worklet DOMRect DOMPoint DOMMatrix CanvasGradient
FontFace Geolocation Gamepad speechSynthesis SpeechSynthesisUtterance MediaRecorder MediaStream RTCPeerConnection
Node Element HTMLElement Document Window console document window navigator location history localStorage
sessionStorage indexedDB crypto performance screen globalThis self parent top frames caches customElements
scrollTo scrollBy scroll moveTo resizeTo focus blur getSelection importScripts setImmediate clearImmediate
module exports process Buffer __dirname __filename define arguments undefined NaN Infinity isPrototypeOf
hasOwnProperty toString valueOf""".split())
LIBS = [  # (patrón en el src del <script>, globales que define, nombre, uso típico, CDN sugerido)
    (r"three", {"THREE"}, "three.js", r"\bTHREE\.", "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"),
    (r"jquery", {"$", "jQuery"}, "jQuery", r"(?<![\w$.])(?:\$|jQuery)\s*\(", "https://code.jquery.com/jquery-3.7.1.min.js"),
    (r"phaser", {"Phaser"}, "Phaser", r"\bPhaser\.", "https://cdn.jsdelivr.net/npm/phaser@3.80.1/dist/phaser.min.js"),
    (r"pixi", {"PIXI"}, "PixiJS", r"\bPIXI\.", "https://cdn.jsdelivr.net/npm/pixi.js@7/dist/pixi.min.js"),
    (r"babylon", {"BABYLON"}, "Babylon.js", r"\bBABYLON\.", "https://cdn.babylonjs.com/babylon.js"),
    (r"chart", {"Chart"}, "Chart.js", r"\bnew\s+Chart\s*\(", "https://cdn.jsdelivr.net/npm/chart.js"),
    (r"gsap|tweenmax", {"gsap", "TweenMax", "TimelineMax"}, "GSAP", r"\bgsap\.", "https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"),
    (r"matter", {"Matter"}, "Matter.js", r"\bMatter\.", "https://cdn.jsdelivr.net/npm/matter-js@0.19.0/build/matter.min.js"),
    (r"cannon", {"CANNON"}, "cannon.js", r"\bCANNON\.", "https://cdn.jsdelivr.net/npm/cannon@0.6.2/build/cannon.min.js"),
    (r"socket\.io", {"io"}, "Socket.IO", r"(?<![\w$.])io\s*\(", "https://cdn.socket.io/4.7.5/socket.io.min.js"),
    (r"tone", {"Tone"}, "Tone.js", r"\bTone\.", "https://cdn.jsdelivr.net/npm/tone@14/build/Tone.js"),
    (r"howler", {"Howl", "Howler"}, "Howler.js", r"\bnew\s+Howl\s*\(", "https://cdn.jsdelivr.net/npm/howler@2/dist/howler.min.js"),
    (r"d3", {"d3"}, "D3.js", r"\bd3\.", "https://cdn.jsdelivr.net/npm/d3@7"),
    (r"axios", {"axios"}, "axios", r"\baxios[.(]", "https://cdn.jsdelivr.net/npm/axios/dist/axios.min.js"),
    (r"vue", {"Vue"}, "Vue", r"\bVue\.", "https://unpkg.com/vue@3/dist/vue.global.prod.js"),
    (r"react", {"React", "ReactDOM"}, "React", r"\bReact(?:DOM)?\.", "https://unpkg.com/react@18/umd/react.production.min.js"),
    (r"leaflet", {"L"}, "Leaflet", r"\bL\.map\s*\(", "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"),
    (r"anime", {"anime"}, "anime.js", r"(?<![\w$.])anime\s*\(", "https://cdn.jsdelivr.net/npm/animejs@3/lib/anime.min.js"),
    (r"lodash|underscore", {"_"}, "lodash", r"(?<![\w$.])_\.", "https://cdn.jsdelivr.net/npm/lodash/lodash.min.js"),
    (r"tailwind", set(), "Tailwind", r"$^", ""),
    (r"bootstrap", {"bootstrap"}, "Bootstrap", r"\bbootstrap\.", ""),
    (r"p5", set(), "p5.js", r"$^", ""),  # p5 en modo global define cientos de funciones: se omite el análisis
]

DEF_PATTERNS = [
    re.compile(r"\bfunction\s*\*?\s*([A-Za-z_$][\w$]*)"),
    re.compile(r"\bclass\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"(?:window|globalThis|self)\.([A-Za-z_$][\w$]*)\s*=(?!=)"),
    re.compile(r"(?:^|[;{}\n])\s*([A-Za-z_$][\w$]*)\s*=(?![=>])", re.M),
    re.compile(r"\bcatch\s*\(\s*([A-Za-z_$][\w$]*)"),
    re.compile(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*=>"),
]
DECL = re.compile(r"\b(?:const|let|var)\s+([^;=]+?)(?:=|;|\bof\b|\bin\b|$)", re.M)
PARAMS = [re.compile(r"\bfunction\s*\*?\s*[\w$]*\s*\(([^)]*)\)"), re.compile(r"\(([^()]*)\)\s*=>")]
IMPORT = re.compile(r"\bimport\s+(?:([\w$]+)\s*,?\s*)?(?:\{([^}]*)\}|\*\s+as\s+([\w$]+))?\s*(?:from\s+)?")
CALL = re.compile(r"(?<![\w$.])(new\s+)?([A-Za-z_$][\w$]*)\s*\(")
IDENT = re.compile(r"[A-Za-z_$][\w$]*")


def _names(txt):
    """Identificadores declarados en una lista de parámetros o destructuración (a, {b, c: d}, [e, f] = 1)."""
    out = set()
    for part in re.split(r",(?![^{\[]*[}\]])", txt):
        part = re.sub(r"=.*", "", part.strip(), flags=re.S)
        for m in IDENT.finditer(part):
            if m.group(0) not in KEYWORDS:
                out.add(m.group(0))
    return out


def js_defs(code):
    """Nombres definidos en código JS ya limpiado con strip_js."""
    d = set()
    for rx in DEF_PATTERNS:
        d.update(m.group(1) for m in rx.finditer(code))
    for m in DECL.finditer(code):
        d |= _names(m.group(1))
    for rx in PARAMS:
        for m in rx.finditer(code):
            d |= _names(m.group(1))
    for m in IMPORT.finditer(code):
        if m.group(1):
            d.add(m.group(1))
        if m.group(2):
            d |= {x.split(" as ")[-1].strip() for x in m.group(2).split(",") if x.strip()}
        if m.group(3):
            d.add(m.group(3))
    return d - KEYWORDS


def js_calls(code):
    """[(nombre, línea, es_new, profundidad_de_llaves)] de las llamadas a funciones sin punto delante."""
    out = []
    depth_at = []
    depth = 0
    for ch in code:
        depth_at.append(depth)
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
    for m in CALL.finditer(code):
        name = m.group(2)
        if name in KEYWORDS:
            continue
        # «nombre(args) {» es la DEFINICIÓN de un método/función, no una llamada
        k, par = m.end(), 1
        while k < len(code) and par:
            if code[k] == "(":
                par += 1
            elif code[k] == ")":
                par -= 1
            k += 1
        rest = code[k:k + 40].lstrip()
        if rest.startswith("{") or rest.startswith("=>"):
            continue
        line = code.count("\n", 0, m.start()) + 1
        ls = code.rfind("\n", 0, m.start()) + 1
        arrow = "=>" in code[ls:m.start()]
        depth = depth_at[m.start()] if m.start() < len(depth_at) else 0
        out.append((name, line, bool(m.group(1)), 1 if arrow and depth == 0 else depth))
    return out


# ───────────── HTML ─────────────
SCRIPT_RX = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.S | re.I)
ATTR_RX = lambda name: re.compile(r"\b" + name + r"\s*=\s*([\"'])(.*?)\1", re.I | re.S)
ID_RX = re.compile(r"\bid\s*=\s*([\"'])([^\"']+)\1", re.I)
HANDLER_RX = re.compile(r"\bon[a-z]+\s*=\s*([\"'])(.*?)\1", re.I | re.S)


def parse_html(src):
    """Scripts en orden: [{"src", "inline", "module", "linea"}], ids, llamadas en atributos on*."""
    scripts = []
    for m in SCRIPT_RX.finditer(src):
        attrs, body = m.group(1), m.group(2)
        s = ATTR_RX("src").search(attrs)
        t = ATTR_RX("type").search(attrs)
        typ = (t.group(2).strip().lower() if t else "")
        if typ and typ not in ("module", "text/javascript", "application/javascript", "text/babel", "importmap"):
            if typ != "importmap":
                continue
        scripts.append({"src": s.group(2).strip() if s else "", "inline": "" if s else body,
                        "module": typ == "module", "importmap": typ == "importmap", "babel": typ == "text/babel",
                        "linea": src.count("\n", 0, m.start()) + 1,
                        "linea_cuerpo": src.count("\n", 0, m.start(2)) + 1})
    ids = {m.group(2).strip() for m in ID_RX.finditer(src)}
    handlers = [(m.group(2), src.count("\n", 0, m.start()) + 1) for m in HANDLER_RX.finditer(src)]
    return scripts, ids, handlers


VENDOR = re.compile(r"(?i)(\.min\.js$|^(three|jquery|phaser|pixi|babylon|chart|gsap|matter|cannon|socket\.io|tone|howler|d3|"
                    r"axios|vue|react|react-dom|leaflet|anime|lodash|underscore|bootstrap|p5|orbitcontrols|gltfloader|"
                    r"objloader|stats|dat\.gui|tween|popper|swiper|alpine)[\w.-]*\.js$)")


def is_vendor(p, raw=""):
    """Librería de terceros o archivo minificado (no se analiza como código del usuario)."""
    if VENDOR.search(Path(p).name):
        return True
    try:
        if Path(p).stat().st_size > 250_000:
            return True
    except OSError:
        pass
    lines = raw.splitlines() if raw else []
    return bool(lines) and max(len(x) for x in lines[:50]) > 1500


def _is_remote(u):
    return bool(re.match(r"(?i)^(https?:)?//", u))


# ───────────── Revisiones ─────────────
def check_encoding(root, files, reparar=False, ctx=None):
    issues, fixed = [], []
    for f in files:
        try:
            data = f.read_bytes()
        except OSError:
            continue
        if not data or len(data) > 3_000_000:
            continue
        text, enc = TX.decode(data)
        probs = TX.problemas(data, text, enc)
        if not probs:
            continue
        rel = _rel(root, f)
        if reparar and (not TX.es_utf8(enc) or "\x00" in text):
            try:
                if ctx is not None:
                    from .tools import _backup
                    _backup(ctx, f)
                old = TX.reparar(f)
                if old:
                    fixed.append(f"{rel} ({TX.nombre(old)} → UTF-8)")
                    probs = [p for p in probs if "UTF-8" not in p and "nulos" not in p]
            except OSError:
                pass
        for p in probs:
            issues.append(_issue(rel, 0, f"{rel} {p}", "Guárdalo en UTF-8: usa escribir_archivo/editar_archivo (nunca "
                                 "Set-Content/Out-File) o diagnosticar con reparar=true.", "codificación", 1))
    return issues, fixed


PLACEHOLDER = re.compile(r"(?i)^\s*(?://|#|/\*|<!--|\*)\s*(?:\.\.\.|…|\[?\s*(?:el\s+)?resto\s+(?:del|de\s+la)|"
                         r"c[oó]digo\s+(?:anterior|existente|igual|previo|sin\s+cambios)|mismo\s+c[oó]digo|sin\s+cambios|"
                         r"aqu[ií]\s+va|(?:por\s+)?implementar|todo:?\s*implement|rest\s+of\s+(?:the\s+)?code|existing\s+code|"
                         r"same\s+as\s+(?:before|above)|\.\.\.\s*(?:c[oó]digo|code)|add\s+(?:your|more)\s+code)")


def check_placeholders(root, files):
    issues = []
    for f in files:
        if f.suffix.lower() not in CODE_EXT or is_vendor(f):
            continue
        try:
            lines = TX.read_text(f).splitlines()
        except OSError:
            continue
        rel = _rel(root, f)
        hits = [i for i, l in enumerate(lines, 1) if PLACEHOLDER.search(l) or (l.strip() in ("...", "…") and f.suffix.lower() != ".py")]
        for i in hits[:2]:
            issues.append(_issue(rel, i, f"{rel}:{i} tiene un marcador de CÓDIGO OMITIDO («{lines[i - 1].strip()[:60]}»): "
                                 "falta código real ahí", "Escribe el código completo en ese lugar (sin «...» ni «resto del código»).",
                                 "incompleto", 1, _snip(lines, i)))
        n_code = len([l for l in lines if l.strip() and not l.strip().startswith(("//", "#", "/*", "*"))])
        if f.suffix.lower() in JS_EXT | {".py"} and n_code <= 2 and f.name != "__init__.py" and f.stat().st_size < 400:
            issues.append(_issue(rel, 1, f"{rel} está casi vacío ({n_code} línea(s) de código)", "Si antes tenía más código, "
                                 "se sobrescribió por error: usa deshacer_cambio o puntos_restauracion para recuperarlo, "
                                 "o escríbelo completo.", "incompleto", 2, _snip(lines, 1, 2)))
        # ¿se encogió? (hay una copia de respaldo mucho más grande)
        bak = Path(root) / ".noviq" / "respaldos"
        if bak.exists() and len(lines) >= 1:
            try:
                grandes = [(b, TX.read_text(b).count("\n") + 1) for b in bak.glob(f.name + ".*.bak")]
                grandes = [x for x in grandes if x[1] >= 30 and x[1] > 3 * len(lines)]
            except OSError:
                grandes = []
            if grandes:
                b, n = max(grandes, key=lambda x: x[1])
                issues.append(_issue(rel, 1, f"{rel} tiene {len(lines)} líneas pero antes tenía {n} (hay copia de respaldo): "
                                     "¿se BORRÓ código sin querer?", "Si no fue a propósito, recupera la versión completa con "
                                     f"deshacer_cambio (ruta='{rel}') o puntos_restauracion, y corrige desde ahí.", "incompleto", 2))
    return issues


def check_web(root, htmls, js_files):
    """Análisis cruzado HTML ↔ JS."""
    issues = []
    root = Path(root)
    code_cache = {}

    def js_info(p):
        if p not in code_cache:
            try:
                raw = TX.read_text(p)
            except OSError:
                raw = ""
            code = strip_js(raw) if len(raw) < 1_500_000 else ""
            code_cache[p] = (raw, code, js_defs(code))
        return code_cache[p]

    all_defs = {}  # nombre → [archivo relativo]
    for p in js_files:
        for d in js_info(p)[2]:
            all_defs.setdefault(d, []).append(_rel(root, p))
    all_ids = set()
    html_info = {}
    for h in htmls:
        try:
            src = TX.read_text(h)
        except OSError:
            continue
        scripts, ids, handlers = parse_html(src)
        html_info[h] = (src, scripts, ids, handlers)
        all_ids |= ids
    dyn_ids = set()
    for p in js_files:
        raw = js_info(p)[0]
        dyn_ids |= set(re.findall(r"\bid\s*=\s*\\?[\"']([\w-]+)", raw))
        dyn_ids |= set(re.findall(r"\.id\s*=\s*[\"'`]([\w-]+)", raw))
        dyn_ids |= set(re.findall(r"setAttribute\(\s*[\"']id[\"']\s*,\s*[\"']([\w-]+)", raw))
    for h, (src, scripts, ids, handlers) in html_info.items():
        hrel = _rel(root, h)
        hlines = src.splitlines()
        user_defs, lib_defs, remote, units, srcs = set(), set(), [], [], []
        uses_modules = any(s["module"] for s in scripts)
        skip_calls = False
        for k, s in enumerate(scripts):
            if s["importmap"] or s["babel"]:
                skip_calls = skip_calls or s["babel"]  # JSX con Babel: el análisis no aplica
                continue
            if s["src"]:
                srcs.append(s["src"])
                for pat, glob, *_ in LIBS:
                    if re.search(pat, s["src"].split("/")[-1] if not _is_remote(s["src"]) else s["src"], re.I):
                        lib_defs |= glob
                        if pat == "p5":
                            skip_calls = True
                if _is_remote(s["src"]):
                    remote.append(s["src"])
                    continue
                p = (h.parent / s["src"].split("?")[0].split("#")[0]).resolve()
                if not p.exists():
                    continue  # lo informa check_html del agente de pruebas
                raw, code, defs = js_info(p)
                if is_vendor(p, raw):
                    lib_defs |= defs
                    continue
                units.append((k, _rel(root, p), code, raw.splitlines(), 0, s["module"], defs))
                user_defs |= defs
            elif s["inline"].strip():
                code = strip_js(s["inline"])
                defs = js_defs(code)
                user_defs |= defs
                units.append((k, hrel, code, hlines, s["linea_cuerpo"] - 1, s["module"], defs))
        page_defs = user_defs | lib_defs
        # módulos ES abiertos con doble clic (file://) no cargan
        mod_local = [s for s in scripts if s["module"] and ((s["src"] and not _is_remote(s["src"])) or
                                                          re.search(r"\bfrom\s*[\"'](\.{0,2}/)", s["inline"]))]
        if mod_local:
            issues.append(_issue(hrel, mod_local[0]["linea"],
                                 f"{hrel} usa <script type=\"module\">: al abrir el archivo con doble clic (file://) el navegador "
                                 "BLOQUEA los módulos (error de CORS) y la página no hace nada",
                                 "Usa scripts normales (sin type=module, sin import/export) o sirve la carpeta con "
                                 "`python -m http.server 8000` y abre http://localhost:8000.", "web", 2))
        # librerías usadas sin cargar
        all_code = "\n".join(u[2] for u in units)
        for pat, glob, nombre, uso, cdn in LIBS:
            if not cdn or not re.search(uso, all_code):
                continue
            if any(re.search(pat, x, re.I) for x in srcs) or (glob & user_defs):
                continue
            if uses_modules and re.search(r"\bimport\b", all_code):
                continue  # con módulos ES la librería se importa (lo revisa el navegador de pruebas)
            u = next((u for u in units if re.search(uso, u[2])), None)
            ln = (u[2][:re.search(uso, u[2]).start()].count("\n") + 1 + u[4]) if u else 0
            issues.append(_issue(u[1] if u else hrel, ln, f"El código usa {nombre} ({', '.join(sorted(glob)) or nombre}) pero "
                                 f"{hrel} no carga esa librería con ningún <script>", f"Agrega en {hrel}, ANTES de tus scripts: "
                                 f"<script src=\"{cdn}\"></script>", "web", 1, _snip(u[3], ln) if u else ""))
        if "THREE" in lib_defs and re.search(r"\bTHREE\.OrbitControls\b", all_code) and \
                not any("orbitcontrols" in x.lower() for x in srcs) and "OrbitControls" not in user_defs:
            issues.append(_issue(hrel, 0, "Se usa THREE.OrbitControls pero no se carga el archivo de OrbitControls (no viene dentro de three.js)",
                                 "Agrega después de three.min.js: <script src=\"https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/"
                                 "OrbitControls.js\"></script> (misma versión que three.js).", "web", 1))
        # funciones llamadas que no existen / no están cargadas / se cargan después
        if not skip_calls:
            reported, missing = set(), {}
            unknown_lib = [r for r in remote if not any(re.search(p_[0], r, re.I) for p_ in LIBS)]
            calls = []
            for k, rel, code, lines, off, is_mod, _d in units:
                for name, line, is_new, depth in js_calls(code):
                    calls.append((k, rel, lines, line + off, name, is_new, 1 if is_mod else depth))
            for code_h, line_h in handlers:
                for name, line, is_new, depth in js_calls(strip_js(code_h)):
                    calls.append((999, hrel, hlines, line_h, name, is_new, 1))
            for k, rel, lines, line, name, is_new, depth in calls:
                if name in page_defs or name in BUILTINS or (rel, name) in reported:
                    if name in page_defs and depth == 0 and k != 999:
                        # llamada al cargar la página a algo que se define en un script que se carga DESPUÉS
                        later = [u for u in units if u[0] > k and name in u[6]]
                        earlier = [u for u in units if u[0] <= k and name in u[6]]
                        if later and not earlier and (rel, name) not in reported:
                            reported.add((rel, name))
                            issues.append(_issue(rel, line, f"{rel}:{line} llama a {name}() al cargar la página, pero {name} se "
                                                 f"define en {later[0][1]}, que se carga DESPUÉS", f"Cambia el orden de los <script> en "
                                                 f"{hrel} (primero {later[0][1]}) o llama a {name}() dentro de "
                                                 "window.addEventListener('load', …).", "web", 1, _snip(lines, line)))
                    continue
                reported.add((rel, name))
                if len(reported) > 60:
                    break
                elsewhere = [f for f in all_defs.get(name, []) if f != rel]
                if elsewhere:
                    issues.append(_issue(rel, line, f"{rel}:{line} usa {'new ' if is_new else ''}{name}(), que está en {elsewhere[0]}, "
                                         f"pero {hrel} NO carga {elsewhere[0]}",
                                         f"Agrega <script src=\"{elsewhere[0]}\"></script> en {hrel} antes de {rel}.", "web", 1,
                                         _snip(lines, line)))
                else:
                    missing.setdefault(rel, []).append((name, line, is_new, lines))
            for rel, items in missing.items():
                sug = []
                for name, line, is_new, lines in items[:8]:
                    c = [x for x in dict.fromkeys(difflib.get_close_matches(name, list(page_defs - BUILTINS) + list(all_defs), n=3,
                                                                           cutoff=0.72)) if x.lower() != name.lower()]
                    if c:
                        sug.append(f"{name}→{c[0]}")
                names = ", ".join(f"{'new ' if n_ else ''}{nm}() (línea {ln})" for nm, ln, n_, _l in items[:8])
                name0, line0, _n, lines0 = items[0]
                issues.append(_issue(rel, line0, f"{rel} llama a {len(items)} función(es)/clase(s) que NO están definidas en ningún "
                                     f"archivo del proyecto: {names}" + (" …" if len(items) > 8 else ""),
                                     ("¿Nombres equivocados? " + ", ".join(sug) + ". " if sug else "") +
                                     "Hay que DEFINIRLAS (escribir su código) o usar las que sí existen" +
                                     (f"; si vienen de una librería externa ({unknown_lib[0][:60]}), revisa que se cargue." if unknown_lib else "."),
                                     "web", 1 if not unknown_lib else 2, _snip(lines0, line0)))
        # getElementById / querySelector('#id') de elementos que no existen
        for k, rel, code, lines, off, is_mod, _d in units:
            raw_lines = lines if rel != hrel else hlines
            raw = "\n".join(raw_lines)
            rx = re.compile(r"getElementById\(\s*[\"'`]([\w-]+)[\"'`]\s*\)|querySelector(?:All)?\(\s*[\"'`]#([\w-]+)[\"'`]\s*\)")
            seen = set()
            for m in rx.finditer(raw):
                idn = m.group(1) or m.group(2)
                if idn in all_ids or idn in dyn_ids or idn in seen:
                    continue
                seen.add(idn)
                line = raw.count("\n", 0, m.start()) + 1
                if rel == hrel and not (off < line):
                    continue
                sug = difflib.get_close_matches(idn, list(all_ids), n=2, cutoff=0.5)
                issues.append(_issue(rel, line, f"{rel}:{line} busca el elemento id=\"{idn}\" pero NO existe en el HTML "
                                     f"(devuelve null y lo siguiente falla con «Cannot read properties of null»)",
                                     (f"¿Es «{sug[0]}»? " if sug else "") + f"Agrega el elemento (ej. <canvas id=\"{idn}\">) en {hrel} "
                                     f"o corrige el id. Ids que sí existen: {', '.join(sorted(all_ids)[:10]) or 'ninguno'}.",
                                     "id", 1, _snip(raw_lines, line)))
    # scripts JS que ninguna página carga (código muerto que la IA cree que se usa)
    if htmls:
        used = set()
        for h, (src, scripts, ids, handlers) in html_info.items():
            for s in scripts:
                if s["src"] and not _is_remote(s["src"]):
                    used.add((h.parent / s["src"].split("?")[0]).resolve())
        imported = set()
        for p in js_files:
            for m in re.finditer(r"(?:import|from)\s*\(?\s*[\"'](\.{1,2}/[^\"']+)[\"']", js_info(p)[0]):
                imported.add((p.parent / m.group(1)).resolve())
        for p in js_files:
            if is_vendor(p):
                continue
            if p.resolve() not in used and p.resolve() not in imported and not re.search(r"(?i)(node_modules|server|test|config|sw|service)",
                                                                                          p.name) and len(htmls) <= 3:
                if (Path(root) / "package.json").exists():
                    continue
                issues.append(_issue(_rel(root, p), 0, f"{_rel(root, p)} no lo carga ninguna página HTML: su código nunca se ejecuta",
                                     "Si se necesita, agrégalo con <script src=\"...\"> en el HTML; si no, ignóralo.", "web", 3))
    return issues


# ───────────── Orquestación ─────────────
def run(root, ctx=None, only=None, dinamico=True, web=True, ejecutar=False, reparar=True, emit=None):
    """Diagnóstico completo. Devuelve {"problemas", "reparados", "web", "resumen"}."""
    from . import pruebas as PR
    root = Path(root)
    say = emit or (lambda t: None)
    files = [root / f for f in only] if only else _files(root, TEXT_EXT)
    files = [f for f in files if f.is_file()]
    say(f"🩺 Revisando {len(files)} archivos…")
    issues = []
    enc_issues, fixed = check_encoding(root, files, reparar, ctx)
    issues += enc_issues
    issues += check_placeholders(root, files)
    htmls = [f for f in (files if only else _files(root, {".html", ".htm"})) if f.suffix.lower() in (".html", ".htm")]
    js_files = _files(root, JS_EXT)
    if htmls:
        try:
            issues += check_web(root, htmls, js_files)
        except Exception as e:  # el análisis es una ayuda: nunca debe romper el diagnóstico
            say(f"(análisis web omitido: {type(e).__name__})")
    rels = [_rel(root, f) for f in files if f.suffix.lower() in PR.EXTS] if only else None
    res = PR.run_checks(root, only=rels, dynamic=ejecutar, allow_install=False, emit=None)
    for e in res["errores"]:
        issues.append(_issue(e["archivo"], e.get("linea") or 0, (f"{e['archivo']}:{e['linea']} " if e.get("linea") else "") + e["msg"],
                             e.get("pista", ""), e.get("tipo", "prueba"), 1 if e.get("tipo") in ("sintaxis", "ejecución", "enlace") else 2,
                             e.get("fragmento", "")))
    web_rep = None
    if dinamico and web and htmls:
        from . import navegador as NAV
        entry = next((h for h in htmls if h.name.lower() == "index.html" and h.parent == root), None) or \
            next((h for h in htmls if h.name.lower() == "index.html"), None) or htmls[0]
        if NAV.find_browser():
            say(f"🌐 Abriendo {_rel(root, entry)} en un navegador invisible para ver los errores reales…")
            try:
                r = NAV.probar(str(entry), cwd=root, captura=True, espera_ms=2500)
                web_rep = r
                for e in r.get("errores", [])[:6]:
                    loc = f"{e['archivo']}:{e['linea']}" if e.get("archivo") else _rel(root, entry)
                    issues.append(_issue(e.get("archivo") or _rel(root, entry), e.get("linea") or 0,
                                         f"Al abrir la página: {e['msg'][:220]} ({loc})", _pista_js(e["msg"]), "navegador", 0,
                                         (f">{e['linea']:>4}| {e['codigo']}" if e.get("codigo") else "")))
                for c in r.get("cargas", [])[:4]:
                    remoto = c["url"].startswith(("http://", "https://")) and "localhost" not in c["url"] and "127.0.0.1" not in c["url"]
                    red = re.search(r"INTERNET|TUNNEL|NAME_NOT_RESOLVED|CONNECTION|TIMED_OUT|PROXY|CERT", c["motivo"] or "")
                    pista = ("No hay internet o el CDN está bloqueado: descarga la librería al proyecto (descargar_archivo) y cárgala "
                             "con una ruta local." if remoto and red else
                             "Esa URL no existe (404): usa una URL válida del CDN (ej. cdnjs.cloudflare.com) con la versión correcta." if remoto else
                             "Corrige la ruta en el <script>/<link>/<img> (relativa al HTML) o crea el archivo que falta.")
                    issues.append(_issue(c["archivo"], 0, f"Al abrir la página no cargó {c['archivo']} ({c['motivo']})",
                                         pista, "carga", 0))
                if (r.get("blanca") or r.get("casi_vacia")) and not r.get("errores"):
                    issues.append(_issue(_rel(root, entry), 0, "La página abre sin errores pero " +
                                         (("el canvas del juego está " + ("VACÍO (no se dibuja nada)" if r.get("blanca") else
                                           f"casi vacío (solo {r.get('contenido_pct')}% tiene dibujo)")) if r.get("zona") == "canvas" else
                                          "se ve en blanco/de un solo color"),
                                         "Revisa que se llame a la función de inicio, que el bucle de dibujo (requestAnimationFrame) "
                                         "se ejecute y que la cámara/escena tengan objetos visibles.", "navegador", 1))
            except Exception as e:
                say(f"(no pude abrir el navegador de pruebas: {str(e)[:120]})")
    # orden: prioridad, luego tipo
    orden = {"carga": -1, "navegador": 0, "codificación": 1, "sintaxis": 1, "id": 1, "web": 2, "incompleto": 2, "enlace": 2, "nombre": 3,
             "dependencia": 3, "ejecución": 1, "seguridad": 5}
    uniq, seen = [], set()
    for i in sorted(issues, key=lambda x: (x["prioridad"], orden.get(x["tipo"], 4))):
        k = (i["archivo"], i["linea"], i["msg"][:80])
        if k not in seen:
            seen.add(k)
            uniq.append(i)
    return {"problemas": uniq, "reparados": fixed, "web": web_rep, "humo": res.get("humo")}


def _pista_js(msg):
    m = msg.lower()
    n = re.search(r"(\w+) is not defined", msg)
    if n:
        return f"«{n.group(1)}» no existe en el momento en que se usa: defínela, carga el archivo que la define ANTES, o corrige el nombre."
    if "cannot read properties of null" in m or "cannot set properties of null" in m:
        return "Un getElementById/querySelector devolvió null: el id no existe en el HTML o el script corre antes de que exista el elemento."
    if "cannot read properties of undefined" in m:
        return "Se usa una variable que todavía no tiene valor (no se inicializó o la función de inicio no se llamó)."
    if "is not a function" in m:
        return "Se llama como función algo que no lo es (nombre equivocado, falta cargar una librería o un método que no existe)."
    if "is not a constructor" in m:
        return "Se usa new con algo que no es una clase (revisa el nombre y que la librería esté cargada)."
    if "cors" in m or "origin 'null'" in m:
        return "Los módulos ES no funcionan con file://: quita type=module o sirve la carpeta con python -m http.server."
    if "unexpected token" in m or "syntaxerror" in m:
        return "Error de sintaxis: revisa llaves, paréntesis y comas en esa línea o la anterior."
    return "Corrige esa línea (lee el código alrededor con leer_archivo)."


def reporte(res, max_items=10):
    probs = res["problemas"]
    L = []
    if res.get("reparados"):
        L.append("🔧 Reparé la codificación (a UTF-8, con respaldo): " + ", ".join(res["reparados"]))
    if not probs:
        L.append("✅ DIAGNÓSTICO: no encontré problemas (codificación, código incompleto, HTML/JS, sintaxis, nombres, dependencias"
                 + (", ni errores al abrir la página" if res.get("web") else "") + ").")
        if res.get("humo"):
            L.append("Ejecución: " + res["humo"])
        return "\n".join(L)
    L.append(f"🩺 DIAGNÓSTICO: {len(probs)} problema(s) (ordenados del más importante al menos importante):")
    for i, p in enumerate(probs[:max_items], 1):
        L.append(f"\n{i}) {p['msg']}")
        if p.get("fragmento"):
            L.append(p["fragmento"])
        if p.get("pista"):
            L.append(f"   → Cómo arreglarlo: {p['pista']}")
    if len(probs) > max_items:
        L.append(f"\n… y {len(probs) - max_items} más (vuelve a diagnosticar después de corregir estos).")
    w = res.get("web")
    if w and (w.get("info") or {}).get("title") is not None:
        info = w["info"]
        L.append(f"\n🌐 Página abierta en el navegador de pruebas: título «{info.get('title', '')}», "
                 f"{len(info.get('canvas') or [])} canvas, {'pantalla VACÍA' if w.get('blanca') else 'con contenido'}.")
    L.append("\nPLAN: corrige de uno en uno empezando por el 1 (suele causar los siguientes) con editar_archivo "
             "(o escribir_archivo si falta el archivo), y vuelve a ejecutar diagnosticar/probar_web para verificar.")
    return "\n".join(L)
