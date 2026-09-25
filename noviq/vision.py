# -*- coding: utf-8 -*-
"""Visión auxiliar: si el modelo principal no puede ver imágenes, un modelo visual las analiza a fondo
y le entrega un resumen en texto (ahorra tokens: una imagen cuesta miles, el resumen unos cientos).
Las descripciones se guardan en caché para no volver a analizar la misma imagen."""
import hashlib
import json
import re
import threading

from .config import CONFIG, DATA_DIR, model_override, set_override

CACHE_FILE = DATA_DIR / "vision_cache.json"
_lock = threading.Lock()
_cache = None

# Orden de preferencia para elegir un modelo con visión entre los disponibles
VISION_PREF = [
    r"gemini-[\d.]+-flash(?!-image)", r"gemini", r"glm-5[\w.-]*", r"glm-4\.\dv", r"gpt-5", r"gpt-4\.1", r"gpt-4o",
    r"claude", r"llama-4-(maverick|scout)", r"qwen[\d.]*-?vl", r"nemotron[\w-]*vl", r"pixtral", r"mistral-(medium|small)-3",
    r"gemma-?3", r"llama-3\.2-\d+b-vision", r"phi-4-multimodal", r"minicpm-v", r"llava", r"moondream", r"vision",
]
VISION_RX = re.compile("|".join(VISION_PREF), re.I)

PROMPT = """Eres un analista visual experto. Otra IA que NO puede ver esta imagen depende de tu descripción para ayudar al usuario.
Analiza la imagen a fondo y responde en español, conciso pero completo (máximo ~350 palabras), con este formato:
1. **Qué es**: tipo de pantalla, programa, página, documento o foto.
2. **Texto visible**: transcribe EXACTAMENTE lo importante (mensajes de error, códigos, rutas, números de línea, valores, títulos, botones).
3. **Problemas o errores detectados** y su causa probable.
4. **Detalles clave** (estado de la interfaz, diseño, datos) que importen para la tarea.
5. **Posibles soluciones** o siguientes pasos.
No inventes nada que no se vea. Si algo no se lee bien, dilo."""


def _load():
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            _cache = {}
    return _cache


def _save():
    with _lock:
        c = _load()
        if len(c) > 400:
            for k in list(c)[:len(c) - 400]:
                c.pop(k, None)
        CACHE_FILE.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")


def key(url):
    return hashlib.sha1(url.encode("utf-8", "ignore")).hexdigest()


def cached(url):
    return _load().get(key(url))


def looks_vision(model_id):
    return bool(VISION_RX.search(model_id.split("::", 1)[-1]))


def lacks_vision(model_id):
    """¿El modelo NO puede ver imágenes? (aprendido por error, o modelo local sin nombre de visión)."""
    ov = model_override(model_id)
    if ov.get("no_vision"):
        return True
    if ov.get("vision"):
        return False
    pid = model_id.split("::", 1)[0] if "::" in model_id else "nvidia"
    if CONFIG["providers"].get(pid, {}).get("local") and not looks_vision(model_id):
        return True
    return False


def candidates(exclude=()):
    from .providers import _models_cache, list_models
    forced = (CONFIG.get("modelo_vision") or "").strip()
    out = [forced] if forced else []
    pool = []
    for pid, p in CONFIG["providers"].items():
        if not p.get("enabled"):
            continue
        info = _models_cache.get(pid) or list_models(pid)
        pool += [f"{pid}::{m}" for m in info.get("models", [])]
    ovs = CONFIG.get("model_overrides", {})
    pool = [m for m in pool if not ovs.get(m, {}).get("no_vision")]
    learned = [m for m in pool if ovs.get(m, {}).get("vision")]
    out += learned
    for pat in VISION_PREF:
        rx = re.compile(pat, re.I)
        out += [m for m in pool if rx.search(m.split("::", 1)[1]) and not m.split("::")[0] in ("ollama", "lmstudio")]
    out += [m for m in pool if looks_vision(m)]  # locales con visión al final
    seen, res = set(), []
    from . import salud
    for m in out:
        if m and m not in seen and m not in exclude and not salud.blocked(m):
            seen.add(m)
            res.append(m)
    return res


def describe(url, contexto="", emit=None, exclude=()):
    """Devuelve (descripcion, modelo) o (None, error)."""
    k = key(url)
    c = _load()
    if k in c:
        return c[k]["texto"], c[k]["modelo"]
    from .providers import APIError, stream_chat
    last = "no hay modelos con visión disponibles (activa Gemini, NVIDIA u otro proveedor con visión)"
    for m in candidates(exclude)[:4]:
        if emit:
            emit("status", {"text": f"Analizando la imagen con {m.split('::')[-1]}…"})
        msgs = [{"role": "system", "content": PROMPT},
                {"role": "user", "content": [{"type": "text", "text": "Contexto del usuario: " + (contexto or "(sin texto)")[:600]},
                                             {"type": "image_url", "image_url": {"url": url}}]}]
        try:
            raw, reasoning, _, _ = stream_chat(m, msgs, None, lambda *a: None, threading.Event(),
                                               extra={"max_tokens": 3000}, max_attempts=2)
            from .providers import strip_tool_text
            txt = strip_tool_text(raw).strip()
            if len(txt) < 20:
                raise APIError("descripción vacía")
            set_override(m, "vision", True)
            c[k] = {"texto": txt, "modelo": m}
            _save()
            return txt, m
        except APIError as e:
            t = str(e).lower()
            if any(w in t for w in ("image", "vision", "multimodal")) and not getattr(e, "kind", None):
                set_override(m, "no_vision", True)
            last = f"{m}: {str(e)[:200]}"
    return None, last


def replace_images(msgs, only_cached=False):
    """Sustituye imágenes por su descripción (in-place). Con only_cached=True solo usa la caché."""
    for m in msgs:
        c = m.get("content")
        if not isinstance(c, list):
            continue
        parts = []
        for p in c:
            if p.get("type") == "image_url":
                url = p.get("image_url", {}).get("url", "")
                d = cached(url)
                if d:
                    parts.append(f"[Imagen analizada por {d['modelo'].split('::')[-1]}]:\n{d['texto']}")
                elif not only_cached:
                    parts.append("[Imagen no disponible: no se pudo analizar]")
                else:
                    parts.append(None)
            else:
                parts.append(p.get("text", ""))
        if None in parts:  # quedan imágenes sin descripción: se conserva el formato con imágenes
            continue
        m["content"] = "\n\n".join(x for x in parts if x)


def ensure_descriptions(conv, emit):
    """Analiza (y guarda en caché) todas las imágenes de la conversación que aún no tienen descripción."""
    errors = []
    for m in conv["messages"]:
        c = m.get("content")
        if not isinstance(c, list):
            continue
        ctx = " ".join(p.get("text", "") for p in c if p.get("type") == "text")
        for p in c:
            if p.get("type") == "image_url":
                url = p.get("image_url", {}).get("url", "")
                if not cached(url):
                    txt, info = describe(url, ctx, emit)
                    if not txt:
                        errors.append(info)
    return errors
