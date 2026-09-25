# -*- coding: utf-8 -*-
"""Subagentes: agentes secundarios que hacen una tarea concreta con su propio modelo y herramientas,
y devuelven un resumen a la IA principal. Se usan para controlar el navegador (Chrome/Edge) aunque la IA
principal no sepa usar herramientas, y ahorran tokens: las 50+ herramientas del navegador solo se envían
al subagente, no en cada mensaje de la IA principal."""
import json
import re
import threading

from .config import CONFIG, model_override

TOOL_PREF = [r"gemini-[\d.]+-(flash|pro)", r"gpt-5", r"gpt-4\.1", r"gpt-4o", r"claude", r"glm-5", r"glm-4\.[5-9]",
             r"qwen3", r"kimi-k2", r"deepseek-v3", r"llama-4", r"llama-3\.3-70b", r"mistral-(large|medium)", r"grok"]

BROWSER_SYSTEM = """Eres un agente experto en controlar el navegador web (Chrome/Edge) con herramientas.
Completa la TAREA de forma autónoma, paso a paso:
- Usa browser_navigate para abrir páginas y browser_snapshot para LEER la página: verás los elementos con su [ref=eN].
- Para hacer clic, escribir o elegir opciones (browser_click, browser_type, browser_fill_form, browser_select_option, browser_press_key)
  pasa ese ref exacto en el parámetro que pida la herramienta (por ejemplo target="e4") y sigue exactamente su esquema de parámetros.
- Después de cada acción importante vuelve a tomar un snapshot para verificar el resultado.
- Si aparece un inicio de sesión, captcha o algo que requiera al usuario, DETENTE y explícalo en tu resumen.
- No inventes datos: todo lo que informes debe venir de la página.
Al terminar responde SOLO con un RESUMEN en español: qué hiciste, qué encontraste (datos exactos, URLs) y qué falló si algo falló."""


def _blocked(m):
    try:
        from . import salud
        return salud.blocked(m)
    except Exception:
        return False


def aux_models(conv, exclude=()):
    """Modelos capaces de usar herramientas nativas, en orden de preferencia."""
    from .providers import _models_cache, list_models
    forced = (CONFIG.get("modelo_auxiliar") or "").strip()
    out = [forced] if forced else []
    ovs = CONFIG.get("model_overrides", {})
    main = conv.get("model") or CONFIG.get("model")
    if main and ovs.get(main, {}).get("tool_mode") != "texto":
        out.append(main)
    out += [m for m in CONFIG.get("fallback_models") or [] if ovs.get(m, {}).get("tool_mode") != "texto"]
    out += [m for m, o in ovs.items() if o.get("tool_mode") == "nativo"]
    pool = []
    for pid, p in CONFIG["providers"].items():
        if p.get("enabled"):
            info = _models_cache.get(pid) or list_models(pid)
            pool += [f"{pid}::{m}" for m in info.get("models", [])]
    for pat in TOOL_PREF:
        rx = re.compile(pat, re.I)
        out += [m for m in pool if rx.search(m.split("::", 1)[1]) and ovs.get(m, {}).get("tool_mode") != "texto"]
    seen, res = set(), []
    for m in out:
        if m and m not in seen and m not in exclude and not _blocked(m):
            seen.add(m)
            res.append(m)
    return res


_RECURSOS = {"pc": threading.Lock(), "navegador": threading.Lock()}


class recurso:
    """El navegador y el escritorio son únicos: si otra conversación los está usando, se espera el turno."""
    def __init__(self, name, ctx):
        self.lock, self.ctx, self.name = _RECURSOS[name], ctx, name

    def __enter__(self):
        if not self.lock.acquire(timeout=1):
            self.ctx.emit("tool_output", {"id": self.ctx.call_id, "text": f"⏳ Otra conversación está usando el {self.name}; espero mi turno…\n"})
            while not self.lock.acquire(timeout=2):
                if self.ctx.stop_ev.is_set():
                    raise RuntimeError("Detenido por el usuario.")
        return self

    def __exit__(self, *a):
        self.lock.release()


def run(conv, ctx, task, tools, system, max_steps=30, label="Subagente", executor=None, models=None, prefix=""):
    """Bucle de un subagente con su propio modelo. executor(name, args) ejecuta cada herramienta."""
    from .mcp import MANAGER
    from .providers import APIError, stream_chat, strip_tool_text
    if not tools:
        return None
    executor = executor or (lambda n, a: MANAGER.call(n, a))
    log = lambda t: ctx.emit("tool_output", {"id": ctx.call_id, "text": f"{prefix}{t}\n"})
    for model in (models or aux_models(conv))[:4]:
        log(f"🤖 {label} usando {model.split('::')[-1]}")
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": task}]
        text = ""
        try:
            for step in range(max_steps):
                if ctx.stop_ev.is_set():
                    return "Detenido por el usuario."
                from .guardian import Guardian
                raw, reasoning, calls, finish = stream_chat(model, msgs, tools, lambda *a: None, ctx.stop_ev,
                                                            max_attempts=3, guard=Guardian())
                if finish == "guardian" and not calls:
                    log(f"  🛡 {model.split('::')[-1]} se quedó pensando en bucle; paso a otro modelo")
                    raise APIError("razonamiento en bucle")
                text = strip_tool_text(raw)
                if not calls:
                    if step == 0 and not text.strip():
                        raise APIError("sin respuesta")
                    return text.strip() or "(el subagente terminó sin resumen)"
                msgs.append({"role": "assistant", "content": text, "tool_calls": calls})
                for tc in calls:
                    name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"]["arguments"] or "{}")
                    except Exception:
                        args = {}
                    short = next((str(v) for v in args.values() if isinstance(v, str)), "")[:90].replace("\n", " ")
                    log(f"  · {name.split('__')[-1]} {short}")
                    try:
                        res = executor(name, args)
                    except Exception as e:
                        res = f"ERROR: {type(e).__name__}: {e}"
                    txt = res.get("text", "") if isinstance(res, dict) else str(res)
                    msgs.append({"role": "tool", "tool_call_id": tc["id"], "name": name, "content": txt[:12000]})
                    imgs = res.get("images") if isinstance(res, dict) else None
                    if imgs:
                        from . import vision as V
                        if V.lacks_vision(model):
                            try:
                                desc = V.describe(imgs[0], "Captura del escritorio para un agente que maneja el PC: describe ventanas, "
                                                           "botones, campos y textos visibles con su posición aproximada (x,y).")[0]
                            except Exception:
                                desc = ""
                            if desc:
                                msgs.append({"role": "user", "content": "[Descripción de la captura por el ayudante visual]\n" + desc})
                        else:
                            msgs.append({"role": "user", "content": [{"type": "text", "text": "[Captura de pantalla]"}]
                                         + [{"type": "image_url", "image_url": {"url": u}} for u in imgs[:1]]})
                for m in msgs[:-6]:
                    if m["role"] == "tool" and len(m["content"]) > 1500:
                        m["content"] = m["content"][:1200] + "\n...[recortado]"
                    if m.get("tool_calls"):
                        for tc in m["tool_calls"]:
                            if len(tc["function"]["arguments"]) > 1500:
                                tc["function"]["arguments"] = json.dumps({"_nota": "argumentos largos omitidos (ya aplicados)"})
            return "El subagente alcanzó el máximo de pasos. Último estado:\n" + (text or "")
        except APIError as e:
            t = str(e).lower()
            if any(w in t for w in ("tool", "function")) and not getattr(e, "kind", None) and "not found for account" not in t:
                from .config import set_override
                set_override(model, "tool_mode", "texto")
            log(f"  ⚠ {model.split('::')[-1]} falló: {str(e)[:120]}")
            continue
    return None


# ═════════════════════ EQUIPO DE AGENTES ═════════════════════
ROLES_PLAN = [
    ("Arquitecto", "Diseña la solución completa: estructura de archivos, tecnologías, módulos y orden de construcción."),
    ("Experto en calidad y riesgos", "Detecta riesgos, casos límite, errores típicos, seguridad y cómo probar cada parte."),
    ("Desarrollador pragmático", "Propón el camino más simple y rápido que funcione bien, con pasos concretos y ejecutables."),
]


def diverse(models, n):
    """Elige n modelos intentando que sean de proveedores distintos."""
    out, used = [], set()
    for m in models:
        p = m.split("::")[0]
        if p not in used:
            out.append(m)
            used.add(p)
        if len(out) >= n:
            return out
    for m in models:
        if m not in out:
            out.append(m)
        if len(out) >= n:
            break
    return out or models[:n]


def plan_team(conv, ctx, objetivo, contexto=""):
    """Varias IAs proponen un plan en paralelo (sin herramientas, barato). Devuelve las propuestas."""
    from .providers import APIError, stream_chat, strip_tool_text
    n = max(2, min(int(CONFIG.get("equipo_max", 3)), 3))
    models = diverse(aux_models(conv) + [conv.get("model") or CONFIG.get("model")], n)
    results = [None] * n
    log = lambda t: ctx.emit("tool_output", {"id": ctx.call_id, "text": t + "\n"})

    def one(i):
        role, focus = ROLES_PLAN[i % len(ROLES_PLAN)]
        model = models[i % len(models)]
        log(f"🧠 {role} → {model.split('::')[-1]} pensando…")
        msgs = [{"role": "system", "content": f"Eres el {role} de un equipo de IAs que planifica un trabajo de software/tecnología. "
                                              f"{focus} Responde en español, en máximo 350 palabras, con una lista numerada de "
                                              "tareas concretas (qué archivo o acción, y cómo verificarla)."},
                {"role": "user", "content": f"OBJETIVO: {objetivo}\n\nCONTEXTO:\n{contexto[:4000]}"}]
        for m in [model] + [x for x in models if x != model]:
            try:
                raw, _, _, _ = stream_chat(m, msgs, None, lambda *a: None, ctx.stop_ev,
                                           extra={"max_tokens": 4000}, max_attempts=2)
                txt = strip_tool_text(raw).strip()
                if txt:
                    results[i] = (role, m, txt[:4000])
                    log(f"  ✔ {role} ({m.split('::')[-1]}) listo")
                    return
            except APIError as e:
                log(f"  ⚠ {m.split('::')[-1]}: {str(e)[:100]}")

    ths = [threading.Thread(target=one, args=(i,), daemon=True) for i in range(n)]
    for t in ths:
        t.start()
    for t in ths:
        t.join(300)
    return [r for r in results if r]


WORKER_TOOLS = ["escribir_archivo", "editar_archivo", "leer_archivo", "listar_directorio", "buscar_archivos",
                "buscar_en_archivos", "mapa_codigo", "localizar_error", "buscar_en_internet", "leer_pagina_web",
                "generar_imagen", "probar_web"]
WORKER_SYSTEM = """Eres "{rol}", un agente de un equipo de IAs que trabaja en el proyecto "{proyecto}" ({cwd}).
El coordinador te asignó UNA tarea. Hazla completa y bien usando las herramientas (escribe archivos completos, sin "...").
{limite}
No hagas tareas que no te asignaron. Al terminar responde SOLO con un resumen breve: archivos creados/modificados,
decisiones importantes (nombres de funciones, rutas, formatos que otros agentes deben respetar) y cualquier problema."""


def work_team(conv, ctx, tareas):
    """Varios agentes trabajan en paralelo en tareas independientes del mismo plan."""
    from . import tools as T
    from .config import CONFIG as C
    tareas = [t for t in tareas if isinstance(t, dict) and t.get("instrucciones")][:6]
    if not tareas:
        return "ERROR: no hay tareas válidas (cada una necesita 'instrucciones')."
    allowed = list(WORKER_TOOLS)
    if C.get("permission_mode") == "auto":
        allowed += ["ejecutar_python", "ejecutar_powershell"]
    tools = [t for t in T.BUILTIN if t["function"]["name"] in allowed]
    pool = aux_models(conv)
    if not pool:
        return "ERROR: no hay modelos con herramientas nativas disponibles para el equipo."
    models = diverse(pool, len(tareas))
    max_par = max(1, min(int(C.get("equipo_max", 3)), 4))
    sem = threading.Semaphore(max_par)
    results = [None] * len(tareas)
    lock = threading.Lock()

    def one(i, tarea):
        with sem:
            rol = tarea.get("rol") or f"Agente {i + 1}"
            norm = lambda x: re.sub(r"^(\./)+", "", str(x).replace("\\", "/").strip())
            archivos = [norm(a) for a in tarea.get("archivos") or [] if a]
            limite = ("Solo puedes crear o modificar ESTOS archivos: " + ", ".join(archivos)) if archivos else \
                "Crea o modifica solo los archivos necesarios para tu tarea."
            sub_ctx = T.ToolContext(conv, ctx.emit, ctx.stop_ev, ctx.call_id)

            def execute(name, args):
                if name not in allowed:
                    return f"ERROR: herramienta no permitida para este agente: {name}"
                if archivos and name in ("escribir_archivo", "editar_archivo"):
                    ruta = norm(args.get("ruta") or "")
                    if not any(ruta == a or ruta.endswith("/" + a) or a.endswith("/" + ruta) for a in archivos):
                        return f"ERROR: {ruta} no está entre tus archivos asignados ({', '.join(archivos)})."
                res = T.FUNCS[name](args, sub_ctx)
                with lock:
                    from . import estado as E
                    E.record_action(conv, name, args, res.get("text", "") if isinstance(res, dict) else res)
                return res

            system = WORKER_SYSTEM.format(rol=rol, proyecto=conv.get("project") or "_General", cwd=sub_ctx.cwd, limite=limite)
            task = f"TAREA: {tarea.get('titulo', '')}\n{tarea['instrucciones']}"
            if tarea.get("contexto"):
                task += "\n\nCONTEXTO DEL PLAN:\n" + str(tarea["contexto"])[:3000]
            order = [models[i]] + [m for m in pool if m != models[i]]
            res = run(conv, sub_ctx, task, tools, system, max_steps=25, label=rol, executor=execute,
                      models=order, prefix=f"[{rol}] ")
            results[i] = (rol, tarea.get("titulo", ""), res or "ERROR: ningún modelo pudo completar la tarea.")

    ths = [threading.Thread(target=one, args=(i, t), daemon=True) for i, t in enumerate(tareas)]
    for t in ths:
        t.start()
    for t in ths:
        t.join(1800)
    out = [f"### {r[0]} — {r[1]}\n{r[2]}" for r in results if r]
    return ("Resultados del equipo (revisa, integra y prueba; corrige incompatibilidades entre partes):\n\n"
            + "\n\n".join(out))


def browser_tools():
    from .mcp import MANAGER
    return [t for t in MANAGER.tool_defs(include_browser=True) if t["function"]["name"].split("__")[-1].startswith("browser_")]
