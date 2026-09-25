# -*- coding: utf-8 -*-
"""Modo compacto para IA local (o de poco contexto): la IA trabaja PASO A PASO con un contexto pequeño
que siempre cabe en su ventana, sin perder el hilo.

Técnicas aplicadas (las que mejor funcionan hoy en agentes de programación):
  1. Memoria de trabajo estructurada: el ESTADO DEL TRABAJO (pedido, plan, hecho, archivos, errores,
     siguiente paso) lo mantiene el programa y va siempre al inicio del prompt.
  2. Mapa del código ultracompacto (agente indexador, sin LLM): la IA sabe qué hay sin leer archivos.
  3. Enmascarado de observaciones (JetBrains, NeurIPS 2025): los resultados de herramientas viejos se
     reemplazan por una línea; se conservan íntegros solo los últimos. Ahorra ~50 % sin perder calidad.
  4. Ventana por tarea: al completar una tarea se "limpia la mesa": la siguiente empieza con un contexto
     nuevo (estado + mapa + tarea), no con todo el historial.
  5. Presupuesto de tokens: todo se mide y se recorta para que prompt + respuesta quepan en num_ctx.
  6. Herramientas reducidas y descripciones cortas (las 28 herramientas completas ocupan miles de tokens).
"""
import json

from . import estado as E
from . import indice
from .config import CONFIG, meta_dir, model_override

COMPACT_TOOLS = ["crear_proyecto", "cambiar_proyecto", "escribir_archivo", "editar_archivo", "leer_archivo",
                 "listar_directorio", "buscar_en_archivos", "ejecutar_powershell", "ejecutar_python",
                 "actualizar_tareas", "localizar_error", "probar_proyecto", "deshacer_cambio", "pedir_ayuda_usuario",
                 "memoria", "agente_pc", "diagnosticar", "probar_web"]


def is_compact(model_id):
    from .local import cfg_local, context_window
    m = cfg_local().get("modo_compacto", "auto")
    if m == "siempre":
        return True
    if m == "nunca":
        return False
    pid = model_id.split("::", 1)[0] if "::" in model_id else "nvidia"
    if CONFIG["providers"].get(pid, {}).get("local"):
        return True
    ctx, _ = context_window(model_id)
    return bool(ctx and ctx < 40000)


def budget(model_id):
    """Tokens de contexto disponibles para el modelo."""
    from .local import context_window
    ctx, _ = context_window(model_id)
    if ctx:
        return ctx
    pid = model_id.split("::", 1)[0] if "::" in model_id else "nvidia"
    chars = CONFIG["providers"].get(pid, {}).get("context_chars") or 200000
    return int(chars / 3.5)


def tok(obj):
    s = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    return int(len(s) / 3.2) + 1


def compact_tools(tool_defs):
    out = []
    for t in tool_defs:
        f = t["function"]
        if f["name"] not in COMPACT_TOOLS:
            continue
        desc = f.get("description", "").split(". ")[0][:150]
        props = {}
        for k, v in (f.get("parameters", {}).get("properties") or {}).items():
            nv = {kk: vv for kk, vv in v.items() if kk in ("type", "enum", "items")}
            if k in ("ruta", "comando", "codigo", "texto_error", "ruta_o_url", "desde_linea", "despues_de_linea", "acciones"):
                nv["description"] = (v.get("description") or "")[:60]
            props[k] = nv
        out.append({"type": "function", "function": {"name": f["name"], "description": desc, "parameters": {
            "type": "object", "properties": props, "required": f.get("parameters", {}).get("required", [])}}})
    return out


def system_prompt(conv, cwd, text_tools=None, handoff=None, map_chars=1500):
    tasks = conv.get("tasks") or []
    cur = next((t for t in tasks if t.get("estado") == "en_progreso"), None) or \
        next((t for t in tasks if t.get("estado") == "pendiente"), None)
    s = f"""Eres Noviark, un agente de programación que trabaja con herramientas reales en la PC del usuario. Responde en español.
REGLAS (tu memoria es corta, sigue esto al pie de la letra):
1. ACTÚA con herramientas; piensa poco. Nunca termines solo con un plan.
2. Si el trabajo tiene varios pasos y no hay plan, primero `actualizar_tareas` con 3-8 tareas pequeñas.
3. Trabaja SOLO en el PASO ACTUAL. Al terminarlo, `actualizar_tareas` marcándolo completada (y el siguiente en_progreso).
4. Archivos: SOLO con escribir_archivo/editar_archivo (NUNCA con PowerShell). Escribe COMPLETO; si pasa de ~150 líneas, por partes (escribir_archivo modo='agregar'). No escribas código dentro del razonamiento.
5. Si algo no funciona: 1) `diagnosticar` (o `probar_web` en webs/juegos) para ver los errores REALES; 2) `leer_archivo` de esas líneas; 3) `editar_archivo` con desde_linea/hasta_linea o texto exacto SIN números de línea; 4) vuelve a `diagnosticar`/`probar_web` para verificar. Si un archivo está casi vacío o dañado, reescríbelo completo (sobrescribir=true).
6. NO repitas lo hecho ni la misma llamada: el ESTADO y el MAPA de abajo son la verdad. Si una herramienta falla, lee su error: dice qué hacer.
7. No digas «listo» ni marques completada una tarea sin verificarla con una herramienta.
Carpeta de trabajo: {cwd}
"""
    if cur:
        s += f"\n▶ PASO ACTUAL: {cur['contenido']}\n"
    est = E.build(conv, max_actions=12)
    if est:
        s += "\n" + est[:3500] + "\n"
    mp = indice.compact_map(cwd, meta_dir(conv["project"]) if conv.get("project") else None, map_chars) if cwd.exists() else ""
    if mp:
        s += "\n### MAPA DEL CÓDIGO (nombre@línea; usa leer_archivo con desde_linea/hasta_linea para ver detalles)\n" + mp + "\n"
    if handoff:
        s += f"\n(Relevo: la IA anterior {handoff} falló; continúa donde quedó.)\n"
    if conv.get("idioma") == "en":
        s += "\nLANGUAGE: reply in English (the user's interface is in English).\n"
    try:
        from . import aprendizaje as A
        rg = A.reglas(450)
        if rg:
            s += "\n" + rg + "\n"
    except Exception:
        pass
    extra = (CONFIG.get("system_prompt") or "").strip()
    if extra:
        s += "\nPreferencias del usuario: " + extra[:400] + "\n"
    if text_tools:
        s += ("\nHERRAMIENTAS: para usar una escribe exactamente:\n<tool_call>\n{\"name\": \"herramienta\", \"arguments\": {...}}\n"
              "</tool_call>\ny espera el resultado. Disponibles:\n")
        for t in text_tools:
            f = t["function"]
            ps = ", ".join(f.get("parameters", {}).get("properties", {}))
            s += f"- {f['name']}({ps}): {f.get('description', '')[:100]}\n"
    return s


def _mask(msgs, keep_results=3, keep_calls=2):
    """Enmascarado de observaciones: resultados viejos → 1 línea; argumentos largos viejos → recortados."""
    tool_idx = [i for i, m in enumerate(msgs) if m["role"] == "tool"]
    for i in tool_idx[:-keep_results]:
        c = str(msgs[i].get("content", ""))
        first = c.strip().split("\n", 1)[0][:110]
        msgs[i]["content"] = f"[resultado anterior resumido: {first}]"
    for i in tool_idx[-keep_results:]:
        c = str(msgs[i].get("content", ""))
        if len(c) > 2400:
            msgs[i]["content"] = c[:1600] + "\n…[recortado]…\n" + c[-600:]
    asst = [i for i, m in enumerate(msgs) if m.get("tool_calls")]
    for i in asst[:-keep_calls]:
        new = []
        for tc in msgs[i]["tool_calls"]:
            tc = json.loads(json.dumps(tc))
            try:
                a = json.loads(tc["function"]["arguments"])
                for k, v in list(a.items()):
                    if isinstance(v, str) and len(v) > 200:
                        a[k] = v[:120] + f"…[{len(v)} caracteres, ya aplicado]"
                    elif isinstance(v, list) and len(json.dumps(v)) > 300:
                        a[k] = "[…ya aplicado]"
                tc["function"]["arguments"] = json.dumps(a, ensure_ascii=False)
            except Exception:
                pass
            new.append(tc)
        msgs[i]["tool_calls"] = new
    for m in msgs:  # el razonamiento/texto largo del asistente también se acorta
        if m["role"] == "assistant" and isinstance(m.get("content"), str) and len(m["content"]) > 1500 and m is not msgs[-1]:
            m["content"] = m["content"][:900] + "…"


def build(conv, mode, tool_defs, model_id, cwd, handoff=None):
    """Mensajes + herramientas que caben en el contexto del modelo. Devuelve (msgs, tools, info)."""
    from .agent import build_messages
    ctx = budget(model_id)
    ov = model_override(model_id)
    reserve = min(int(ov.get("max_tokens") or CONFIG.get("max_tokens", 16384)), max(1024, int(ctx * 0.28)))
    tools = compact_tools(tool_defs) if mode != "ninguno" else []
    seg = int(conv.get("seg_start") or 0)
    base = build_messages(conv, "nativo" if mode == "nativo" else mode, tool_defs, model_id, handoff, raw=True)
    msgs = base[seg:] if seg < len(base) else []
    while msgs and msgs[0]["role"] != "user":  # la ventana debe empezar en un mensaje del usuario
        msgs.pop(0)
    if not msgs:
        msgs = [{"role": "user", "content": "[Continúa con el PASO ACTUAL según el ESTADO del trabajo.]"}]
    _mask(msgs)
    map_chars = 1500 if ctx >= 12000 else 700
    for attempt in range(6):
        sysmsg = system_prompt(conv, cwd, tools if mode == "texto" else None, handoff, map_chars)
        used = tok(sysmsg) + tok(msgs) + (tok(tools) if mode == "nativo" else 0)
        if used + reserve <= ctx or len(msgs) <= 1:
            break
        # 1) recorta el mapa; 2) descarta los turnos más viejos de la ventana
        if map_chars > 400:
            map_chars //= 2
            continue
        j = 1
        while j < len(msgs) and msgs[j]["role"] != "user":
            j += 1
        if j >= len(msgs):
            _mask(msgs, keep_results=1, keep_calls=1)
            continue
        del msgs[:j]
    if mode in ("texto", "ninguno"):
        from .agent import to_text_mode
        msgs = to_text_mode(msgs)
    info = {"usado": used, "limite": ctx, "reserva": reserve, "compacto": True}
    return [{"role": "system", "content": sysmsg}] + msgs, (tools if mode == "nativo" else None), info


def step_message(conv):
    tasks = conv.get("tasks") or []
    n = len(tasks)
    cur = next((i for i, t in enumerate(tasks) if t.get("estado") == "en_progreso"), None)
    if cur is None:
        cur = next((i for i, t in enumerate(tasks) if t.get("estado") == "pendiente"), None)
    if cur is None:
        return None
    done = sum(t.get("estado") == "completada" for t in tasks)
    return (f"[PASO {cur + 1}/{n}] ({done} completadas) Tarea actual: «{tasks[cur]['contenido']}». "
            "Lo anterior ya está hecho (ver ESTADO y MAPA). Hazla AHORA con las herramientas y, al terminar, "
            "márcala completada con actualizar_tareas.")
