# -*- coding: utf-8 -*-
"""Agente indexador (sin LLM): resume cada archivo de código en una línea súper compacta
(funciones con sus parámetros, clases con sus métodos, imports clave). Con esto la IA local
sabe qué hay en el proyecto sin leer todo el código (ahorra miles de tokens).
Usa el AST de Python para .py y expresiones regulares para los demás lenguajes. Caché por fecha."""
import ast
import json
import os
import re
from pathlib import Path

SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".gradle", "bin", "obj",
        ".idea", ".vs", ".noviq", ".rurak", ".nvchat", ".pytest_cache", ".mypy_cache", "imagenes", "capturas"}
CODE_EXT = {".py", ".js", ".mjs", ".jsx", ".ts", ".tsx", ".html", ".htm", ".css", ".json", ".cs", ".java", ".kt",
            ".php", ".ps1", ".go", ".rs", ".dart", ".ino", ".cpp", ".c", ".h", ".vue", ".sql", ".bat", ".sh", ".md",
            ".toml", ".yml", ".yaml", ".txt", ".ini", ".xml", ".gradle"}
RX = {
    "js": re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)|^\s*(?:export\s+)?class\s+(\w+)|"
                     r"^\s*(?:export\s+)?(?:const|let)\s+(\w+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>"),
    "cs": re.compile(r"^\s*(?:public|private|protected|internal|static|override|async|virtual|\s)+[\w<>\[\],]+\s+(\w+)\s*\(([^)]*)\)|^\s*(?:public\s+)?(?:class|interface|record)\s+(\w+)"),
    "php": re.compile(r"^\s*(?:public|private|protected|static|\s)*function\s+(\w+)\s*\(([^)]*)\)|^\s*class\s+(\w+)"),
    "ps1": re.compile(r"^\s*function\s+([\w-]+)"),
    "go": re.compile(r"^func\s+(?:\([^)]*\)\s*)?(\w+)\s*\(([^)]*)\)|^type\s+(\w+)"),
    "c": re.compile(r"^[\w\*\s]+\s(\w+)\s*\(([^;{]*)\)\s*\{?\s*$"),
}
EXT_RX = {".js": "js", ".mjs": "js", ".jsx": "js", ".ts": "js", ".tsx": "js", ".vue": "js", ".cs": "cs", ".java": "cs",
          ".kt": "cs", ".dart": "cs", ".php": "php", ".ps1": "ps1", ".go": "go", ".ino": "c", ".cpp": "c", ".c": "c"}


def _args(a: ast.arguments):
    names = [x.arg for x in a.posonlyargs + a.args if x.arg not in ("self", "cls")]
    if a.vararg:
        names.append("*" + a.vararg.arg)
    names += [x.arg for x in a.kwonlyargs]
    return ",".join(names)


def summarize_py(src):
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return f"⚠ error de sintaxis línea {e.lineno}"
    parts, imps = [], set()
    for n in tree.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            mod = (n.module if isinstance(n, ast.ImportFrom) else n.names[0].name) or ""
            imps.add(mod.split(".")[0])
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parts.append(f"{n.name}({_args(n.args)})@{n.lineno}")
        elif isinstance(n, ast.ClassDef):
            meths = [m.name for m in n.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and not m.name.startswith("__")]
            parts.append(f"class {n.name}@{n.lineno}[{','.join(meths[:10])}{',…' if len(meths) > 10 else ''}]")
        elif isinstance(n, ast.If):
            try:
                if "__main__" in ast.unparse(n.test):
                    parts.append("[main]")
            except Exception:
                pass
    s = " ".join(parts)
    if imps:
        s += " | usa " + ",".join(sorted(i for i in imps if i)[:8])
    return s


def summarize_other(path: Path, src):
    ext = path.suffix.lower()
    if ext in (".html", ".htm"):
        title = re.search(r"<title>(.*?)</title>", src, re.I | re.S)
        refs = re.findall(r'(?:src|href)=["\']([^"\':#?]+\.(?:js|css))["\']', src)
        ids = re.findall(r'id=["\']([\w-]+)["\']', src)
        return f"título «{(title.group(1).strip() if title else '')[:40]}» enlaza {','.join(refs[:6])} ids {','.join(ids[:8])}"
    if ext == ".css":
        sels = re.findall(r"^\s*([.#]?[\w-][^{,]{0,30})\s*\{", src, re.M)
        return "selectores " + ",".join(s.strip() for s in sels[:10])
    if ext == ".json":
        try:
            j = json.loads(src)
            return "claves " + ",".join(list(j)[:12]) if isinstance(j, dict) else f"lista de {len(j)}"
        except Exception:
            return "⚠ JSON inválido"
    rx = RX.get(EXT_RX.get(ext, ""))
    if not rx:
        first = next((l.strip() for l in src.splitlines() if l.strip()), "")
        return first[:80]
    out = []
    for i, line in enumerate(src.splitlines(), 1):
        m = rx.match(line)
        if m:
            g = [x for x in m.groups() if x is not None]
            if not g or g[0] in ("if", "for", "while", "switch", "return", "catch"):
                continue
            out.append(f"{g[0]}({g[1].strip()[:30]})@{i}" if len(g) > 1 else f"{g[0]}@{i}")
        if len(out) >= 14:
            out.append("…")
            break
    return " ".join(out)


def iter_files(root: Path, limit=400):
    n = 0
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if d not in SKIP and not d.startswith("."))
        for f in sorted(fns):
            p = Path(dp) / f
            if p.suffix.lower() in CODE_EXT and not f.startswith(".noviq_tmp"):
                yield p
                n += 1
                if n >= limit:
                    return


def build(root: Path, meta_dir: Path = None):
    """Devuelve {ruta_relativa: {"l": líneas, "r": resumen, "m": mtime}} usando caché."""
    cache_f = meta_dir / "indice.json" if meta_dir else None
    cache = {}
    if cache_f and cache_f.exists():
        try:
            cache = json.loads(cache_f.read_text(encoding="utf-8"))
        except Exception:
            cache = {}
    out = {}
    for p in iter_files(root):
        rel = p.relative_to(root).as_posix()
        try:
            st = p.stat()
        except OSError:
            continue
        c = cache.get(rel)
        if c and c.get("m") == st.st_mtime:
            out[rel] = c
            continue
        if st.st_size > 600_000:
            out[rel] = {"l": 0, "r": f"(grande, {st.st_size // 1024} KB)", "m": st.st_mtime}
            continue
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        r = summarize_py(src) if p.suffix.lower() == ".py" else summarize_other(p, src)
        out[rel] = {"l": src.count("\n") + 1, "r": r, "m": st.st_mtime}
    if cache_f:
        try:
            cache_f.parent.mkdir(parents=True, exist_ok=True)
            cache_f.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return out


def compact_map(root: Path, meta_dir: Path = None, max_chars=1800, focus=()):
    """Mapa del proyecto en muy pocos tokens. Los archivos de 'focus' van primero y más completos."""
    idx = build(root, meta_dir)
    if not idx:
        return ""
    lines = []
    order = sorted(idx, key=lambda k: (0 if any(f and (k == f or k.endswith("/" + f)) for f in focus) else 1,
                                       k.count("/"), k))
    total = 0
    for rel in order:
        e = idx[rel]
        ln = f"{rel} ({e['l']}l): {e['r']}".rstrip(": ")
        ln = ln[:260]
        if total + len(ln) > max_chars:
            lines.append(f"… y {len(order) - len(lines)} archivos más (usa mapa_codigo o listar_directorio)")
            break
        lines.append(ln)
        total += len(ln) + 1
    return "\n".join(lines)
