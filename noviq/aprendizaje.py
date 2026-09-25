# -*- coding: utf-8 -*-
"""Agente de aprendizaje (sin LLM, vive dentro de Noviark y aprende solo).

Cómo aprende:
  1. Cuando una herramienta falla, extrae la FIRMA del error (el tipo de error normalizado, sin rutas ni nombres
     concretos) y la deja "abierta" en la conversación.
  2. Anota los pasos que da la IA después (ediciones, comandos, instalaciones).
  3. Cuando la verificación vuelve a salir bien (el mismo comando/prueba ya no da ese error), guarda la lección:
     firma → pasos que la resolvieron. Cuantas más veces funciona una solución, más peso tiene.
  4. La próxima vez que aparezca ese error (en cualquier proyecto y con cualquier IA), Noviark le pasa a la IA
     la solución que ya funcionó, junto al error. Las lecciones más probadas se vuelven "reglas" del sistema.
  5. También aprende qué paquete de pip corresponde a cada módulo (ej. cv2 → opencv-python).

Es a prueba de fallos: todo está protegido; si algo falla aquí, el agente principal sigue normal.
Se puede revisar, borrar o apagar en 🧬 Aprendizaje.
"""
import json
import re
import threading
import time

from .config import CONFIG, DATA_DIR

FILE = DATA_DIR / "aprendizaje.json"
_lock = threading.Lock()
_db = None
MAX_LECCIONES = 500

# Conocimiento base (pre-entrenado): errores típicos en Windows y su solución probada
BASE = [
    ("modulenotfounderror: no module named <x>",
     "Instala el paquete en el entorno del proyecto: ejecutar_powershell «python -m pip install <paquete>» (ojo: cv2→opencv-python, "
     "PIL→pillow, yaml→pyyaml, sklearn→scikit-learn, bs4→beautifulsoup4) y vuelve a ejecutar."),
    ("no se reconoce como nombre de un cmdlet",
     "El programa no está instalado o no está en el PATH. Para Python usa «py» o la ruta completa; para Node instálalo con "
     "«winget install OpenJS.NodeJS.LTS»; reabre la terminal tras instalar."),
    ("is not recognized as the name of a cmdlet",
     "El programa no está instalado o no está en el PATH (usa «py» en vez de «python», o instala con winget)."),
    ("unicodeencodeerror: <x> codec can't encode character",
     "Windows usa cp1252: abre/escribe archivos con encoding='utf-8' y ejecuta con la variable PYTHONIOENCODING=utf-8."),
    ("cannot be loaded because running scripts is disabled on this system",
     "Ejecuta el script con «powershell -ExecutionPolicy Bypass -File script.ps1» (sin cambiar la política global)."),
    ("oserror: [errno <n>] address already in use",
     "El puerto está ocupado: usa otro puerto o cierra el proceso que lo usa (procesos → detener)."),
    ("error: cannot find module <x>",
     "Falta la dependencia de Node: ejecuta «npm install» en la carpeta del proyecto (o «npm install <paquete>»)."),
    ("syntaxerror: invalid syntax",
     "Revisa la línea indicada y la anterior (paréntesis/comillas sin cerrar, dos puntos faltantes). Corrige solo esas líneas con editar_archivo."),
    ("indentationerror: <x>",
     "Mezcla de tabs/espacios o bloque mal sangrado: re-sangra SOLO el bloque indicado con 4 espacios."),
    ("filenotfounderror: [errno <n>] no such file or directory",
     "La ruta no existe: usa rutas relativas a la carpeta del proyecto (Path(__file__).parent / 'archivo') y crea las carpetas con mkdir(parents=True)."),
]

ERR_LINE = re.compile(r"((?:[A-Z]\w*(?:Error|Exception|Warning))\s*:.*|error(?: TS\d+)?:.*|npm err!.*|fatal:.*|"
                      r".*no se reconoce como.*|.*is not recognized as.*|.*command not found.*|.*cannot be loaded because.*|"
                      r".*no such file or directory.*|.*permission denied.*|.*access is denied.*|.*acceso denegado.*|"
                      r".*segmentation fault.*|.*undefined reference.*|.*referenceerror.*|.*typeerror.*)", re.I)
VERIFY = {"ejecutar_python", "ejecutar_powershell", "probar_proyecto", "prueba_auto"}
FIX = {"escribir_archivo", "editar_archivo", "deshacer_cambio", "ejecutar_powershell", "ejecutar_python", "crear_proyecto"}


def activo():
    return CONFIG.get("aprendizaje", True) is not False


def _load():
    global _db
    if _db is None:
        try:
            _db = json.loads(FILE.read_text(encoding="utf-8"))
        except Exception:
            _db = {}
        _db.setdefault("lecciones", {})
        _db.setdefault("pip", {})
        _db.setdefault("stats", {"errores": 0, "resueltos": 0})
        for f, sol in BASE:
            _db["lecciones"].setdefault(f, {"firma": f, "ejemplo": "", "herramienta": "", "fuente": "base",
                                            "soluciones": [{"pasos": sol, "veces": 1}], "vistas": 0, "resueltas": 1, "t": 0})
    return _db


def _save():
    try:
        L = _db["lecciones"]
        if len(L) > MAX_LECCIONES:  # olvida lo menos útil
            keep = sorted(L.values(), key=lambda x: (x.get("fuente") == "base", x.get("resueltas", 0), x.get("t", 0)), reverse=True)
            _db["lecciones"] = {x["firma"]: x for x in keep[:MAX_LECCIONES]}
        tmp = FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_db, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(FILE)
    except Exception:
        pass


def firma(texto):
    """Firma normalizada del error más relevante del texto (o None)."""
    try:
        t = str(texto or "")
        if not t:
            return None, None
        cands = [m.group(1).strip() for m in ERR_LINE.finditer(t[-6000:])]
        cands = [c for c in cands if len(c) > 8]
        if not cands:
            if t.startswith("ERROR"):
                cands = [t.split("\n", 1)[0][6:]]
            else:
                return None, None
        line = cands[-1][:300]
        extra = None
        m = re.search(r"no module named ['\"]?([\w.]+)", line, re.I)
        if m:
            extra = m.group(1).split(".")[0]
        f = re.sub(r"\.?\s*did you mean:? .*$|\(did you mean.*$", "", line.lower())
        f = re.sub(r"'[^']*'|\"[^\"]*\"|«[^»]*»|`[^`]*`", "<x>", f)
        f = re.sub(r"[a-z]:\\[^\s,;:]+|/[\w./-]{3,}", "<ruta>", f)
        f = re.sub(r"0x[0-9a-f]+|\b\d+\b", "<n>", f)
        f = re.sub(r"\s+", " ", f).strip(" .:")[:160]
        if len(f) < 6:
            return None, None
        return f, extra
    except Exception:
        return None, None


def _cmd0(name, args):
    a = args or {}
    c = str(a.get("comando") or a.get("ruta") or "").strip().lower()
    return name + ":" + (re.split(r"[\s\\/]+", c)[0] if c else "")


def _paso(name, args):
    a = args or {}
    det = a.get("ruta") or a.get("comando") or (a.get("codigo") or "")[:80] or a.get("accion") or ""
    det = re.sub(r"\s+", " ", str(det))[:110]
    if name == "editar_archivo":
        return f"editar {det}"
    if name == "escribir_archivo":
        return f"reescribir {det}"
    if name == "ejecutar_powershell":
        return f"comando «{det}»"
    if name == "ejecutar_python":
        return f"python «{det}»"
    return f"{name} {det}".strip()


def _match(f):
    L = _load()["lecciones"]
    if f in L:
        return L[f]
    for k, v in L.items():  # coincidencia parcial con las lecciones base (más generales)
        base = k.replace("<x>", "").replace("<n>", "").strip()
        if v.get("fuente") == "base" and base and base in f.replace("<x>", "").replace("<n>", ""):
            return v
    return None


def hint(f):
    try:
        v = _match(f)
        if not v or v.get("resueltas", 0) < 1:
            return ""
        sols = sorted(v.get("soluciones") or [], key=lambda s: -s.get("veces", 0))
        # «editar X → reescribir Y» de OTRO proyecto no enseña nada (y confunde): solo sirven pasos concretos
        sols = [s for s in sols if not all(p.strip().startswith(("editar ", "reescribir ", "leer ")) for p in s["pasos"].split(" → "))][:2]
        if not sols:
            return ""
        txt = " | ".join(s["pasos"][:260] for s in sols)
        src = "conocimiento base" if v.get("fuente") == "base" else f"este error ya se resolvió {v.get('resueltas', 0)} vez(es) en este PC; lo que funcionó"
        return f"\n\n💡 APRENDIZAJE ({src}): {txt}"
    except Exception:
        return ""


def on_result(conv, name, args, result):
    """Llamar tras cada herramienta. Devuelve una pista (texto) para añadir al resultado, o ''."""
    if not activo():
        return ""
    try:
        with _lock:
            db = _load()
            st = conv.setdefault("_apr", {"abiertos": []})
            ab = st["abiertos"]
            res = str(result or "")
            is_err = res.startswith(("ERROR", "✗")) or "Traceback (most recent call last)" in res \
                or bool(re.search(r"c[óo]digo de salida:? ?[1-9]|exit code:? ?[1-9]|\[PRUEBA AUTOM", res, re.I))
            if name in ("leer_archivo", "listar_directorio", "buscar_en_archivos", "actualizar_tareas", "memoria", "mapa_codigo"):
                return ""
            if is_err and name in ("editar_archivo", "escribir_archivo", "deshacer_cambio") and \
                    re.search(r"texto_anterior|ya existe y tiene|aparece \d+ veces|no hay copias", res):
                return ""  # errores de uso de la herramienta: su propio mensaje ya dice qué hacer
            if is_err:
                f, extra = firma(res)
                if not f:
                    return ""
                db["stats"]["errores"] = db["stats"].get("errores", 0) + 1
                v = db["lecciones"].get(f)
                if v:
                    v["vistas"] = v.get("vistas", 0) + 1
                if not any(a["firma"] == f for a in ab):
                    ab.append({"firma": f, "extra": extra, "tool": name, "cmd0": _cmd0(name, args), "ejemplo": res[:300], "pasos": [], "t": time.time()})
                    del ab[:-6]
                for a in ab:  # si falló una acción de arreglo, igual cuenta como intento
                    if a["firma"] != f and name in FIX:
                        a["pasos"].append(_paso(name, args) + " (falló)")
                return hint(f)
            # éxito
            pip = re.search(r"pip(?:3)?\s+install\s+(?:-[\w-]+\s+)*([A-Za-z0-9_.\-\[\]]+)", str((args or {}).get("comando", "")))
            if pip:
                for a in ab:
                    if a.get("extra") and a["extra"].lower() != pip.group(1).lower().split("[")[0]:
                        db["pip"][a["extra"]] = pip.group(1)
            if name in VERIFY:
                c0 = _cmd0(name, args)
                solved = [a for a in ab if (a["tool"] == name and a.get("cmd0") == c0) or name == "probar_proyecto"
                          or (a["tool"] == "prueba_auto" and name == "prueba_auto")]
                for a in solved:
                    _learn(a)
                    ab.remove(a)
                if solved:
                    _save()
            if name in FIX:
                for a in ab:
                    a["pasos"].append(_paso(name, args))
                    del a["pasos"][:-8]
            return ""
    except Exception:
        return ""


def _learn(a):
    pasos = [p for p in a.get("pasos") or [] if not p.endswith("(falló)")]
    if not pasos:
        return
    db = _load()
    txt = " → ".join(dict.fromkeys(pasos))[:400]
    v = db["lecciones"].setdefault(a["firma"], {"firma": a["firma"], "ejemplo": a.get("ejemplo", "")[:300],
                                                "herramienta": a.get("tool", ""), "fuente": "aprendido",
                                                "soluciones": [], "vistas": 1, "resueltas": 0, "t": 0})
    v["resueltas"] = v.get("resueltas", 0) + 1
    v["t"] = time.time()
    gen = re.sub(r"«[^»]*»", "«…»", txt) if len(txt) > 200 else txt
    for s in v["soluciones"]:
        if s["pasos"] == txt or s["pasos"] == gen:
            s["veces"] += 1
            break
    else:
        v["soluciones"].append({"pasos": txt, "veces": 1})
        v["soluciones"] = sorted(v["soluciones"], key=lambda s: -s["veces"])[:4]
    db["stats"]["resueltos"] = db["stats"].get("resueltos", 0) + 1


def resolve_all(conv):
    """Las pruebas finales pasaron: todo error abierto quedó resuelto por los pasos anotados."""
    if not activo():
        return
    try:
        with _lock:
            ab = (conv.get("_apr") or {}).get("abiertos") or []
            for a in list(ab):
                _learn(a)
                ab.remove(a)
            _save()
    except Exception:
        pass


def reglas(max_chars=700):
    """Lecciones más probadas (aprendidas en este PC) para incluir en el prompt del sistema."""
    if not activo():
        return ""
    try:
        L = [v for v in _load()["lecciones"].values() if v.get("fuente") != "base" and v.get("resueltas", 0) >= 2]
        L.sort(key=lambda v: (-v["resueltas"], -v.get("t", 0)))
        out, n = [], 0
        for v in L:
            s = f"- Si ves «{v['firma'][:90]}»: {v['soluciones'][0]['pasos'][:160]}"
            if n + len(s) > max_chars:
                break
            out.append(s)
            n += len(s)
        return ("LECCIONES APRENDIDAS EN ESTE PC (soluciones que ya funcionaron):\n" + "\n".join(out)) if out else ""
    except Exception:
        return ""


def pip_name(module):
    try:
        return _load()["pip"].get(module)
    except Exception:
        return None


def listar():
    with _lock:
        db = _load()
        L = sorted(db["lecciones"].values(), key=lambda v: (v.get("fuente") == "base", -v.get("resueltas", 0), -v.get("t", 0)))
        return {"lecciones": L, "pip": db["pip"], "stats": db["stats"], "activo": activo()}


def borrar(f=None):
    global _db
    with _lock:
        db = _load()
        if f:
            db["lecciones"].pop(f, None)
        else:
            _db = None
            try:
                FILE.unlink()
            except OSError:
                pass
            _load()
        _save()
