# -*- coding: utf-8 -*-
"""Salud de los modelos y proveedores: traduce cada error técnico a un MOTIVO claro y una SOLUCIÓN,
recuerda qué modelos no están operativos (para saltarlos y marcarlos en la lista) y los reactiva solos
cuando vuelven a funcionar o pasa el tiempo de espera.

Tipos (kind):
  sin_clave      falta la API key                        → bloquea el proveedor
  clave_invalida 401/403: clave incorrecta o vencida     → bloquea el proveedor
  sin_credito    402 / sin saldo / cuota agotada          → bloquea el modelo 6 h
  limite         429: límite por minuto/día               → pausa corta (10 min), se reintenta
  no_disponible  404: el modelo no existe o tu cuenta no lo tiene (NVIDIA "Function not found for account") → 24 h
  no_descargado  modelo local no descargado               → hasta que cambie
  no_cabe        no hay memoria (VRAM/RAM) para cargarlo  → 12 h
  apagado        Ollama / LM Studio no está abierto       → se revisa en cada intento
"""
import json
import re
import threading
import time

from .config import CONFIG, DATA_DIR

FILE = DATA_DIR / "salud_modelos.json"
_lock = threading.Lock()
_data = None
TTL = {"sin_credito": 6 * 3600, "limite": 600, "no_disponible": 24 * 3600, "no_descargado": 30 * 24 * 3600,
       "no_cabe": 12 * 3600, "clave_invalida": 30 * 24 * 3600, "sin_clave": 30 * 24 * 3600, "apagado": 90}
BLOQUEA = {"sin_credito", "no_disponible", "no_descargado", "no_cabe", "clave_invalida", "sin_clave"}
ICONO = {"sin_clave": "🔑", "clave_invalida": "🔑", "sin_credito": "💳", "limite": "⏳", "no_disponible": "⛔",
         "no_descargado": "⬇", "no_cabe": "💾", "apagado": "🔌"}


def _load():
    global _data
    if _data is None:
        try:
            _data = json.loads(FILE.read_text(encoding="utf-8"))
        except Exception:
            _data = {}
        _data.setdefault("modelos", {})
        _data.setdefault("proveedores", {})
        _data.setdefault("verificados", {})
        _data.setdefault("claves", {})  # modelo → índice de la API key que funciona con él (si tienes varias cuentas)
        if _data.get("version", 1) < 2:
            # v2: antes un 401/403 de UN modelo marcaba a TODO el proveedor como «clave inválida» y la lista quedaba
            # casi vacía. Se borran esas marcas viejas: el verificador vuelve a probar con las reglas nuevas.
            _data["modelos"], _data["proveedores"], _data["version"] = {}, {}, 2
    return _data


def _save():
    try:
        tmp = FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(FILE)
    except Exception:
        pass


def classify(status, body, pid="", model="", local=False):
    """(kind, motivo, solucion) o (None, None, None) si no es un fallo de disponibilidad."""
    t = (body or "").lower()
    pname = (CONFIG["providers"].get(pid) or {}).get("name", pid)
    if "falta la api key" in t or "no api key" in t or "missing api key" in t:
        return ("sin_clave", f"Falta la clave (API key) de {pname}.",
                f"Pégala en 🎁 IA gratis o ⚙ Ajustes → Proveedores → {pname}.")
    if status in (401, 403) or "invalid api key" in t or "unauthorized" in t or "incorrect api key" in t \
            or "authentication" in t and "fail" in t or "api key not valid" in t or "invalid_api_key" in t:
        if status == 403 and ("region" in t or "country" in t or "not available in your" in t):
            return ("no_disponible", f"{pname} no permite este modelo desde tu país o cuenta.", "Usa otro modelo o proveedor.")
        return ("clave_invalida", f"La clave de {pname} es inválida, está vencida o fue revocada.",
                f"Crea una clave nueva en la web de {pname} y pégala en 🎁 IA gratis o ⚙ Ajustes → Proveedores.")
    if status == 402 or "insufficient" in t and ("credit" in t or "balance" in t or "quota" in t) \
            or "payment required" in t or "exceeded your current quota" in t:
        return ("sin_credito", f"Tu cuenta de {pname} no tiene crédito o agotó la cuota gratuita de este modelo.",
                "Espera a que se renueve la cuota, recarga saldo o usa un modelo gratuito de otro proveedor.")
    if status == 429 or "rate limit" in t or "too many requests" in t:
        return ("limite", f"Llegaste al límite de uso de {pname} (por minuto o por día).",
                "Noviark continúa con otra IA del respaldo; este modelo se reintenta en unos minutos.")
    if local:
        if "requires more system memory" in t or "out of memory" in t or "insufficient memory" in t \
                or "not enough memory" in t or "failed to allocate" in t or "cudamalloc" in t or "exceeds" in t and "memory" in t:
            return ("no_cabe", f"{model} no cabe en la memoria de tu PC (VRAM/RAM).",
                    "Usa una versión más pequeña o cuantizada (ej. q4), cierra otros programas o baja el contexto en ⚙ Ajustes → IA local.")
        if status == 404 and ("not found" in t or "pull" in t) or "try pulling" in t or "no such model" in t:
            how = (f"en una terminal: ollama pull {model}" if pid == "ollama" else "en LM Studio → Descubrir (lupa) → Descargar")
            return ("no_descargado", f"{model} no está descargado en {pname}.", f"Descárgalo {how}.")
        if status == 599 and ("no pude conectar" in t or "está abierto" in t):
            return ("apagado", f"{pname} no está abierto o su servidor está apagado.",
                    "Abre Ollama (o LM Studio → Developer → Start server) y vuelve a intentar.")
    if status == 404 or "function" in t and "not found for account" in t or "model_not_found" in t \
            or ("model" in t and ("does not exist" in t or "not found" in t or "is not a valid model" in t
                                  or "no longer available" in t or "deprecated" in t and "removed" in t)):
        if "not found for account" in t:
            motivo = (f"{pname} muestra {model} en la lista pero NO lo sirve para tu cuenta "
                      "(«Function not found for account»: el modelo fue retirado, está en otra región o no está habilitado para ti).")
        else:
            motivo = f"El modelo {model} no existe o ya no está disponible en {pname}."
        return ("no_disponible", motivo, "Elige otro modelo: Noviark lo salta automáticamente durante 24 h y sigue con el respaldo.")
    return (None, None, None)


def friendly(kind, motivo, solucion, raw=""):
    ic = ICONO.get(kind, "⚠")
    s = f"{ic} {motivo}\n💡 Solución: {solucion}"
    if raw:
        s += f"\n\nDetalle técnico: {raw[:300]}"
    return s


def mark(model_id, kind, motivo, solucion, provider_level=False):
    try:
        with _lock:
            d = _load()
            entry = {"kind": kind, "motivo": motivo, "solucion": solucion, "t": time.time()}
            # Solo se marca el PROVEEDOR entero si lo pide quien sabe que falló todo (la lista de modelos o la
            # conexión local). Un error de un modelo concreto marca solo a ese modelo.
            if provider_level or kind in ("sin_clave", "apagado"):
                d["proveedores"][model_id.split("::")[0]] = entry
            else:
                d["modelos"][model_id] = entry
            _save()
    except Exception:
        pass


def ok(model_id):
    """El modelo respondió bien: se borra cualquier marca y queda como verificado."""
    try:
        with _lock:
            d = _load()
            pid = model_id.split("::")[0]
            d["modelos"].pop(model_id, None)
            d["proveedores"].pop(pid, None)
            prev = d["verificados"].get(model_id, 0)
            d["verificados"][model_id] = time.time()
            if time.time() - prev > 600:  # no escribir el archivo en cada respuesta
                _save()
    except Exception:
        pass


def clave(model_id):
    try:
        return _load()["claves"].get(model_id)
    except Exception:
        return None


def set_clave(model_id, idx):
    try:
        with _lock:
            d = _load()
            if d["claves"].get(model_id) != idx:
                d["claves"][model_id] = idx
                _save()
    except Exception:
        pass


def verificado(model_id, max_age=3 * 86400):
    t = _load()["verificados"].get(model_id)
    return bool(t and time.time() - t < max_age)


def ultima_revision(model_id):
    d = _load()
    e = d["modelos"].get(model_id)
    return max(d["verificados"].get(model_id, 0), (e or {}).get("t", 0))


def provider_ok(pid):
    try:
        with _lock:
            d = _load()
            if d["proveedores"].pop(pid, None) is not None:
                _save()
    except Exception:
        pass


def _fresh(e):
    return e and time.time() - e.get("t", 0) < TTL.get(e.get("kind"), 3600)


def get(model_id):
    """Marca vigente del modelo o de su proveedor (o None)."""
    try:
        d = _load()
        e = d["modelos"].get(model_id)
        if _fresh(e):
            return e
        p = d["proveedores"].get(model_id.split("::")[0])
        if _fresh(p):
            return p
    except Exception:
        pass
    return None


def blocked(model_id):
    e = get(model_id)
    return bool(e and e["kind"] in BLOQUEA)


def provider_state(pid):
    e = _load()["proveedores"].get(pid)
    return e if _fresh(e) else None


def reset(model_id=None):
    with _lock:
        d = _load()
        if model_id:
            d["modelos"].pop(model_id, None)
            d["proveedores"].pop(model_id.split("::")[0], None)
        else:
            d["modelos"].clear()
            d["proveedores"].clear()
            d["verificados"].clear()
        _save()


def reset_proveedor(pid):
    """Tras cambiar las claves de un proveedor: se olvidan sus fallos (se vuelve a probar todo)."""
    with _lock:
        d = _load()
        for k in [m for m in d["modelos"] if m.startswith(pid + "::")]:
            d["modelos"].pop(k, None)
        for k in [m for m in d["claves"] if m.startswith(pid + "::")]:
            d["claves"].pop(k, None)
        d["proveedores"].pop(pid, None)
        _save()


def resumen():
    d = _load()
    return {"modelos": {m: e for m, e in d["modelos"].items() if _fresh(e)},
            "proveedores": {p: e for p, e in d["proveedores"].items() if _fresh(e)}}


def list_error(status, body, pid):
    """Error al pedir la lista de modelos de un proveedor → texto claro."""
    p = CONFIG["providers"].get(pid) or {}
    kind, motivo, sol = classify(status, body, pid, "", p.get("local"))
    if kind in ("clave_invalida", "sin_clave", "sin_credito"):
        mark(pid + "::*", kind, motivo, sol, provider_level=True)
        return f"{ICONO[kind]} {motivo} {sol}", kind
    return None, None


_re_json = re.compile(r"\{.*\}", re.S)
