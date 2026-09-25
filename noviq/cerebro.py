# -*- coding: utf-8 -*-
"""Cerebro de vanguardia: antes de construir algo nuevo, el modelo GRATUITO más inteligente disponible
(el que más razona) diseña el plan completo con razonamiento alto. Luego el modelo de trabajo (que puede ser
otro, incluso uno local) lo ejecuta paso a paso. Así el plan sale de la mejor IA aunque el trabajo lo haga otra.

- El cerebro se elige solo (catalogo.ranking) o se fija en Ajustes (modelo_cerebro).
- Si el cerebro falla o no hay ninguno, Noviark sigue como siempre (la IA principal planifica).
- Un plan es un JSON con resumen, tecnología, estructura de archivos, tareas y pruebas; las tareas se cargan
  en la lista de tareas y el plan se adjunta al pedido del usuario para que cualquier IA (y los relevos) lo sigan.
"""
import json
import re

from . import estado as E
from . import indice
from .config import CONFIG, meta_dir, model_override
from .providers import APIError, stream_chat

PLAN_RX = re.compile(r"\b(crea|cre[ae]r|cr[eé]ame|haz|hac(er|me|erme)|desarroll|program|constru|implement|diseñ|arma|"
                     r"genera|migra|refactoriz|rehac|necesito (una?|un) |quiero (una?|un) )\w*", re.I)
MARK = "[PLAN DEL ARQUITECTO"

SYSTEM = """Eres el ARQUITECTO principal de Noviark, un equipo de IAs que construye programas reales en la PC del usuario (Windows).
Tu trabajo NO es programar ahora: es pensar a fondo y diseñar el plan para construir el programa COMPLETO y funcional,
de modo que otra IA (quizá más pequeña) lo ejecute paso a paso sin perderse.
Analiza el pedido, elige la tecnología más simple que cumpla todo, define la estructura de archivos y divide el trabajo
en 4-10 tareas pequeñas, concretas y verificables (cada una deja algo que funciona y se puede probar).
Incluye lo que el usuario no pidió explícitamente pero necesita (manejo de errores, instrucciones de uso, dependencias).
Si ya hay un proyecto con código, planifica SOBRE lo existente (no rehacer lo que ya funciona).
Responde SOLO con un JSON válido (sin texto antes ni después) con esta forma:
{"resumen": "qué se va a construir, en 1-3 frases",
 "tecnologia": "lenguaje/frameworks y por qué",
 "estructura": ["ruta/archivo: para qué sirve", "..."],
 "tareas": ["1 tarea concreta", "..."],
 "pruebas": "cómo comprobar que todo funciona",
 "riesgos": ["posible problema y cómo evitarlo"]}
Escribe en español."""


def _text(content):
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return str(content or "")


def needs_plan(conv):
    """¿Es el inicio de un trabajo de construcción nuevo que merece un plan del cerebro?"""
    V = CONFIG.get("vanguardia") or {}
    if not V.get("planificar", True) or (CONFIG.get("modelo_cerebro") or "auto") == "no":
        return None
    if any(t.get("estado") in ("pendiente", "en_progreso") for t in conv.get("tasks") or []):
        return None
    msgs = conv.get("messages") or []
    if not msgs or msgs[-1].get("role") != "user":
        return None
    txt = _text(msgs[-1].get("content")).strip()
    if MARK in txt or txt.startswith("[") or len(txt) < 30:
        return None
    try:
        from . import decisor  # decisión rápida tipo «System One» (Jev si está configurado; si no, reglas)
        if not decisor.necesita_plan(txt) or decisor.complejidad(txt) == "bajo":
            return None
    except Exception:
        if not PLAN_RX.search(txt):
            return None
    return txt


def brain_models(main_model):
    forced = (CONFIG.get("modelo_cerebro") or "auto").strip()
    if forced and forced not in ("auto", "no"):
        return [forced]
    from . import catalogo as K
    try:
        infos = K.all_infos()
    except Exception:
        return []
    from . import salud
    out = [m for m in K.ranking(infos, need_tools=False, n=4) if not salud.blocked(m)]
    if not out:
        return []
    # si la IA principal ya es la mejor, planifica ella misma (con razonamiento alto) y las demás de respaldo
    mi = infos.get(main_model)
    if mi and not salud.blocked(main_model) and mi.get("cerebro", -1) >= infos[out[0]]["cerebro"]:
        return [main_model] + [m for m in out if m != main_model]
    return out


def _parse(raw):
    s = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()
    m = re.search(r"\{.*\}", s, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:
        try:
            d = json.loads(re.sub(r",\s*([}\]])", r"\1", m.group(0)))
        except Exception:
            return None
    tareas = [str(t).strip() for t in d.get("tareas") or [] if str(t).strip()]
    return d if tareas else None


def format_plan(d, model):
    L = [f"{MARK} — diseñado por {model.split('::')[-1]} con razonamiento alto. Síguelo; las tareas ya están cargadas]"]
    if d.get("resumen"):
        L.append("Resumen: " + str(d["resumen"]))
    if d.get("tecnologia"):
        L.append("Tecnología: " + str(d["tecnologia"]))
    if d.get("estructura"):
        L.append("Estructura:\n" + "\n".join(f"- {x}" for x in d["estructura"][:25]))
    L.append("Tareas:\n" + "\n".join(f"{k}. {t}" for k, t in enumerate(d["tareas"][:10], 1)))
    if d.get("pruebas"):
        L.append("Pruebas: " + str(d["pruebas"]))
    if d.get("riesgos"):
        L.append("Cuidado con:\n" + "\n".join(f"- {x}" for x in d["riesgos"][:6]))
    return "\n".join(L)


# ───────────── Revisión del plan por el usuario (cuenta regresiva editable) ─────────────
PLANS = {}  # id → {"event", "accion", "plan", "editando"}


def review(conv, emit, stop_ev, d, modelo=""):
    """Muestra el plan al usuario con una cuenta regresiva (revisar_plan_seg). Si no hace nada, se aprueba solo;
    si empieza a editarlo, la cuenta se detiene hasta que pulse «Aprobar». Devuelve el plan (editado o no) o None
    si lo descarta."""
    seg = int(CONFIG.get("revisar_plan_seg", 30) or 0)
    if seg <= 0 or conv.get("programada"):
        return d
    import time
    import uuid
    rid = uuid.uuid4().hex[:12]
    st = PLANS[rid] = {"event": __import__("threading").Event(), "accion": None, "plan": None, "editando": False}
    emit("plan_review", {"id": rid, "plan": d, "segundos": seg, "modelo": modelo.split("::")[-1]})
    t0 = time.time()
    try:
        while not st["event"].wait(0.4):
            if stop_ev.is_set():
                return None
            lim = 1800 if st["editando"] else seg
            if time.time() - t0 > lim:
                st["accion"] = "aprobar"
                break
        if st["accion"] == "cancelar":
            emit("notice", {"text": "✖ Plan descartado por el usuario: la IA trabajará sin él."})
            return None
        nd = st.get("plan") or d
        if st.get("plan"):
            nd = dict(d, **{k: v for k, v in st["plan"].items() if v})
            nd["tareas"] = [t.strip() for t in nd.get("tareas") or [] if str(t).strip()] or d["tareas"]
        emit("plan_done", {"id": rid, "editado": bool(st.get("plan")), "auto": time.time() - t0 >= seg and not st["editando"]})
        return nd
    finally:
        PLANS.pop(rid, None)


def responder(rid, accion, plan=None):
    st = PLANS.get(rid)
    if not st:
        return False
    if accion == "editando":
        st["editando"] = True
        return True
    st["accion"] = accion
    if plan:
        st["plan"] = plan
    st["event"].set()
    return True


def plan(conv, cwd, emit, stop_ev, main_model):
    """Crea el plan con el cerebro. Devuelve True si se creó."""
    pedido = needs_plan(conv)
    if not pedido:
        return False
    models = brain_models(main_model)
    if not models:
        return False
    ctx = ""
    try:
        if cwd.exists() and any(cwd.iterdir()):
            mp = indice.compact_map(cwd, meta_dir(conv["project"]) if conv.get("project") else None, 2500)
            if mp:
                ctx += "\nPROYECTO EXISTENTE (mapa del código):\n" + mp
    except Exception:
        pass
    est = E.build(conv, max_actions=10) or ""
    if est:
        ctx += "\n\n" + est[:2500]
    prev = [_text(m.get("content"))[:600] for m in (conv.get("messages") or [])[:-1]
            if m.get("role") == "user" and not _text(m.get("content")).startswith("[")][-2:]
    user = f"Carpeta del proyecto: {cwd}\n" + ("Pedidos anteriores del usuario:\n- " + "\n- ".join(prev) + "\n\n" if prev else "") + \
        f"PEDIDO ACTUAL:\n{pedido[:6000]}\n{ctx}"
    from . import salud
    tried = 0
    for mid in models:
        if stop_ev.is_set() or tried >= 2:
            break
        if salud.blocked(mid):
            continue
        tried += 1
        name = mid.split("::")[-1]
        emit("status", {"text": f"🧠 {name} (cerebro de vanguardia) está diseñando el plan con razonamiento alto…"})
        chars = [0]

        emit("plan_stream", {"inicio": True, "modelo": name})

        def em(kind, p):
            if kind == "reasoning":
                chars[0] += len(p.get("text", ""))
                emit("plan_stream", {"tipo": "razonamiento", "text": p.get("text", "")})
                if chars[0] % 1500 < len(p.get("text", "")):
                    emit("status", {"text": f"🧠 {name} está pensando el plan… ({chars[0] // 1000} mil caracteres de razonamiento)"})
            elif kind == "token":
                emit("plan_stream", {"tipo": "texto", "text": p.get("text", "")})
            elif kind in ("status", "fase"):
                emit(kind, p)
        ov = model_override(mid)
        local = CONFIG["providers"].get(mid.split("::")[0], {}).get("local")
        extra = {"max_tokens": 12000}
        if not ov.get("no_reasoning_effort") and not local:
            extra["reasoning_effort"] = "high"
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
        if ov.get("no_system"):
            msgs = [{"role": "user", "content": SYSTEM + "\n\n" + user}]
        d = None
        for attempt in range(2):
            try:
                from .guardian import Guardian
                g = Guardian(max_chars=60000, max_secs=420)  # el cerebro puede pensar mucho, pero no para siempre ni en bucle
                raw, _reasoning, _calls, _fin = stream_chat(mid, msgs, None, em, stop_ev, extra=extra, max_attempts=2, guard=g)
                if _fin == "guardian":
                    emit("status", {"text": f"🧠 {name} {g.tripped}; pruebo otro cerebro…"})
                d = _parse(raw)
                break
            except APIError as e:
                if "reasoning" in str(e).lower() and "reasoning_effort" in extra:
                    extra.pop("reasoning_effort")
                    continue
                emit("status", {"text": f"🧠 {name} no pudo planificar ({str(e)[:90]}); pruebo otro…"})
                break
            except Exception:
                break
        if not d:
            continue
        d = review(conv, emit, stop_ev, d, mid)
        if d is None:
            return False
        tareas = d["tareas"][:12]
        tasks = [{"contenido": t[:300], "estado": "en_progreso" if k == 0 else "pendiente"} for k, t in enumerate(tareas)]
        conv["tasks"] = tasks
        emit("tasks", {"tasks": tasks})
        texto = format_plan(d, mid)
        last = conv["messages"][-1]
        if isinstance(last.get("content"), list):
            last["content"] = last["content"] + [{"type": "text", "text": "\n\n" + texto}]
        else:
            last["content"] = str(last.get("content") or "") + "\n\n" + texto
        conv["plan_cerebro"] = {"modelo": mid, "plan": d}
        emit("notice", {"text": f"🧠 Plan de vanguardia creado por {name}: {len(tasks)} tareas. "
                                + (f"{str(d.get('resumen', ''))[:220]}" if d.get("resumen") else "")})
        return True
    emit("status", {"text": "El cerebro no respondió; la IA principal planificará por su cuenta."})
    return False
