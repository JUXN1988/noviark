# -*- coding: utf-8 -*-
"""Decisor «System One»: decisiones rápidas y tipadas (sí/no, elegir una opción, puntuar) en vez de texto.

Inspirado en Jev (TypeSafe AI, septiembre 2026): un modelo que no escribe, DECIDE, con probabilidades calibradas,
en ~0,1-0,5 s y a una fracción del costo de un LLM. Noviark lo usa en los puntos de decisión del agente:
  - ¿Esta acción es peligrosa o irreversible?  (antes de ejecutar comandos: guardarraíl)
  - ¿El pedido es un trabajo de varios pasos que merece plan?  (activar el cerebro y la revisión del plan)
  - ¿Qué tan complejo es?  (bajo / medio / alto → no gastar un modelo razonador en un saludo)
  - ¿Qué tipo de error es?  (dependencia, sintaxis, nombre, ruta, permiso, red, lógica, entorno)

Motores (el primero disponible):
  1. Jev de TypeSafe, si pones su clave (🎁 IA gratis → Decisiones). Es de pago por uso pero muy barato.
  2. Reglas locales (sin IA, sin internet, instantáneas): siempre disponibles y siempre se aplican como
     guardarraíl, porque «el texto adversario puede mover a Jev» (recomendación del propio fabricante).
"""
import re
import threading
import time

import requests

from .config import CONFIG

API = "https://api.typesafe.ai/v1/systemone"
_stats = {"jev": 0, "reglas": 0, "errores_jev": 0, "ultimo_error": ""}
_lock = threading.Lock()


def _key():
    try:
        from . import vault
        ks = vault.get_keys("typesafe")
        return ks[0] if ks else None
    except Exception:
        return None


def activo_jev():
    p = CONFIG["providers"].get("typesafe") or {}
    return bool(p.get("enabled") and _key())


def estado():
    return {"motor": "Jev (TypeSafe)" if activo_jev() else "Reglas locales", **_stats}


def _jev(state, questions, timeout=6):
    """questions: {nombre: {"tipo": "noul"|"choice"|"score", "instrucciones": str, "opciones": [...]}}
    Devuelve {nombre: {"valor", "confianza"}} o None si falla."""
    body = {"model": (CONFIG["providers"].get("typesafe") or {}).get("modelo") or "jev-latest", "state": state[:12000], "questions": {}}
    for n, q in questions.items():
        t = q.get("tipo", "noul")
        d = {"type": t, "instructions": q.get("instrucciones", "")}
        if t in ("choice", "score"):
            d["criteria" if t == "choice" else "levels"] = {o: o for o in q.get("opciones") or []}
        body["questions"][n] = d
    try:
        r = requests.post(API, json=body, headers={"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"},
                          timeout=timeout)
        if r.status_code != 200:
            raise RuntimeError(f"{r.status_code}: {r.text[:200]}")
        j = r.json()
    except Exception as e:
        _stats["errores_jev"] += 1
        _stats["ultimo_error"] = str(e)[:200]
        return None
    out = {}
    buckets = [j] + [j.get(k) for k in ("answers", "results", "nouls", "choices", "scores", "questions") if isinstance(j.get(k), dict)]
    for n, q in questions.items():
        v = next((b[n] for b in buckets if isinstance(b, dict) and n in b), None)
        if v is None:
            continue
        if isinstance(v, dict):
            conf = v.get("confidence") or v.get("probability")
            if q.get("tipo", "noul") == "noul":
                pv = v.get("noul", v.get("probability", v.get("value")))
                val = float(pv) if isinstance(pv, (int, float)) else bool(pv)
            else:
                val = v.get("choice") or v.get("score") or v.get("selected") or v.get("value") or v.get("level")
            out[n] = {"valor": val, "confianza": conf}
        else:
            out[n] = {"valor": v, "confianza": None}
    return out or None


def decidir(state, questions, reglas):
    """reglas: {nombre: función(state) → valor}. Devuelve {nombre: {"valor", "confianza", "fuente"}}.
    Si Jev está activo se usa; lo que no responda (o si falla) lo deciden las reglas."""
    res = {}
    if activo_jev():
        t0 = time.time()
        j = _jev(state, questions)
        if j:
            with _lock:
                _stats["jev"] += 1
            for n, v in j.items():
                res[n] = dict(v, fuente="jev", ms=int((time.time() - t0) * 1000))
    for n in questions:
        if n not in res and n in reglas:
            with _lock:
                _stats["reglas"] += 1
            try:
                res[n] = {"valor": reglas[n](state), "confianza": None, "fuente": "reglas"}
            except Exception:
                pass
    return res


# ───────────── Decisiones concretas que usa Noviark ─────────────
PELIGRO = re.compile(
    r"(Remove-Item\b[^|;\n]*-Recurse|rm\s+-[a-z]*r[a-z]*f|rm\s+-rf|\brmdir\s+/s|\bdel\s+/[sq]|\bformat\s+[a-z]:|diskpart|"
    r"Format-Volume|Clear-Disk|Initialize-Disk|reg\s+delete|Remove-ItemProperty\s+.*HKLM|Stop-Computer|Restart-Computer|"
    r"shutdown\s+/[sr]|\bshutdown\b|bcdedit|cipher\s+/w|vssadmin\s+delete|wmic\s+shadowcopy|Set-ExecutionPolicy\s+Unrestricted|"
    r"git\s+push\s+.*--force|git\s+reset\s+--hard|git\s+clean\s+-[a-z]*f|DROP\s+(TABLE|DATABASE)|TRUNCATE\s+TABLE|"
    r"winget\s+uninstall|Uninstall-Package|takeown|icacls\s+.*\/grant\s+Everyone|mkfs\.|dd\s+if=|:\(\)\{|chmod\s+-R\s+777\s+/|"
    r"Disable-WindowsOptionalFeature|netsh\s+advfirewall\s+set\s+.*off|Set-MpPreference\s+-Disable)", re.I)
SISTEMA = re.compile(r"([A-Za-z]:\\(Windows|Program Files|ProgramData)|%SystemRoot%|\$env:SystemRoot|/etc/|/usr/|/boot/|HKLM:)", re.I)
PLAN_RX = re.compile(r"\b(crea|cre[ae]r|cr[eé]ame|haz|hac(er|me|erme)|desarroll|program|constru|implement|diseñ|arma|genera|"
                     r"migra|refactoriz|rehac|necesito (una?|un) |quiero (una?|un) |app|aplicaci[oó]n|sistema|p[aá]gina web|juego|bot\b)", re.I)
SALUDO = re.compile(r"^\s*(hola|buenas|hey|gracias|ok|vale|perfecto|genial|qu[eé] tal|c[oó]mo est[aá]s)\b[\s!.?]*$", re.I)
TIPOS_ERROR = ["dependencia", "sintaxis", "nombre", "ruta", "permiso", "red", "memoria", "entorno", "logica"]


def _riesgo_reglas(state):
    if PELIGRO.search(state):
        return "alto"
    if SISTEMA.search(state) and re.search(r"(Remove|Set-|New-|Copy|Move|del |rm |>|Out-File|reg add)", state, re.I):
        return "alto"
    if re.search(r"(Remove-Item|\brm\b|\bdel\b|Stop-Process|taskkill|pip uninstall|npm uninstall)", state, re.I):
        return "medio"
    return "bajo"


def riesgo(nombre_herramienta, args):
    """bajo / medio / alto para una acción del agente."""
    state = f"Herramienta: {nombre_herramienta}\n" + "\n".join(f"{k}: {str(v)[:3000]}" for k, v in (args or {}).items())
    reglas_v = _riesgo_reglas(state)
    if reglas_v == "alto":  # las reglas deterministas mandan: el texto adversario no puede bajar este nivel
        return "alto", "reglas"
    r = decidir(state, {"riesgo": {"tipo": "score", "opciones": ["bajo", "medio", "alto"],
                                   "instrucciones": "¿Qué tan peligrosa o irreversible es esta acción en la PC del usuario? "
                                                    "alto = borra datos, cambia el sistema o no se puede deshacer."}},
                {"riesgo": lambda s: reglas_v})
    v = str((r.get("riesgo") or {}).get("valor") or reglas_v).lower()
    v = v if v in ("bajo", "medio", "alto") else reglas_v
    return (max(v, reglas_v, key=["bajo", "medio", "alto"].index)), (r.get("riesgo") or {}).get("fuente", "reglas")


def necesita_plan(texto):
    t = texto.strip()
    r = decidir(t, {"plan": {"tipo": "noul", "instrucciones": "El usuario pide construir, crear o modificar un programa, "
                                                               "proyecto o sistema que requiere varios pasos de trabajo."}},
                {"plan": lambda s: bool(len(s) >= 30 and PLAN_RX.search(s) and not SALUDO.match(s))})
    v = (r.get("plan") or {}).get("valor")
    return (v >= 0.5) if isinstance(v, float) else bool(v)


def complejidad(texto):
    def reglas(s):
        if SALUDO.match(s) or len(s) < 25:
            return "bajo"
        if len(s) > 400 or len(PLAN_RX.findall(s)) >= 2:
            return "alto"
        return "medio"
    r = decidir(texto, {"c": {"tipo": "score", "opciones": ["bajo", "medio", "alto"],
                              "instrucciones": "Complejidad del trabajo pedido (bajo = charla o pregunta simple; alto = programa completo)."}},
                {"c": reglas})
    v = str((r.get("c") or {}).get("valor") or "medio").lower()
    return v if v in ("bajo", "medio", "alto") else "medio"


def tipo_error(texto):
    def reglas(s):
        t = s.lower()
        for k, rx in (("dependencia", r"no module named|cannot find module|modulenotfound|importerror|could not resolve|package .* not found"),
                      ("sintaxis", r"syntaxerror|indentationerror|unexpected token|parse error|expected .* but"),
                      ("nombre", r"nameerror|is not defined|undefined name|referenceerror|attributeerror"),
                      ("ruta", r"filenotfound|no such file|cannot find path|enoent|not found: '"),
                      ("permiso", r"permission denied|access is denied|acceso denegado|eacces|unauthorized"),
                      ("red", r"connection refused|timed out|econnrefused|name resolution|getaddrinfo|ssl"),
                      ("memoria", r"memoryerror|out of memory|cuda out of memory"),
                      ("entorno", r"not recognized|no se reconoce|command not found|executionpolicy|venv")):
            if re.search(rx, t):
                return k
        return "logica"
    r = decidir(texto[-3000:], {"t": {"tipo": "choice", "opciones": TIPOS_ERROR,
                                      "instrucciones": "¿Qué tipo de error de programación muestra este texto?"}}, {"t": reglas})
    v = str((r.get("t") or {}).get("valor") or "logica").lower()
    return v if v in TIPOS_ERROR else reglas(texto)
