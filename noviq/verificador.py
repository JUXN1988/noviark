# -*- coding: utf-8 -*-
"""Agente verificador (sin IA): comprueba en segundo plano qué modelos RESPONDEN de verdad con tus claves.
Muchos proveedores (sobre todo NVIDIA) listan modelos que tu cuenta no puede usar; este agente los prueba uno a uno
con un mensaje mínimo, respetando los límites gratuitos, y deja cada uno como ✅ verificado o ⛔ no operativo
(con motivo). La lista de modelos muestra por defecto solo los que funcionan.
- Se repite cada día y cuando conectas un proveedor nuevo.
- No gasta cuotas pequeñas: en OpenRouter (50/día) solo prueba los mejores; en proveedores anónimos muy limitados, pocos.
"""
import threading
import time

from .config import CONFIG

# segundos entre pruebas y máximo de modelos por proveedor (para no agotar los planes gratuitos)
RITMO = {"nvidia": (2.0, 400), "groq": (3.0, 60), "cerebras": (13.0, 20), "gemini": (5.0, 20), "mistral": (3.0, 40),
         "openrouter": (5.0, 8), "kilo": (20.0, 10), "llm7": (7.0, 12), "ovh": (35.0, 3), "zai": (4.0, 10),
         "cloudflare": (3.0, 10), "cohere": (4.0, 4), "aion": (5.0, 6), "pollinations": (5.0, 10), "huggingface": (4.0, 10),
         "ollamacloud": (5.0, 10), "vercel": (4.0, 10)}
NO_VERIFICAR = {"openai", "anthropic", "deepseek", "xai", "custom"}  # de pago: no se gasta dinero probando

_state = {}      # pid → {"total", "hechos", "ok", "fallos", "activo", "t", "actual"}
_running = set()
_lock = threading.Lock()
_started = False


def estado():
    return {k: dict(v) for k, v in _state.items()}


def pedir(pid=None, forzar=False):
    """Verifica un proveedor (o todos los activos). Cada proveedor se prueba EN PARALELO en su propio hilo,
    así Gemini no espera a que termine NVIDIA."""
    if CONFIG.get("verificar_modelos", True) is False and not forzar:
        return
    pids = [pid] if pid else [k for k, p in CONFIG["providers"].items()
                               if p.get("enabled") and not p.get("local") and not p.get("decisor")]
    for k in pids:
        if k in NO_VERIFICAR:
            continue
        with _lock:
            if k in _running:
                continue
            _running.add(k)
        threading.Thread(target=_worker, args=(k, forzar), daemon=True, name=f"verificador-{k}").start()
    iniciar()


def _worker(pid, forzar):
    try:
        _run_one(pid, forzar)
    except Exception as e:
        _state.setdefault(pid, {})["error"] = str(e)[:200]
    finally:
        _state.setdefault(pid, {})["activo"] = False
        with _lock:
            _running.discard(pid)


def _candidatos(pid, forzar):
    from . import catalogo as K
    from . import salud
    from .providers import list_models
    c = list_models(pid)
    if not c.get("ok"):
        return []
    ritmo, maximo = RITMO.get(pid, (4.0, 30))
    ids = [f"{pid}::{m}" for m in c["models"]]
    try:  # primero los mejores (así lo más útil queda verificado antes)
        infos = K.all_infos()
        ids.sort(key=lambda m: -(infos.get(m) or {}).get("cerebro", 0))
    except Exception:
        pass
    if not forzar:
        ids = [m for m in ids if time.time() - salud.ultima_revision(m) > 86400]
    return ids[:maximo]


def _run_one(pid, forzar):
    from .providers import probe
    ids = _candidatos(pid, forzar)
    st = _state[pid] = {"total": len(ids), "hechos": 0, "ok": 0, "fallos": 0, "ocupados": 0, "activo": True, "t": time.time(),
                        "nombre": CONFIG["providers"].get(pid, {}).get("name", pid), "actual": ""}
    ritmo = RITMO.get(pid, (4.0, 30))[0]
    for m in ids:
        st["actual"] = m
        r = probe(m, timeout=45)
        st["hechos"] += 1
        if r.get("ok"):
            st["ok"] += 1
        elif r.get("kind") in ("limite", "ocupado"):
            st["ocupados"] += 1
            time.sleep(min(30, ritmo * 3))  # se respeta el límite del plan gratuito
        elif r.get("kind") in ("clave_invalida", "sin_clave", "sin_conexion") and st["ok"] == 0 and st["hechos"] >= 3:
            st["error"] = (r.get("motivo") or "")[:200]
            break
        else:
            st["fallos"] += 1
        try:
            from . import catalogo as K
            K._cache["t"] = 0  # la lista se actualiza en vivo con cada resultado
        except Exception:
            pass
        time.sleep(ritmo)
    st["activo"], st["actual"] = False, ""


def _loop():
    time.sleep(15)
    while True:
        pedir()
        time.sleep(86400)


def iniciar():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="verificador").start()
