# -*- coding: utf-8 -*-
"""Proveedores compatibles con OpenAI: NVIDIA, Ollama, LM Studio y cualquier otro."""
import json
import random
import re
import time
import uuid

import requests

from .config import CONFIG

NON_CHAT = re.compile(r"embed|rerank|guard|safety|reward|parse|clip\b|retriever|ocr|asr|tts|detector|pii|"
                      r"paligemma|deplot|kosmos|nemoretriever|topic-control|content-safety|whisper|canary|"
                      r"parakeet|riva|audio2face|flux|stable-diffusion|sdxl|cosmos|trellis|bge|e5-|nv-embed|"
                      r"dall-e|moderation|imagen|veo-|\baqa\b|realtime|transcribe|-image|babbage|davinci|"
                      r"text-embedding|gpt-image|sora|lyria|native-audio|-live-|robotics|computer-use|-tts|imagen|nano-banana|learnlm|gemini-embedding", re.I)


class APIError(Exception):
    def __init__(self, msg, status=0, kind=None):
        super().__init__(msg)
        self.status = status
        self.kind = kind


def http_error(status, body, model_id, local=False):
    """Convierte un error HTTP en un APIError con motivo y solución claros (y marca el modelo)."""
    from . import salud
    pid, model = split_model(model_id)
    kind, motivo, sol = salud.classify(status, body, pid, model, local)
    if kind == "clave_invalida" and status == 403 and model:
        # 403 en un modelo concreto = tu cuenta no tiene permiso para ESE modelo (la clave sirve para los demás)
        kind, motivo, sol = ("no_disponible", f"Tu cuenta de {(CONFIG['providers'].get(pid) or {}).get('name', pid)} no tiene permiso "
                             f"para usar {model}.", "Elige otro modelo (o agrega la clave de otra cuenta que sí lo tenga).")
    if kind:
        if kind != "limite":
            salud.mark(model_id, kind, motivo, sol)
        return APIError(salud.friendly(kind, motivo, sol, f"{status}: {body}"), status, kind)
    return APIError(f"{status}: {body}", status)


def split_model(model_id):
    if "::" in model_id:
        p, m = model_id.split("::", 1)
        return p, m
    return "nvidia", model_id


def provider_cfg(pid):
    p = CONFIG["providers"].get(pid)
    if not p:
        raise APIError(f"Proveedor desconocido: {pid}")
    if not p.get("base_url"):
        raise APIError(f"El proveedor {p.get('name', pid)} no tiene URL configurada (⚙ Configuración → Proveedores).")
    if "{cuenta}" in p["base_url"]:
        if not p.get("cuenta"):
            raise APIError(f"🔑 Falta el ID de cuenta de {p.get('name', pid)}.\n💡 Solución: pégalo en 🎁 IA gratis.", 401, "sin_clave")
        p = dict(p, base_url=p["base_url"].replace("{cuenta}", p["cuenta"]))
    return p


_key_idx = {}


def _keys(pid, p):
    from . import vault
    keys = vault.get_keys(pid)
    if not keys and p.get("anonimo"):
        return [p.get("clave_anonima") or ""]  # acceso anónimo gratuito (sin cuenta)
    if not keys:
        if not p.get("local") and pid != "custom":
            raise APIError(f"🔑 Falta la API key de {p.get('name', pid)}.\n💡 Solución: pégala en 🎁 IA gratis o "
                           "⚙ Ajustes → Proveedores.", 401, "sin_clave")
        keys = ["sin-clave"]
    return keys


def _headers(key, p=None):
    h = {"Content-Type": "application/json"}
    if key:
        h["Authorization"] = f"Bearer {key}"
    if p and p.get("anthropic_headers"):
        h.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
    if p and "openrouter" in p.get("base_url", ""):
        h.update({"HTTP-Referer": "http://localhost", "X-Title": "Noviark"})
    return h


# ───────────── Listado de modelos ─────────────
_models_cache = {}


def list_models(pid, refresh=False):
    c = _models_cache.get(pid)
    if c and not refresh and time.time() - c["t"] < 600:
        return c
    p = CONFIG["providers"].get(pid) or {}
    out = {"id": pid, "name": p.get("name", pid), "ok": False, "models": [], "error": "", "t": time.time()}
    if not p.get("enabled") or not p.get("base_url"):
        out["error"] = "desactivado"
        return out
    if p.get("decisor"):
        out["error"] = "desactivado"  # no es un modelo de chat (lo usa el decisor)
        return out
    try:
        p = provider_cfg(pid)
        key = _keys(pid, p)[0]
        r = requests.get(p["base_url"].rstrip("/") + "/models", headers=_headers(key, p),
                         timeout=4 if p.get("local") else 20)
        if r.status_code in (404, 405) and p.get("modelos_fijos"):
            out.update(ok=True, models=list(p["modelos_fijos"]))
            _models_cache[pid] = out
            return out
        if r.status_code != 200:
            from . import salud
            msg, kind = salud.list_error(r.status_code, r.text[:600], pid)
            raise APIError(msg or f"{r.status_code}: {r.text[:200]}", r.status_code, kind)
        j = r.json()
        data = j.get("data") or j.get("models") or []
        ids = sorted({(m.get("id") or m.get("name") or "").removeprefix("models/") for m in data} - {""})
        if not p.get("local"):
            ids = [i for i in ids if not NON_CHAT.search(i)]
            if p.get("solo_gratis") and any(i.endswith(":free") for i in ids):
                ids = [i for i in ids if i.endswith(":free")]  # OpenRouter/Kilo: solo los modelos gratuitos
            if p.get("filtro_gratis"):
                fg = re.compile(p["filtro_gratis"], re.I)
                ids = [i for i in ids if fg.search(i)] or ids
        else:
            from . import local as LOC
            ids = [i for i in ids if not LOC.NON_CHAT_LOCAL.search(i)]
            if pid == "lmstudio":
                v0 = LOC.lmstudio_models(p)
                if v0:  # LM Studio dice el tipo: solo modelos de texto (llm) y visión (vlm)
                    ok = {m["id"] for m in v0 if m.get("type") in ("llm", "vlm")}
                    ids = [i for i in ids if i in ok]
        out.update(ok=True, models=ids)
        from . import salud
        salud.provider_ok(pid)
    except APIError as e:
        out["error"] = str(e)
        out["kind"] = e.kind
    except requests.ConnectionError:
        out["error"] = ("🔌 No está abierto: abre el programa (o activa su servidor) y pulsa ↻" if p.get("local")
                        else "🌐 Sin conexión a internet o el servidor no responde")
        out["kind"] = "apagado" if p.get("local") else "sin_conexion"
    except Exception as e:
        out["error"] = str(e)[:200]
    _models_cache[pid] = out
    return out


# ───────────── Separador de etiquetas en streaming (<think>, <tool_call>) ─────────────
class TagSplitter:
    """Divide texto en streaming por canales: content, reasoning (<think>) y hidden (<tool_call>)."""
    TAGS = {"think": "reasoning", "thinking": "reasoning", "tool_call": "hidden"}

    def __init__(self):
        self.buf = ""
        self.stack = []  # canal actual por etiqueta abierta

    def _chan(self):
        return self.stack[-1][1] if self.stack else "content"

    def feed(self, text, final=False):
        self.buf += text
        out = []
        while self.buf:
            i = self.buf.find("<")
            if i < 0:
                out.append((self._chan(), self.buf))
                self.buf = ""
                break
            if i > 0:
                out.append((self._chan(), self.buf[:i]))
                self.buf = self.buf[i:]
            m = re.match(r"<(/?)([a-z_]+)>", self.buf)
            if m:
                closing, tag = m.group(1) == "/", m.group(2)
                if tag in self.TAGS:
                    if not closing:
                        self.stack.append((tag, self.TAGS[tag]))
                        if self.TAGS[tag] == "hidden":
                            out.append(("hidden", m.group(0)))
                    elif self.stack and self.stack[-1][0] == tag:
                        if self.stack[-1][1] == "hidden":
                            out.append(("hidden", m.group(0)))
                        self.stack.pop()
                    elif not self.stack and tag in ("think", "thinking"):
                        # algunos modelos (DeepSeek-R1) omiten <think> y solo cierran
                        out = [("reasoning", t) if ch == "content" else (ch, t) for ch, t in out]
                        self.pre_reasoning = True
                    self.buf = self.buf[m.end():]
                    continue
                out.append((self._chan(), m.group(0)))
                self.buf = self.buf[m.end():]
                continue
            # ¿podría ser el inicio de una etiqueta incompleta?
            if not final and re.fullmatch(r"</?[a-z_]{0,12}", self.buf):
                break
            out.append((self._chan(), "<"))
            self.buf = self.buf[1:]
        if final and self.buf:
            out.append((self._chan(), self.buf))
            self.buf = ""
        return out


# ───────────── Chat en streaming ─────────────
def stream_chat(model_id, messages, tools, emit, stop_ev, extra=None, max_attempts=6, guard=None):
    """Devuelve (contenido_crudo, razonamiento, tool_calls_nativos, finish_reason).
    guard: Guardian opcional; si detecta razonamiento eterno o texto en bucle corta el streaming y finish='guardian'."""
    pid, model = split_model(model_id)
    p = provider_cfg(pid)
    ov = CONFIG.get("model_overrides", {}).get(model_id, {})
    from . import local as LOC
    if p.get("local") and (pid == "ollama" or ":11434" in p.get("base_url", "")) and LOC.cfg_local().get("ollama_nativo", True):
        # API nativa de Ollama: permite fijar num_ctx (por defecto Ollama usa solo 4096 tokens y "olvida" el inicio)
        L = LOC.cfg_local()
        think = False if (L.get("pensar") == "no" or ov.get("reasoning_effort") == "low"
                          or (extra or {}).get("reasoning_effort") == "low") else None
        mt = int((extra or {}).get("max_tokens") or ov.get("max_tokens") or CONFIG.get("max_tokens", 16384))
        try:
            raw, reasoning, calls, finish, usage = LOC.stream_ollama(
                model_id, p, messages, tools, emit, stop_ev, mt, float(CONFIG.get("temperature", 0.6)),
                float(CONFIG.get("top_p", 0.95)), think, guard=guard)
        except APIError as e:
            if e.kind or "tool" in str(e).lower():
                raise
            raise http_error(e.status, str(e).split(": ", 1)[-1], model_id, local=True)
        from . import salud
        salud.ok(model_id)
        if usage:
            emit("usage", usage)
        log_call(model_id, {"tools": tools, "max_tokens": mt, "reasoning_effort": f"num_ctx={usage.get('num_ctx')}"},
                 raw, reasoning, calls, finish)
        return raw, reasoning, calls, finish
    if p.get("local") and pid == "lmstudio":
        LOC.ensure_lmstudio_loaded(p, model, emit)
    emit("fase", {"fase": "procesando" if p.get("local") else "esperando",
                  "texto": (f"{model} está leyendo el contexto…" if p.get("local") else f"Esperando respuesta de {p.get('name', pid)}…")})
    payload = {
        "model": model,
        "messages": messages,
        "temperature": min(float(CONFIG.get("temperature", 0.6)), float(p.get("max_temp", 2.0))),
        "top_p": float(CONFIG.get("top_p", 0.95)),
        "max_tokens": int(ov.get("max_tokens") or CONFIG.get("max_tokens", 16384)),
        "stream": True,
    }
    effort = ov.get("reasoning_effort") or CONFIG.get("reasoning_effort")
    if effort and not ov.get("no_reasoning_effort"):
        payload["reasoning_effort"] = effort
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    if extra:
        payload.update(extra)
        if ov.get("no_reasoning_effort"):
            payload.pop("reasoning_effort", None)
        if ov.get("no_ctk"):
            payload.pop("chat_template_kwargs", None)

    keys = _keys(pid, p)
    url = p["base_url"].rstrip("/") + "/chat/completions"
    r, last_err, bad_keys = None, "", set()
    read_to = float(CONFIG.get("read_timeout", 240))
    from . import salud as _S
    pref = _S.clave(model_id) if len(keys) > 1 else None
    if pref is not None and pref < len(keys):
        _key_idx[pid] = pref  # la clave (cuenta) que ya funcionó con este modelo
    for attempt in range(max_attempts + len(keys) - 1):
        k = keys[_key_idx.get(pid, 0) % len(keys)]
        try:
            r = requests.post(url, headers=_headers(k, p), json=payload, stream=True, timeout=(15, read_to))
        except requests.ConnectionError as e:
            if p.get("local"):
                raise APIError(f"🔌 No pude conectar con {p['name']} en {p['base_url']}.\n💡 Solución: ábrelo y activa su "
                               "servidor (LM Studio → Developer → Start server; Ollama se abre solo al iniciarlo).", 599, "apagado")
            last_err = str(e)
            time.sleep(2 + attempt * 2)
            continue
        except requests.Timeout:
            last_err = f"sin respuesta en {int(read_to)} s"
            continue
        if r.status_code == 200:
            break
        body = r.text[:2000]
        r.close()
        cuenta_404 = r.status_code == 404 and "not found for account" in body.lower()
        if r.status_code in (401, 403) or cuenta_404:
            bad_keys.add(k)
        if (r.status_code in (401, 403, 429) or cuenta_404) and len(keys) > 1 and len(bad_keys) < len(keys):
            _key_idx[pid] = _key_idx.get(pid, 0) + 1  # prueba con la siguiente clave (otra cuenta)
            emit("status", {"text": ("Este modelo no está en tu primera cuenta; " if cuenta_404 else f"Clave {r.status_code}: ")
                                    + "probando con tu otra API key…"})
            continue
        if r.status_code in (429, 500, 502, 503, 504) and attempt < max_attempts - 1:
            wait = float(r.headers.get("Retry-After") or 0) or min(40, 2 ** attempt + random.random() * 2)
            emit("status", {"text": f"El servidor respondió {r.status_code}; reintento en {int(wait)} s…"})
            for _ in range(int(wait * 2)):
                if stop_ev.is_set():
                    raise APIError("Detenido.")
                time.sleep(0.5)
            continue
        raise http_error(r.status_code, body, model_id, local=p.get("local"))
    else:
        raise APIError(f"{p.get('name', pid)} no respondió tras {max_attempts} intentos. {last_err}", 599)

    raw, reasoning, calls, finish = "", "", {}, None
    splitter = TagSplitter()

    def push(chunks):
        nonlocal reasoning
        for ch, t in chunks:
            if not t:
                continue
            if ch == "reasoning":
                reasoning += t
                emit("reasoning", {"text": t})
                if guard:
                    guard.on_reasoning(t)
            elif ch == "content":
                emit("token", {"text": t})
                if guard:
                    guard.on_content(t)
            elif ch == "hidden":  # llamada a herramienta escrita como texto: también se muestra en vivo
                emit("tool_delta", {"i": 0, "name": "", "chunk": t, "texto": True})
                if guard:
                    guard.on_tool()

    try:
        for line in r.iter_lines(decode_unicode=False):
            if stop_ev.is_set():
                break
            if not line or not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                break
            try:
                chunk = json.loads(data.decode("utf-8"))
            except Exception:
                continue
            if chunk.get("error"):
                er = chunk["error"]
                code = er.get("code") if isinstance(er, dict) else None
                raise http_error(code if isinstance(code, int) else 500, json.dumps(er, ensure_ascii=False)[:800], model_id,
                                 local=p.get("local"))
            for ch in chunk.get("choices", []):
                d = ch.get("delta") or ch.get("message") or {}
                rc = d.get("reasoning_content") or d.get("reasoning")
                if isinstance(rc, str) and rc:
                    if not reasoning:
                        emit("fase", {"fase": "pensando", "texto": f"{model} está pensando…"})
                    reasoning += rc
                    emit("reasoning", {"text": rc})
                    if guard:
                        guard.on_reasoning(rc)
                if d.get("content"):
                    if not raw:
                        emit("fase", {"fase": "escribiendo", "texto": f"{model} está respondiendo…"})
                    raw += d["content"]
                    push(splitter.feed(d["content"]))
                if d.get("tool_calls") and not calls:
                    emit("fase", {"fase": "herramienta", "texto": f"{model} está preparando una acción…"})
                    if guard:
                        guard.on_tool()
                for tc in d.get("tool_calls") or []:
                    i = tc.get("index", len(calls))
                    slot = calls.setdefault(i, {"id": "", "name": "", "arguments": ""})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] = fn["name"] if fn["name"].startswith(slot["name"]) else slot["name"] + fn["name"]
                    a = fn.get("arguments")
                    if a:
                        a = a if isinstance(a, str) else json.dumps(a, ensure_ascii=False)
                        slot["arguments"] += a
                        emit("tool_delta", {"i": i, "name": slot["name"], "chunk": a})
                if ch.get("finish_reason"):
                    finish = ch["finish_reason"]
            if guard and guard.tripped:
                finish = "guardian"
                break
        push(splitter.feed("", final=True))
    except requests.RequestException as e:
        raise APIError(f"La conexión con {p.get('name', pid)} se cortó o dejó de responder ({type(e).__name__}).", 599)
    finally:
        r.close()

    tool_calls = []
    for i in sorted(calls):
        c = calls[i]
        if c["name"]:
            tool_calls.append({"id": c["id"] or f"call_{uuid.uuid4().hex[:12]}", "type": "function",
                               "function": {"name": c["name"], "arguments": c["arguments"] or "{}"}})
    log_call(model_id, payload, raw, reasoning, tool_calls, finish)
    if raw or reasoning or tool_calls:
        from . import salud
        salud.ok(model_id)
        if len(keys) > 1:
            salud.set_clave(model_id, _key_idx.get(pid, 0) % len(keys))
    return raw, reasoning, tool_calls, finish


def log_call(model_id, payload, raw, reasoning, tool_calls, finish):
    """Registro técnico (datos/registro.log) para diagnosticar modelos."""
    try:
        from .config import DATA_DIR
        f = DATA_DIR / "registro.log"
        if f.exists() and f.stat().st_size > 2_000_000:
            f.replace(DATA_DIR / "registro.old.log")
        line = (f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {model_id} | tools={'si' if payload.get('tools') else 'no'} | "
                f"max_tokens={payload.get('max_tokens')} | effort={payload.get('reasoning_effort', '-')} | fin={finish} | "
                f"texto={len(raw)} | razonamiento={len(reasoning)} | llamadas={[c['function']['name'] for c in tool_calls]}")
        if not tool_calls and raw:
            line += " | muestra=" + json.dumps(raw[:300], ensure_ascii=False)
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


# ───────────── Llamadas a herramientas escritas como texto ─────────────
def _loads_lenient(s):
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    for attempt in (s, s.replace("\n", "\\n"), re.sub(r",\s*([}\]])", r"\1", s)):
        try:
            return json.loads(attempt)
        except Exception:
            pass
    # último intento: primer objeto JSON balanceado
    start = s.find("{")
    if start >= 0:
        depth, instr, esc = 0, False, False
        for i, c in enumerate(s[start:], start):
            if instr:
                esc = (c == "\\" and not esc)
                if c == '"' and not esc:
                    instr = False
                continue
            if c == '"':
                instr = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(s[start:i + 1])
                    except Exception:
                        break
    return None


def _xml_val(v):
    v = v.strip("\n")
    s = v.strip()
    if s[:1] in "[{" or s in ("true", "false", "null") or re.fullmatch(r"-?\d+(\.\d+)?", s or "x"):
        try:
            return json.loads(s)
        except Exception:
            pass
    return v


def _parse_xml_call(block):
    """Formatos XML de GLM (<arg_key>/<arg_value>) y Qwen (<function=..><parameter=..>)."""
    m = re.search(r"<function=([\w.\-]+)>(.*?)(?:</function>|$)", block, re.S)
    if m:
        args = {k: _xml_val(v) for k, v in re.findall(r"<parameter=([\w.\-]+)>(.*?)(?:</parameter>|(?=<parameter=)|$)", m.group(2), re.S)}
        return m.group(1), args
    if "<arg_key>" in block:
        name = block.split("<arg_key>", 1)[0].strip()
        pairs = re.findall(r"<arg_key>\s*(.*?)\s*</arg_key>\s*<arg_value>(.*?)(?:</arg_value>|(?=<arg_key>)|$)", block, re.S)
        return name, {k: _xml_val(v) for k, v in pairs}
    name = block.strip()
    if re.fullmatch(r"[\w.\-]+", name or ""):
        return name, {}
    return None, None


def parse_text_tool_calls(text, valid_names, allow_fenced=True):
    blocks = re.findall(r"<tool_call>\s*(.*?)\s*(?:</tool_call>|$)", text, re.S)
    if not blocks:
        blocks = re.findall(r"(<function=[\w.\-]+>.*?(?:</function>|$))", text, re.S)
    blocks += re.findall(r"\[TOOL_REQUEST\]\s*(.*?)\s*(?:\[END_TOOL_REQUEST\]|$)", text, re.S)
    if not blocks and allow_fenced:
        for m in re.finditer(r"```(?:json|tool)?\s*(\{.*?\})\s*```", text, re.S):
            if re.search(r'"(name|herramienta|tool)"\s*:', m.group(1)):
                blocks.append(m.group(1))
    calls = []
    for b in blocks:
        obj = _loads_lenient(b) if b.lstrip().startswith(("{", "```")) else None
        if not isinstance(obj, dict):
            name, args = _parse_xml_call(b)
            if name in valid_names:
                calls.append({"id": f"txt_{uuid.uuid4().hex[:10]}", "type": "function",
                              "function": {"name": name, "arguments": json.dumps(args or {}, ensure_ascii=False)}})
            continue
        name = obj.get("name") or obj.get("herramienta") or obj.get("tool") or obj.get("function")
        args = obj.get("arguments", obj.get("argumentos", obj.get("args", obj.get("parameters", {}))))
        if isinstance(args, str):
            args = _loads_lenient(args) or {}
        if name in valid_names:
            calls.append({"id": f"txt_{uuid.uuid4().hex[:10]}", "type": "function",
                          "function": {"name": name, "arguments": json.dumps(args or {}, ensure_ascii=False)}})
    return calls


def strip_tool_text(text):
    if "</think>" in text and "<think>" not in text:
        text = text.split("</think>", 1)[1]
    text = re.sub(r"<tool_call>.*?(</tool_call>|$)", "", text, flags=re.S)
    text = re.sub(r"<function=[\w.\-]+>.*?(</function>|$)", "", text, flags=re.S)
    text = re.sub(r"\[TOOL_REQUEST\].*?(\[END_TOOL_REQUEST\]|$)", "", text, flags=re.S)
    text = re.sub(r"<think(ing)?>.*?(</think(ing)?>|$)", "", text, flags=re.S)
    return text.strip()


def probe(model_id, timeout=30):
    """Prueba rápida (1 mensaje corto, sin streaming) para saber si un modelo está operativo.
    Devuelve {"ok": bool, "kind", "motivo", "solucion", "ms"}. No carga modelos locales (sería lento)."""
    from . import salud
    t0 = time.time()
    try:
        pid, model = split_model(model_id)
        p = provider_cfg(pid)
        if p.get("local"):
            return {"ok": True, "local": True, "ms": 0}
        keys = _keys(pid, p)
        for i, k in enumerate(keys):  # con varias claves (cuentas) basta con que una funcione
            body = {"model": model, "messages": [{"role": "user", "content": "Responde solo: ok"}], "max_tokens": 16, "stream": False}
            r = requests.post(p["base_url"].rstrip("/") + "/chat/completions", headers=_headers(k, p), timeout=(10, timeout), json=body)
            if r.status_code in (400, 422):  # algunos modelos (razonadores) rechazan un límite tan bajo: se reintenta normal
                body["max_tokens"] = 1024
                r = requests.post(p["base_url"].rstrip("/") + "/chat/completions", headers=_headers(k, p), timeout=(10, timeout), json=body)
            if r.status_code == 200:
                salud.ok(model_id)
                if len(keys) > 1:
                    salud.set_clave(model_id, i)
                return {"ok": True, "ms": int((time.time() - t0) * 1000), "clave": i + 1}
            if not (r.status_code in (401, 403) or (r.status_code == 404 and "not found for account" in r.text.lower())):
                break
        ms = int((time.time() - t0) * 1000)
        if r.status_code in (429, 500, 502, 503, 504):
            return {"ok": False, "kind": "ocupado", "ms": ms, "solucion": "Se volverá a probar más tarde.",
                    "motivo": "Ocupado ahora mismo (el servidor está saturado o llegaste al límite por minuto)."}
        e = http_error(r.status_code, r.text[:600], model_id)
        low = r.text.lower()
        if not e.kind and (r.status_code in (404, 405) or (r.status_code in (400, 415, 422) and re.search(
                r"not a chat|does not support chat|not supported for (chat|generatecontent)|model.{0,40}(not found|does not exist|unknown)|"
                r"only supports|embedding|is not a valid model", low))):
            # no responde ni a un mensaje básico: se marca para no ofrecerlo como si funcionara
            salud.mark(model_id, "no_disponible", f"No respondió a una prueba básica ({r.status_code}): {r.text[:140]}",
                       "Elige otro modelo; se volverá a probar mañana.")
            e.kind = "no_disponible"
        st = salud.get(model_id) or {}
        return {"ok": False, "kind": e.kind, "motivo": st.get("motivo") or str(e)[:200], "solucion": st.get("solucion", ""), "ms": ms}
    except APIError as e:
        return {"ok": False, "kind": e.kind, "motivo": str(e)[:240], "solucion": "", "ms": int((time.time() - t0) * 1000)}
    except requests.RequestException as e:
        return {"ok": False, "kind": "sin_conexion", "motivo": f"Sin respuesta ({type(e).__name__}).", "solucion": "Revisa tu internet.",
                "ms": int((time.time() - t0) * 1000)}
