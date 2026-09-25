# -*- coding: utf-8 -*-
"""IA local (Ollama / LM Studio) optimizada para el hardware del usuario.

Problema que resuelve: Ollama usa por defecto un contexto de solo 4096 tokens. El prompt del sistema,
las herramientas y el historial no caben, Ollama recorta el INICIO de la conversación y el modelo
"olvida" el plan y empieza de cero. Aquí:
  • Se habla con Ollama por su API nativa (/api/chat) para fijar num_ctx en cada petición.
  • num_ctx se calcula según la VRAM/RAM del equipo (por defecto RTX 5060 16 GB + 32 GB RAM),
    el tamaño del modelo y el costo de su caché KV por token.
  • LM Studio: se lee el contexto cargado (/api/v0/models) y, si el modelo no está cargado, se carga
    con un contexto adecuado (/api/v1/models/load).
"""
import base64
import json
import threading
import re
import time
import uuid

import requests

from .config import CONFIG

_info_cache = {}
NON_CHAT_LOCAL = re.compile(r"embed|flux|ideogram|fooocus|stable-?diffusion|sdxl|whisper|\bclip\b|^clips$|bge-|rerank|"
                            r"tts|kokoro|musicgen", re.I)


def cfg_local():
    d = {"vram_gb": 16, "ram_gb": 32, "num_ctx": 0, "max_ctx": 32768, "kv_q8": False, "ollama_nativo": True,
         "modo_compacto": "auto", "pensar": "auto", "keep_alive": "30m"}
    d.update(CONFIG.get("local") or {})
    return d


def root_url(p):
    return re.sub(r"/v1/?$", "", (p.get("base_url") or "").rstrip("/"))


# ───────────── Información del modelo ─────────────
def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _params_b(s):
    m = re.search(r"([\d.]+)\s*([BbMm])", s or "")
    if not m:
        return None
    v = float(m.group(1))
    return v / 1000 if m.group(2).lower() == "m" else v


def ollama_info(p, model):
    key = ("ollama", model)
    if key in _info_cache and time.time() - _info_cache[key]["t"] < 600:
        return _info_cache[key]
    base = root_url(p)
    info = {"t": time.time(), "ctx_max": None, "size_gb": None, "params_b": None, "caps": [], "kv_tok": None,
            "quant": ""}
    try:
        r = requests.post(base + "/api/show", json={"model": model}, timeout=8)
        if r.ok:
            j = r.json()
            mi = j.get("model_info") or {}
            get = lambda suf: next((v for k, v in mi.items() if k.endswith(suf)), None)
            info["ctx_max"] = _num(get(".context_length"))
            layers, kvh, heads = _num(get(".block_count")), _num(get(".attention.head_count_kv")), _num(get(".attention.head_count"))
            emb, keylen = _num(get(".embedding_length")), _num(get(".attention.key_length"))
            if isinstance(get(".attention.head_count_kv"), list):
                kvh = max(get(".attention.head_count_kv"))
            hd = keylen or (emb / heads if emb and heads else None)
            if layers and kvh and hd:
                info["kv_tok"] = 2 * layers * kvh * hd * (1 if cfg_local()["kv_q8"] else 2)  # bytes por token
            det = j.get("details") or {}
            info["params_b"] = _params_b(det.get("parameter_size"))
            info["quant"] = det.get("quantization_level", "")
            info["caps"] = j.get("capabilities") or []
        r = requests.get(base + "/api/tags", timeout=8)
        if r.ok:
            for m in r.json().get("models", []):
                if m.get("name") == model or m.get("model") == model:
                    info["size_gb"] = (m.get("size") or 0) / 1e9
    except requests.RequestException:
        pass
    _info_cache[key] = info
    return info


def lmstudio_models(p):
    try:
        r = requests.get(root_url(p) + "/api/v0/models", timeout=4)
        if r.ok:
            return r.json().get("data", [])
    except requests.RequestException:
        pass
    return None


def lmstudio_info(p, model):
    for m in lmstudio_models(p) or []:
        if m.get("id") == model:
            return {"state": m.get("state"), "ctx_max": m.get("max_context_length"),
                    "ctx_loaded": m.get("loaded_context_length"), "type": m.get("type"),
                    "caps": m.get("capabilities") or []}
    return {}


def choose_num_ctx(info):
    """Contexto óptimo para la VRAM/RAM configuradas (por defecto 16 GB VRAM / 32 GB RAM)."""
    L = cfg_local()
    if int(L.get("num_ctx") or 0) > 0:
        return int(L["num_ctx"])
    cap = int(L.get("max_ctx") or 32768)
    if info.get("ctx_max"):
        cap = min(cap, int(info["ctx_max"]))
    size = info.get("size_gb") or ((info.get("params_b") or 8) * 0.62)  # ~Q4 si no se conoce
    kv = info.get("kv_tok") or (0.00016e9 if (info.get("params_b") or 8) >= 20 else 0.00012e9)
    free = float(L["vram_gb"]) * 0.92 - size - 0.8  # margen para buffers de cómputo
    if free > 0.5:
        ctx = free * 1e9 / kv
    else:
        # el modelo no cabe entero en la GPU: parte va a la RAM. Contexto moderado para no volverlo lentísimo.
        spare_ram = float(L["ram_gb"]) * 0.7 - (size - float(L["vram_gb"]) * 0.9)
        ctx = 16384 if spare_ram > 8 else 8192
    ctx = int(max(4096, min(ctx, cap)) // 1024 * 1024)
    return ctx


def context_window(model_id):
    """(tokens de contexto que usará el modelo, info) para modelos locales; (None, {}) si es de la nube."""
    pid, model = model_id.split("::", 1) if "::" in model_id else ("nvidia", model_id)
    p = CONFIG["providers"].get(pid) or {}
    if not p.get("local"):
        return None, {}
    if pid == "ollama" or ":11434" in p.get("base_url", ""):
        info = ollama_info(p, model)
        return choose_num_ctx(info), info
    info = lmstudio_info(p, model)
    if info.get("ctx_loaded"):
        return int(info["ctx_loaded"]), info
    return min(choose_num_ctx({"ctx_max": info.get("ctx_max"), "params_b": _params_b(model)}), 16384), info


def ensure_lmstudio_loaded(p, model, emit):
    """Si el modelo de LM Studio no está cargado, lo carga con un contexto adecuado y avisa cuánto tarda."""
    from .providers import APIError
    info = lmstudio_info(p, model)
    if not info or info.get("state") == "loaded":
        return
    ctx = min(choose_num_ctx({"ctx_max": info.get("ctx_max"), "params_b": _params_b(model)}), 16384)
    emit("fase", {"fase": "cargando", "texto": f"Cargando {model} en LM Studio (contexto {ctx} tokens). "
                                              "La primera carga puede tardar de 10 s a 2 min…"})
    try:
        r = requests.post(root_url(p) + "/api/v1/models/load", json={"model": model, "context_length": ctx}, timeout=300)
    except requests.Timeout:
        raise APIError(f"⏳ LM Studio tardó más de 5 minutos en cargar {model}.\n💡 Solución: prueba un modelo más pequeño "
                       "o cárgalo a mano en LM Studio.", 599)
    except requests.RequestException:
        return
    if r.status_code >= 400:
        from .providers import http_error
        e = http_error(r.status_code, r.text[:600], "lmstudio::" + model, local=True)
        if e.kind:
            raise e


def ollama_loaded(p):
    """Modelos que Ollama tiene cargados ahora mismo en memoria (/api/ps)."""
    try:
        r = requests.get(root_url(p) + "/api/ps", timeout=3)
        return {m.get("name") or m.get("model") for m in r.json().get("models", [])}
    except Exception:
        return None


# ───────────── Ollama: API nativa ─────────────
def _to_ollama_messages(messages):
    out = []
    for m in messages:
        role = m.get("role")
        c = m.get("content")
        msg = {"role": role, "content": ""}
        if isinstance(c, list):
            texts, imgs = [], []
            for part in c:
                if part.get("type") == "image_url":
                    url = part.get("image_url", {}).get("url", "")
                    imgs.append(url.split(",", 1)[1] if url.startswith("data:") else url)
                else:
                    texts.append(part.get("text", ""))
            msg["content"] = "\n".join(texts)
            if imgs:
                msg["images"] = imgs
        else:
            msg["content"] = c or ""
        if m.get("tool_calls"):
            calls = []
            for tc in m["tool_calls"]:
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except Exception:
                    args = {}
                calls.append({"function": {"name": tc["function"]["name"], "arguments": args}})
            msg["tool_calls"] = calls
        if role == "tool":
            msg["tool_name"] = m.get("name", "")
        out.append(msg)
    return out


def stream_ollama(model_id, p, messages, tools, emit, stop_ev, max_tokens, temperature, top_p, think=None, guard=None):
    """Devuelve (texto, razonamiento, tool_calls, finish, uso)."""
    from .providers import APIError, TagSplitter
    model = model_id.split("::", 1)[1]
    num_ctx, info = context_window(model_id)
    L = cfg_local()
    payload = {"model": model, "messages": _to_ollama_messages(messages), "stream": True,
               "keep_alive": L.get("keep_alive") or "30m",
               "options": {"num_ctx": num_ctx, "num_predict": int(min(max_tokens, max(1024, num_ctx // 3))),
                           "temperature": temperature, "top_p": top_p}}
    if tools:
        payload["tools"] = tools
    if think is not None and "thinking" in (info.get("caps") or []):
        payload["think"] = think
    loaded = ollama_loaded(p)
    names = {model, model + ":latest"} if ":" not in model else {model}
    watch = None
    if loaded is not None and not (loaded & names):
        size = info.get("size_gb")
        emit("fase", {"fase": "cargando", "texto": f"Cargando {model} en la memoria"
                      + (f" ({size:.1f} GB)" if size else "") + " — la primera vez tarda de 10 s a 1-2 min…"})
        done = threading.Event()

        def _watch():  # avisa cuando termina de cargar y empieza a leer el contexto
            while not done.wait(1.0):
                now = ollama_loaded(p)
                if now and (now & names):
                    emit("fase", {"fase": "procesando", "texto": f"{model} cargado. Leyendo el contexto (~{num_ctx // 1000}k tokens máx.)…"})
                    return
        watch = done
        threading.Thread(target=_watch, daemon=True).start()
    else:
        emit("fase", {"fase": "procesando", "texto": f"{model} está leyendo el contexto…"})
    try:
        r = requests.post(root_url(p) + "/api/chat", json=payload, stream=True,
                          timeout=(15, float(CONFIG.get("read_timeout", 240)) + 300))
    except requests.ConnectionError:
        if watch:
            watch.set()
        raise APIError(f"🔌 No pude conectar con Ollama en {root_url(p)}.\n💡 Solución: abre Ollama (icono junto al reloj) "
                       "y vuelve a intentar.", 599, "apagado")
    if r.status_code != 200:
        if watch:
            watch.set()
        body = r.text[:1500]
        r.close()
        raise APIError(f"{r.status_code}: {body}", r.status_code)
    raw, reasoning, calls, finish, usage = "", "", [], None, {}
    splitter = TagSplitter()

    def push(chunks):
        nonlocal reasoning
        for ch, t in chunks:
            if t and ch == "reasoning":
                reasoning += t
                emit("reasoning", {"text": t})
                if guard:
                    guard.on_reasoning(t)
            elif t and ch == "content":
                emit("token", {"text": t})
                if guard:
                    guard.on_content(t)
    try:
        for line in r.iter_lines(decode_unicode=False):
            if stop_ev.is_set():
                break
            if not line:
                continue
            try:
                j = json.loads(line.decode("utf-8"))
            except Exception:
                continue
            if j.get("error"):
                raise APIError(str(j["error"]), 400)
            if watch and not watch.is_set():
                watch.set()
            msg = j.get("message") or {}
            if msg.get("thinking"):
                if not reasoning:
                    emit("fase", {"fase": "pensando", "texto": f"{model} está pensando…"})
                reasoning += msg["thinking"]
                emit("reasoning", {"text": msg["thinking"]})
                if guard:
                    guard.on_reasoning(msg["thinking"])
            if msg.get("content"):
                if not raw:
                    emit("fase", {"fase": "escribiendo", "texto": f"{model} está respondiendo…"})
                raw += msg["content"]
                push(splitter.feed(msg["content"]))
            for tc in msg.get("tool_calls") or []:
                if guard:
                    guard.on_tool()
                fn = tc.get("function") or {}
                args = fn.get("arguments")
                calls.append({"id": f"call_{uuid.uuid4().hex[:12]}", "type": "function",
                              "function": {"name": fn.get("name", ""),
                                           "arguments": args if isinstance(args, str) else json.dumps(args or {}, ensure_ascii=False)}})
                emit("tool_delta", {"i": len(calls) - 1, "name": fn.get("name", ""), "chunk": calls[-1]["function"]["arguments"]})
            if j.get("done"):
                finish = {"length": "length", "stop": "stop"}.get(j.get("done_reason"), j.get("done_reason"))
                usage = {"entrada": j.get("prompt_eval_count"), "salida": j.get("eval_count"), "num_ctx": num_ctx}
            if guard and guard.tripped:
                finish = "guardian"
                break
        push(splitter.feed("", final=True))
    except requests.RequestException as e:
        raise APIError(f"La conexión con Ollama se cortó ({type(e).__name__}).", 599)
    finally:
        if watch:
            watch.set()
        r.close()
    if calls:
        finish = finish if finish in ("length", "guardian") else "tool_calls"
    return raw, reasoning, calls, finish, usage


def optimizar_ollama_windows():
    """Variables de entorno recomendadas para una GPU de 16 GB (se aplican al reiniciar Ollama)."""
    return {
        "OLLAMA_FLASH_ATTENTION": "1",      # menos memoria y más velocidad en el contexto
        "OLLAMA_KV_CACHE_TYPE": "q8_0",     # caché KV a la mitad de memoria (casi sin pérdida)
        "OLLAMA_NUM_PARALLEL": "1",         # toda la VRAM para una sola conversación
        "OLLAMA_MAX_LOADED_MODELS": "1",    # no tener 2 modelos cargados peleando por la VRAM
        "OLLAMA_KEEP_ALIVE": "30m",         # no descargar el modelo entre pasos del agente
        "OLLAMA_CONTEXT_LENGTH": "16384",   # respaldo para programas que no envían num_ctx
    }
