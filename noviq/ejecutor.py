# -*- coding: utf-8 -*-
"""Agente ejecutor: cuando la IA principal responde con bloques de código en texto en lugar de usar
herramientas, este agente reconoce cada bloque (inicio, fin, lenguaje y nombre de archivo) y lo convierte
en acciones reales: guardar archivos, ejecutar comandos o scripts. Los resultados vuelven a la IA principal
para que continúe su plan (corregir errores, seguir con el siguiente paso)."""
import json
import re
import uuid

from .config import CONFIG, project_path, projects_root

FENCE = re.compile(r"(?ms)^[ \t]*(```|~~~)[ \t]*([\w+#.\-]*)[^\n]*\n(.*?)^[ \t]*\1[ \t]*$")
EXTS = ("py|pyw|js|mjs|cjs|jsx|ts|tsx|html|htm|css|scss|json|md|txt|csv|xml|yml|yaml|toml|ini|cfg|env|sql|sh|bat|cmd|"
        "ps1|psm1|java|kt|kts|cs|csproj|sln|cpp|cc|c|h|hpp|go|rs|rb|php|ino|dart|swift|lua|r|vb|vue|svelte|gradle|"
        "properties|dockerfile|gitignore|makefile|conf|svg")
NAME = rf"((?:[A-Za-z]:)?[\w\-./\\]*[\w\-]+\.(?:{EXTS})|Dockerfile|Makefile|\.gitignore|\.env)"
HINTS = [
    re.compile(rf"(?i)(?:archivo|fichero|file|guardar? como|save as|crea(?:r)?|nombre)\s*[:\-]?\s*[`*\"']*{NAME}"),
    re.compile(rf"[`*]{{1,2}}{NAME}[`*]{{1,2}}"),
    re.compile(rf"^\s*#+\s*{NAME}\s*$", re.M),
    re.compile(rf"^\s*{NAME}\s*:?\s*$", re.M),
]
FIRST_LINE = re.compile(rf"^\s*(?:#|//|--|;|<!--|/\*|REM|::)\s*(?:archivo|file|fichero|nombre)?\s*:?\s*{NAME}\s*(?:-->|\*/)?\s*$", re.I)
SHELL = {"powershell", "ps1", "ps", "pwsh", "cmd", "bat", "batch", "shell", "bash", "sh", "console", "terminal",
         "shell-session", "zsh"}
RUN_INTENT = re.compile(r"(?i)\b(ejecut\w*|corr[ea]\w*|prueb\w*|run|execute|resultado|salida|output|instal\w*)\b")
LANG_EXT = {"python": ".py", "py": ".py", "javascript": ".js", "js": ".js", "typescript": ".ts", "ts": ".ts",
            "html": ".html", "css": ".css", "json": ".json", "java": ".java", "csharp": ".cs", "cs": ".cs",
            "cpp": ".cpp", "c": ".c", "go": ".go", "rust": ".rs", "php": ".php", "arduino": ".ino", "ino": ".ino",
            "sql": ".sql", "kotlin": ".kt", "dart": ".dart", "ruby": ".rb", "lua": ".lua"}
TIPO_BY_EXT = [((".ino",), "arduino"), ((".cs", ".csproj"), "csharp"), ((".java",), "java"), ((".kt", ".gradle"), "android"),
               ((".py",), "python"), ((".ts", ".tsx", ".jsx", ".mjs"), "node"), ((".html", ".htm", ".css", ".js"), "web")]


def extract_blocks(text):
    blocks, last_end = [], 0
    for m in FENCE.finditer(text or ""):
        lang = (m.group(2) or "").lower().strip(".")
        code = m.group(3)
        before = text[max(last_end, m.start() - 300):m.start()]
        last_end = m.end()
        name = None
        first = code.split("\n", 1)[0] if code else ""
        fm = FIRST_LINE.match(first)
        if fm:
            name = fm.group(1)
        else:
            tail = "\n".join(before.rstrip().split("\n")[-2:])
            for rx in HINTS:
                hm = list(rx.finditer(tail))
                if hm:
                    name = hm[-1].group(1)
                    break
        blocks.append({"lang": lang, "code": code.rstrip("\n") + "\n", "name": name, "before": before})
    return blocks


def _slug(text):
    words = re.findall(r"[A-Za-zÁÉÍÓÚáéíóúñÑ0-9]+", text or "")
    stop = {"crea", "crear", "creame", "hazme", "haz", "un", "una", "el", "la", "los", "las", "de", "del", "en", "con",
            "que", "para", "por", "programa", "mi", "me", "y", "a", "al", "quiero", "necesito", "puedes", "porfa", "favor"}
    keep = [w.capitalize() for w in words if w.lower() not in stop][:4]
    return "_".join(keep) or "Proyecto"


def _call(name, args):
    return {"id": f"ejec_{uuid.uuid4().hex[:10]}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}


def synthesize(text, conv, mode, cwd=None):
    """Convierte los bloques de código de la respuesta en llamadas a herramientas. Devuelve [] si no aplica."""
    setting = CONFIG.get("ejecutor", "auto")
    if setting == "nunca":
        return []
    blocks = extract_blocks(text)
    if not blocks:
        return []
    allow_exec = setting == "siempre" or mode in ("texto", "ninguno")
    calls, files = [], []
    for b in blocks:
        lang, code, name = b["lang"], b["code"], b["name"]
        if not code.strip():
            continue
        if name:
            if cwd is not None and conv.get("project"):
                p = cwd / name.replace("\\", "/")
                if p.is_file():
                    try:
                        existing = p.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        existing = ""
                    # es un fragmento/resumen de un archivo que ya existe: no lo pisa
                    if code.strip() in existing or code.count("\n") < 0.5 * existing.count("\n"):
                        continue
            if FIRST_LINE.match(code.split("\n", 1)[0]) and name.lower().endswith(".json"):
                code = code.split("\n", 1)[1] if "\n" in code else code
            files.append(name)
            calls.append(_call("escribir_archivo", {"ruta": name.replace("\\", "/"), "contenido": code, "sobrescribir": True}))
        elif lang in SHELL and allow_exec:
            calls.append(_call("ejecutar_powershell", {"comando": code.strip(),
                                                       "explicacion": "Agente ejecutor: comando propuesto por la IA"}))
        elif lang in ("python", "py") and allow_exec and RUN_INTENT.search(b["before"][-250:]):
            calls.append(_call("ejecutar_python", {"codigo": code, "explicacion": "Agente ejecutor: script propuesto por la IA"}))
        elif lang in ("html", "htm") and re.search(r"(?i)<!doctype html|<html", code) and allow_exec:
            files.append("index.html")
            calls.append(_call("escribir_archivo", {"ruta": "index.html", "contenido": code, "sobrescribir": True}))
    if not calls:
        return []
    if files and not conv.get("project"):
        pedido = ((conv.get("estado") or {}).get("pedidos") or [{}])[0].get("texto", "") or conv.get("title", "")
        exts = tuple(("." + f.rsplit(".", 1)[-1].lower()) for f in files if "." in f)
        tipo = next((t for keys, t in TIPO_BY_EXT if any(e in keys for e in exts)), "general")
        name = _slug(pedido)
        if project_path(name).exists():
            calls.insert(0, _call("cambiar_proyecto", {"nombre": name}))
        else:
            calls.insert(0, _call("crear_proyecto", {"nombre": name, "tipo": tipo, "descripcion": pedido[:200]}))
    return calls


def results_note():
    return ("[AGENTE EJECUTOR] Tu respuesta tenía bloques de código y los apliqué por ti (arriba están los resultados). "
            "Continúa con el plan: corrige los errores que aparezcan y sigue con el siguiente paso. "
            "Recuerda que puedes usar las herramientas directamente.")
