# -*- coding: utf-8 -*-
"""Bucle del agente: prompt del sistema, contexto, llamadas a herramientas (nativas o por texto)."""
import copy
import json
import re
import threading
import time
import uuid
from pathlib import Path
from datetime import datetime

from . import compacto as C
from . import diagnostico as D
from . import ejecutor as EJ
from . import escalado as ESC
from . import guardian as G
from . import pruebas as PR
from . import estado as E
from . import salud as S
from . import aprendizaje as A
from . import vision as V
from . import tools as T
from .config import CONFIG, OS_NAME, model_override, projects_root, set_override
from .mcp import MANAGER
from .providers import APIError, parse_text_tool_calls, split_model, stream_chat, strip_tool_text

PENDING = {}  # confirmaciones pendientes: id -> {"event", "ok", "always"}


# ───────────── Prompt del sistema ─────────────
def project_tree(p, limit=80):
    lines, n = [], 0
    for x in sorted(p.rglob("*")):
        if any(part in T.SKIP_DIRS or part.startswith(".") for part in x.relative_to(p).parts):
            continue
        n += 1
        if n > limit:
            lines.append("  ...")
            break
        lines.append("  " + x.relative_to(p).as_posix() + ("/" if x.is_dir() else ""))
    return "\n".join(lines) or "  (vacío)"


def system_prompt(conv, text_tools=None, handoff=None):
    ctx = T.ToolContext(conv, lambda *a: None, threading.Event())
    cwd = ctx.cwd
    proj = conv.get("project")
    s = f"""Eres un asistente de IA autónomo y experto que trabaja dentro de "Noviark", una aplicación de escritorio en la PC del usuario ({OS_NAME}). Fecha y hora: {datetime.now():%Y-%m-%d %H:%M}.
Responde en el idioma del usuario (normalmente español), con Markdown claro. Los bloques de código llevan su lenguaje (```python, ```powershell…).

## Cómo trabajas
- Tienes HERRAMIENTAS reales sobre la PC del usuario. Úsalas directamente; no le digas al usuario que haga lo que tú puedes hacer.
- ACTÚA, no solo pienses: tu razonamiento interno debe ser BREVE (máximo ~15 líneas); el trabajo se hace llamando herramientas. NUNCA escribas el código dentro del razonamiento: escríbelo directamente con escribir_archivo/editar_archivo. Nunca termines un turno solo con un plan: ejecútalo en ese mismo momento. (Un guardián corta los razonamientos eternos y los bucles.)
- Sé autónomo: en trabajos de varios pasos tu PRIMERA acción es `actualizar_tareas` con el plan completo; luego ejecútalo paso a paso marcando cada tarea (en_progreso → completada) y termina todo sin pedir confirmaciones innecesarias. Así, si algo falla, otra IA puede continuar exactamente donde quedaste.
- Si existe un "ESTADO DEL TRABAJO" con trabajo previo, NO empieces de cero ni repitas lo hecho: continúa con su "SIGUIENTE PASO". Los archivos listados ahí ya existen.
- PROGRAMAS/APPS/WEBS NUEVOS: primero `crear_proyecto` (se crea su carpeta en Documentos con PowerShell), luego escribe TODOS los archivos completos con `escribir_archivo` (nunca pongas "..." ni omitas partes). Si un archivo es muy largo (más de ~300 líneas), escríbelo por partes con modo='agregar'.
- Después de escribir código, PRUÉBALO (ejecutar_powershell / ejecutar_python: instalar dependencias, ejecutar, compilar, tests; en webs y juegos `probar_web`) y corrige los errores hasta que funcione. Para servidores usa segundo_plano=true.
- ARCHIVOS: créalos y cámbialos SOLO con escribir_archivo / editar_archivo (guardan en UTF-8 y dejan copia de respaldo). NUNCA escribas archivos con ejecutar_powershell (Set-Content, Out-File, here-strings @"…"@): rompe el código y la codificación.
- WEBS Y JUEGOS: librerías por CDN con <script> normal (cdnjs.cloudflare.com; Three.js r128 + OrbitControls de examples/js), sin type="module" si se abre con doble clic; ids del HTML iguales a los del JS; un solo punto de inicio. Al terminar, `probar_web` con acciones (teclas/clics/arrastrar) para comprobar que se ve y responde.

## Depuración metódica (algo falla, o el usuario dice que no funciona / pide revisar o arreglar)
Trabaja como un programador senior, sin adivinar ni reescribir a ciegas:
1. MIDE el problema real: `diagnosticar` (codificación, código incompleto, funciones que no existen o no se cargan, orden de scripts, ids, librerías, sintaxis, y abre la web en un navegador invisible) o `probar_web` en webs/juegos (errores de consola con archivo:línea, archivos que no cargan, captura, teclas/clics). En programas, ejecútalos y lee el error COMPLETO. Si el mensaje del usuario ya trae un DIAGNÓSTICO AUTOMÁTICO, empieza por él.
2. LOCALIZA la causa raíz: `localizar_error` con la traza, `buscar_en_archivos`, `mapa_codigo` y `leer_archivo` solo del rango necesario. El primer error suele causar los demás.
3. CORRIGE lo mínimo con `editar_archivo` (texto_anterior copiado del archivo SIN números de línea, o desde_linea/hasta_linea con los números que viste; despues_de_linea para insertar). Si un archivo está dañado, casi vacío o le falta la mayor parte, reescríbelo COMPLETO con escribir_archivo (sobrescribir=true), sin «...». Si una edición empeora algo, `deshacer_cambio`.
4. VERIFICA: vuelve a ejecutar `diagnosticar` / `probar_web` / el programa. Solo está terminado cuando no quedan errores (y en juegos los controles cambian la imagen). NUNCA marques una tarea como completada ni digas «listo» sin haberlo verificado.
5. Si una herramienta falla 2 veces igual, CAMBIA de estrategia: lee el error (te dice exactamente qué hacer). Nunca repitas la misma llamada.
6. Si el usuario dice que quedó mal, créele: busca el fallo real con diagnosticar/probar_web en vez de volver a leer lo mismo.
- EQUIPO DE IAs: en proyectos medianos/grandes o problemas difíciles, usa `planificar_en_equipo` para que varias IAs propongan planes y combínalos en uno (regístralo con actualizar_tareas). Si el plan tiene partes independientes (archivos distintos), repártelas con `trabajar_en_equipo` (define bien las interfaces: nombres de funciones, rutas, formatos) y después integra, prueba y corrige tú como coordinador.
- NAVEGADOR: para abrir páginas, llenar formularios o sacar datos de sitios web usa `agente_navegador` con una tarea detallada. Si no está disponible o falla, usa `pedir_ayuda_usuario` para que el usuario haga los pasos y te envíe capturas.
- Si necesitas algo que solo el usuario puede hacer (iniciar sesión, conectar un equipo, un dato), usa `pedir_ayuda_usuario` y continúa con su respuesta.
- Para dibujar usa `generar_imagen` (prompt en inglés). Para ver la pantalla usa `captura_pantalla`. Para información actual usa `buscar_en_internet` y `leer_pagina_web`.
- Guarda en `memoria` (alcance 'usuario') datos duraderos que el usuario te cuente. En proyectos, guarda en `memoria` (alcance 'proyecto') las decisiones importantes, el estado y cómo ejecutarlo, para que cualquier IA pueda continuar.
- Si una herramienta falla, analiza el error y reintenta con otra estrategia. No inventes resultados.
- Al terminar, resume brevemente qué hiciste, dónde quedaron los archivos y cómo usarlos.

## Entorno
- Carpeta de proyectos: {projects_root()}
- Directorio de trabajo actual (rutas relativas): {cwd}
"""
    if proj:
        info = T.project_info(proj)
        s += f"- Proyecto activo: **{proj}** (tipo: {info.get('tipo', '?')}). {info.get('descripcion', '')}\n"
        if info.get("instrucciones"):
            s += f"\n## Instrucciones del proyecto\n{info['instrucciones']}\n"
        s += f"\n## Archivos del proyecto\n{project_tree(cwd)}\n"
    else:
        s += "- No hay proyecto activo (se usa la carpeta _General). Si el usuario pide un programa, crea un proyecto.\n"
    mem = T.read_memory().strip()
    if mem:
        s += f"\n## Memoria sobre el usuario\n{mem[:6000]}\n"
    pmem = T.read_project_memory(proj).strip()
    if pmem:
        s += f"\n## Memoria del proyecto (decisiones y estado)\n{pmem[:8000]}\n"
    est = E.build(conv)
    if est:
        s += "\n" + est + "\n"
    elif proj:
        prev = E.read_project_file(proj)
        if prev:
            s += ("\n## Estado del último trabajo en este proyecto (de una conversación anterior)\n"
                  + prev[:7000] + "\n")
        else:
            plog = T.read_project_log(proj)
            if plog:
                s += f"\n## Últimas acciones en este proyecto\n{plog}\n"
    if handoff:
        s += (f"\n## ⚠ RELEVO\nLa IA anterior ({handoff}) falló o dejó de responder. Tú continúas su trabajo según el "
              "ESTADO DEL TRABAJO: sigue EXACTAMENTE donde quedó, sin repetir lo hecho ni volver a preguntar.\n")
    if conv.get("idioma") == "en":
        s += "\n## Language\nThe user's interface is in ENGLISH: reply in English unless the user writes in another language.\n"
    rg = A.reglas(900)
    if rg:
        s += "\n## " + rg + "\n"
    extra = (CONFIG.get("system_prompt") or "").strip()
    if extra:
        s += f"\n## Instrucciones personales del usuario\n{extra}\n"
    if text_tools:
        s += "\n## HERRAMIENTAS\nPara usar una herramienta escribe EXACTAMENTE este formato (puedes usar varias seguidas):\n" \
             "<tool_call>\n{\"name\": \"nombre_herramienta\", \"arguments\": {\"param\": \"valor\"}}\n</tool_call>\n" \
             "Luego DETENTE y espera: los resultados llegarán en un mensaje <tool_result>. El JSON debe ser válido " \
             "(escapa comillas y saltos de línea como \\n). No inventes resultados.\n\nHerramientas disponibles:\n"
        for t in text_tools:
            f = t["function"]
            props = f.get("parameters", {}).get("properties", {})
            req = f.get("parameters", {}).get("required", [])
            ps = ", ".join(f"{k}{'' if k in req else '?'}: {v.get('type', 'string')}"
                           + (f" ({'|'.join(v['enum'])})" if v.get("enum") else "") for k, v in props.items())
            s += f"- {f['name']}({ps}): {f.get('description', '')[:300]}\n"
    return s


# ───────────── Construcción del contexto ─────────────
def _msg_size(m):
    c = m.get("content")
    n = 0
    if isinstance(c, str):
        n += len(c)
    elif isinstance(c, list):
        for part in c:
            n += 4000 if part.get("type") == "image_url" else len(part.get("text", ""))
    for tc in m.get("tool_calls") or []:
        n += len(tc["function"].get("arguments", ""))
    return n


def _shrink_args(tc):
    tc = copy.deepcopy(tc)
    try:
        a = json.loads(tc["function"]["arguments"])
        for k in ("contenido", "codigo", "texto_nuevo", "texto_anterior"):
            if isinstance(a.get(k), str) and len(a[k]) > 600:
                a[k] = a[k][:400] + f"\n...[{len(a[k]) - 400} caracteres omitidos; ya está en el disco]"
        tc["function"]["arguments"] = json.dumps(a, ensure_ascii=False)
    except Exception:
        pass
    return tc


def to_text_mode(msgs):
    """Convierte llamadas/resultados de herramientas al formato de texto (<tool_call>/<tool_result>)."""
    out = []
    for m in msgs:
        if m["role"] == "assistant" and m.get("tool_calls"):
            calls = "\n".join("<tool_call>\n" + json.dumps({"name": tc["function"]["name"],
                              "arguments": parse_args(tc["function"]["arguments"])}, ensure_ascii=False)
                              + "\n</tool_call>" for tc in m["tool_calls"])
            out.append({"role": "assistant", "content": (m.get("content") or "") + "\n" + calls})
        elif m["role"] == "tool":
            block = f"<tool_result name=\"{m.get('name')}\">\n{m['content']}\n</tool_result>"
            if out and out[-1]["role"] == "user" and out[-1].get("_tr"):
                out[-1]["content"] += "\n" + block
            else:
                out.append({"role": "user", "content": block, "_tr": True})
        else:
            out.append(dict(m))
    for m in out:
        m.pop("_tr", None)
    merged = []  # fusiona mensajes de usuario consecutivos (algunos modelos lo exigen)
    for m in out:
        if merged and merged[-1]["role"] == m["role"] == "user" and isinstance(m["content"], str) \
                and isinstance(merged[-1]["content"], str):
            merged[-1]["content"] += "\n\n" + m["content"]
        else:
            merged.append(m)
    return merged


def apply_no_system(msgs, model_id):
    """Para modelos que no aceptan el rol 'system': lo pasa al primer mensaje del usuario."""
    if not model_override(model_id).get("no_system") or not msgs or msgs[0]["role"] != "system":
        return msgs
    sysmsg, rest = msgs[0]["content"], msgs[1:]
    if rest and rest[0]["role"] == "user" and isinstance(rest[0]["content"], str):
        rest[0] = dict(rest[0], content=sysmsg + "\n\n---\n\n" + rest[0]["content"])
        return rest
    return [{"role": "user", "content": sysmsg}, {"role": "assistant", "content": "Entendido."}] + rest


def build_messages(conv, mode, tool_defs, model_id, handoff=None, raw=False):
    limit = CONFIG["providers"].get(split_model(model_id)[0], {}).get("context_chars") or 200000
    msgs = copy.deepcopy(conv["messages"])
    n = len(msgs)
    # 1) enmascarado de observaciones: solo los 10 últimos resultados de herramientas van completos
    tool_idx = [i for i, m in enumerate(msgs) if m["role"] == "tool"]
    for i in tool_idx[:-10]:
        c = str(msgs[i].get("content", ""))
        if len(c) > 300:
            msgs[i]["content"] = c[:220].rstrip() + " …[resultado anterior resumido]"
    for i, m in enumerate(msgs):
        if i >= n - 6:
            break
        if m["role"] == "tool" and len(m.get("content", "")) > 2000:
            c = m["content"]
            m["content"] = c[:1200] + f"\n...[recortado {len(c) - 1600} caracteres]...\n" + c[-400:]
        if m.get("tool_calls"):
            m["tool_calls"] = [_shrink_args(tc) for tc in m["tool_calls"]]
    # 2) imágenes: si el modelo no ve, van como descripción del modelo visual; si ve, solo las 2 últimas
    #    (las anteriores se reemplazan por su descripción en caché, que cuesta muchos menos tokens)
    if V.lacks_vision(model_id):
        V.replace_images(msgs)
    img_idx = [i for i, m in enumerate(msgs) if isinstance(m.get("content"), list)]
    for i in img_idx[:-2]:
        V.replace_images([msgs[i]], only_cached=True)
        if isinstance(msgs[i]["content"], list):
            parts = msgs[i]["content"]
            txt = " ".join(p.get("text", "") for p in parts if p.get("type") == "text")
            msgs[i]["content"] = txt + " [imagen omitida por espacio]"
    if raw:
        for m in msgs:
            if m["role"] == "assistant" and m.get("tool_calls") and not m.get("content"):
                m["content"] = ""
        return msgs
    # 3) si aún excede, elimina turnos antiguos
    total = sum(_msg_size(m) for m in msgs)
    dropped = False
    while total > limit and len(msgs) > 4:
        j = 1
        while j < len(msgs) - 2 and msgs[j]["role"] != "user":
            j += 1
        j = max(j, 1)
        k = j + 1
        while k < len(msgs) - 2 and msgs[k]["role"] != "user":
            k += 1
        if k >= len(msgs) - 2:
            break
        total -= sum(_msg_size(m) for m in msgs[j:k])
        del msgs[j:k]
        dropped = True
    if dropped:
        msgs.insert(1, {"role": "user", "content": "[Nota del sistema: se omitieron mensajes antiguos por el límite de "
                        "contexto. El ESTADO DEL TRABAJO de las instrucciones resume lo pedido, lo hecho y el siguiente paso.]"})
        msgs.insert(2, {"role": "assistant", "content": "Entendido."})

    # 4) formato según el modo de herramientas
    if mode in ("texto", "ninguno"):
        msgs = to_text_mode(msgs)
    else:
        for m in msgs:
            if m["role"] == "assistant" and m.get("tool_calls") and not m.get("content"):
                m["content"] = ""
    sysmsg = system_prompt(conv, tool_defs if mode == "texto" else None, handoff)
    return apply_no_system([{"role": "system", "content": sysmsg}] + msgs, model_id)


def parse_args(s):
    try:
        v = json.loads(s or "{}")
        return v if isinstance(v, dict) else {}
    except Exception:
        from .providers import _loads_lenient
        v = _loads_lenient(s or "")
        return v if isinstance(v, dict) else {"_error": "argumentos JSON inválidos"}


def display_args(args):
    out = {}
    for k, v in args.items():
        out[k] = v[:20000] + "…" if isinstance(v, str) and len(v) > 20000 else v
    return out


# ───────────── Bucle principal ─────────────
PERSIST = {"file", "image", "tasks", "project", "notice"}
READ_TOOLS = {"leer_archivo", "listar_directorio", "probar_proyecto", "procesos", "diagnosticar", "probar_web",
              "buscar_en_archivos", "buscar_archivos", "mapa_codigo", "localizar_error", "captura_pantalla"}
STATE_TOOLS = {"escribir_archivo", "editar_archivo", "deshacer_cambio", "ejecutar_powershell", "ejecutar_python",
               "mover_o_copiar", "eliminar", "puntos_restauracion", "instalar_herramienta", "entorno", "crear_proyecto",
               "diagnosticar", "ejecutar_linux", "contenedor", "descargar_archivo", "cambiar_proyecto"}
BUG_RX = re.compile(r"(?i)(no funciona|no sirve|no anda|no carga|no abre|no se ve|no aparece|no hace nada|no responde|no se mueve|"
                    r"no juega|no deja|pantalla (en )?(blanco|negro)|\bfalla|\bfallo|\bbug|arregl|corrig|revis|repar|"
                    r"\b(?:da|sale|salta|aparece|hay|tira|lanza|muestra|tengo|tiene|marca|me sale|me da)\s+(?:un\s+|el\s+|este\s+|ese\s+|otro\s+)?error|"
                    r"\berror(?:es)?\s*(?::|en\s+(?:la|el)\s+consola)|de[bv][ií]as?\s+(?:de\s+)?(?:haber|aver|a\s+ver)|"
                    r"no\s+(?:es|está|esta)\s+(?:jugable|bien|funcionando|lo\s+que\s+ped)|"
                    r"mal hech|est[aá] mal|\broto\b|crash|se cierra|se traba|no compila|\bfix\b|broken|doesn'?t work|not working|"
                    r"no se puede jugar|no se juega)")
DIAG_MARK = "[DIAGNÓSTICO AUTOMÁTICO DE NOVIQ"


def _texto(content):
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return str(content or "")


def es_depuracion(conv):
    """¿El último pedido del usuario es revisar/arreglar algo que no funciona?"""
    pedidos = (conv.get("estado") or {}).get("pedidos") or []
    return bool(pedidos and BUG_RX.search(pedidos[-1].get("texto") or ""))


def diagnostico_texto(conv, emit, stop_ev, max_items=8):
    """Corre el agente de diagnóstico sobre el proyecto activo. Devuelve (reporte, n_problemas) o ("", 0)."""
    if not conv.get("project"):
        return "", 0
    ctx = T.ToolContext(conv, emit, stop_ev)
    cwd = ctx.cwd
    try:
        if not cwd.exists() or not any(x for x in cwd.iterdir() if not x.name.startswith(".")):
            return "", 0
    except OSError:
        return "", 0
    res = D.run(cwd, ctx=ctx, dinamico=True, ejecutar=False, reparar=True)
    return D.reporte(res, max_items=max_items), len(res["problemas"])


def auto_diagnostico(conv, emit, stop_ev):
    """Si el usuario dice que algo no funciona, Noviark diagnostica el proyecto ANTES de que la IA empiece
    y le entrega la lista de problemas reales (las IAs pequeñas no saben por dónde empezar)."""
    if not CONFIG.get("diagnostico_auto", True) or not conv.get("project") or not conv.get("messages"):
        return
    last = conv["messages"][-1]
    txt = _texto(last.get("content"))
    if last.get("role") != "user" or txt.startswith("[") or DIAG_MARK in txt or not BUG_RX.search(txt):
        return
    emit("status", {"text": "🩺 Diagnóstico automático del proyecto antes de empezar (errores reales, navegador de pruebas)…"})
    rep_, n = diagnostico_texto(conv, emit, stop_ev)
    if not rep_:
        return
    extra = (f"\n\n{DIAG_MARK} — lo hizo el programa antes de que empieces; es tu punto de partida. Corrige estos problemas "
             "(empezando por el 1) y vuelve a verificar con diagnosticar/probar_web]\n" + rep_)
    if isinstance(last.get("content"), list):
        last["content"] = last["content"] + [{"type": "text", "text": extra}]
    else:
        last["content"] = txt + extra
    T.append_log(conv, f"🩺 diagnóstico automático: {n} problema(s)")
    emit("notice", {"text": f"🩺 Diagnóstico automático: {n} problema(s) encontrados en el proyecto; se los paso a la IA"
                            + (" (primero: " + rep_.split("1) ", 1)[1].split(chr(10))[0][:140] + ")" if n and "1) " in rep_ else ".")})


def extra_breve(model_id):
    """Parámetros para que la próxima respuesta razone poco (tras un corte del guardián)."""
    ov = model_override(model_id)
    ex = {}
    if not ov.get("no_reasoning_effort"):
        ex["reasoning_effort"] = "low"
    pid, name = split_model(model_id)
    if pid == "nvidia" and re.search(r"glm|qwen|deepseek", name, re.I) and not ov.get("no_ctk"):
        ex["chat_template_kwargs"] = {"enable_thinking": False, "thinking": False}
    return ex or None


def msg_guardian(conv, motivo):
    accion = ("usa `diagnosticar` (o `probar_web` si es una web/juego) para ver los errores REALES y corrige el primero con "
              "editar_archivo" if es_depuracion(conv) else f"haz el siguiente paso ({E.next_step(conv)})")
    return ("[GUARDIÁN] Te detuve porque " + motivo + ". Pensar tanto no avanza el trabajo. En tu próxima respuesta:\n"
            "1. Piensa como máximo 5-10 líneas.\n"
            "2. NO escribas código dentro del razonamiento: el código va DIRECTO en escribir_archivo (si es largo, por partes con "
            "modo='agregar') o en editar_archivo.\n"
            "3. Llama AHORA a una herramienta: " + accion + ".")


def msg_supervisor(motivo, diag=""):
    return ("[SUPERVISOR] Llevas varios intentos sin avanzar (" + motivo + "). CAMBIA DE ESTRATEGIA:\n"
            "1. No repitas lo que ya falló.\n"
            "2. Mide el problema real: diagnosticar / probar_web / ejecuta el programa y lee el error completo.\n"
            "3. Lee el código afectado con leer_archivo (rango de líneas) antes de editar.\n"
            "4. Si editar_archivo falla, usa desde_linea/hasta_linea con los números reales, o despues_de_linea para insertar.\n"
            "5. Si un archivo está muy dañado o incompleto, reescríbelo COMPLETO con escribir_archivo (sobrescribir=true).\n"
            "6. Verifica al final con diagnosticar/probar_web."
            + ("\n\n" + diag if diag else ""))


def fallback_chain(conv):
    """IA elegida + respaldo configurado + (respaldo automático) los mejores modelos gratuitos disponibles.
    Los modelos marcados como NO operativos (sin clave, 404, sin crédito…) pasan al final."""
    first = conv.get("model") or CONFIG["model"]
    chain = [first]
    if CONFIG.get("fallback_enabled", True):
        for m in CONFIG.get("fallback_models") or []:
            if m and m not in chain:
                chain.append(m)
        if CONFIG.get("respaldo_auto", True) and len(chain) < 4:
            extend_chain(chain, max_add=4 - len(chain))
    ok = [m for m in chain if not S.blocked(m)]
    return ok + [m for m in chain if m not in ok]


def extend_chain(chain, max_add=3):
    """Añade al respaldo los modelos gratuitos más inteligentes que estén operativos (catalogo.ranking)."""
    try:
        from . import catalogo as K
        infos = K.all_infos()
        added = 0
        for m in K.ranking(infos, need_tools=True, n=10):
            if m not in chain and not S.blocked(m):
                chain.append(m)
                added += 1
                if added >= max_add:
                    break
        return added
    except Exception:
        return 0


def _failover_worthy(e: APIError):
    t = str(e).lower()
    if "detenido" in t:
        return False
    return e.status in (0, 401, 402, 403, 404, 408, 409, 429, 500, 502, 503, 504, 529, 599) or e.status >= 500 \
        or "no respondió" in t or "no pude conectar" in t or "falta la api key" in t


def _short(e):
    s = str(e).replace("\n", " ")
    return s[:160] + ("…" if len(s) > 160 else "")


def log_line(name, args, result):
    ok = "✗" if str(result).startswith(("ERROR", "El usuario RECHAZÓ", "Cancelado")) else "✔"
    arg = args.get("ruta") or args.get("nombre") or args.get("explicacion") or args.get("comando", "")[:80] \
        or args.get("consulta") or args.get("url") or args.get("prompt", "")[:60] or args.get("accion") or ""
    return f"{ok} {name}: {str(arg)[:120]}"


def run_agent(conv, emit_raw, stop_ev):
    from .server_state import save_conv

    def emit(kind, payload):
        emit_raw(kind, payload)
        if kind in PERSIST:
            conv["display"].append({"type": kind, **payload})
        if kind == "file":
            E.record_file(conv, payload)

    conv["en_progreso"] = True
    chain = fallback_chain(conv)
    want = conv.get("model") or CONFIG["model"]
    if chain[0] != want and S.blocked(want):
        st = S.get(want) or {}
        emit("notice", {"text": f"{S.ICONO.get(st.get('kind'), '⛔')} {want.split('::')[-1]} no está operativo: {st.get('motivo', '')} "
                                f"Trabajo con {chain[0].split('::')[-1]}. 💡 {st.get('solucion', '')}"})
    rounds, max_rounds = 0, int(CONFIG.get("fallback_rounds", 3))
    ci = 0
    model_id = chain[0]
    handoff = None

    def mode_for(mid):
        m = model_override(mid).get("tool_mode") or CONFIG.get("tool_mode", "auto")
        return "nativo" if m == "auto" else m

    mode = mode_for(model_id)
    E.record_model(conv, model_id)
    compact = C.is_compact(model_id)
    from .local import cfg_local
    max_steps = int(cfg_local().get("max_steps", 150)) if compact else int(CONFIG.get("max_steps", 40))
    changed_run = set()      # archivos de código cambiados en este turno (para las pruebas finales)
    final_fixes, last_report, stalls = 0, "", {}
    seen_sigs, loops = {}, 0
    step, retried = 0, set()
    cuts, nudges, tools_used, ejec_passes, vision_warned = 0, 0, 0, 0, False
    sup, reg = ESC.Supervisor(), ESC.Registro(conv)   # 🚀 escalador: detecta atascos y pasa el trabajo a una IA más capaz
    breve, state_ver = 0, 0                           # 🛡 guardián: respuestas con razonamiento breve tras un corte
    # ⏪ Punto de restauración automático antes de trabajar (git en la sombra dentro de .noviq, sin tocar tu .git)
    if conv.get("project"):
        try:
            from . import entornos as EN
            _cwd = T.ToolContext(conv, emit, stop_ev).cwd
            _txt = str((conv["messages"][-1] or {}).get("content", ""))[:70].replace("\n", " ") if conv["messages"] else ""
            threading.Thread(target=EN.snapshot, args=(_cwd, "antes de: " + _txt), daemon=True).start()
        except Exception:
            pass
    # 🧠 Cerebro de vanguardia: el modelo gratuito más inteligente diseña el plan antes de construir
    try:
        from . import cerebro as CB
        if CB.plan(conv, T.ToolContext(conv, emit, stop_ev).cwd, emit, stop_ev, model_id):
            save_conv(conv)
            E.save_file(conv)
    except Exception as ex:  # el plan es una ayuda: si falla, el trabajo sigue normal
        emit("status", {"text": f"(plan de vanguardia omitido: {type(ex).__name__})"})
    # 🩺 Diagnóstico automático: si el usuario dice que algo no funciona, primero se miden los errores reales
    try:
        auto_diagnostico(conv, emit, stop_ev)
        save_conv(conv)
    except Exception as ex:
        emit("status", {"text": f"(diagnóstico automático omitido: {type(ex).__name__}: {str(ex)[:80]})"})
    while step < max_steps:
        step += 1
        # ── 🚀 Escalador: la IA se atascó → pasa el trabajo a la IA más capaz habilitada (con cuota) ──
        if sup.atascado() and not stop_ev.is_set():
            motivo = sup.explicacion()
            reg.marcar(model_id)
            nuevo, info_ = ESC.mejor(model_id, excluir=reg.excluidos()) if sup.escalados < sup.max else (None, "ya se escaló varias veces")
            diag = ""
            if conv.get("project") and es_depuracion(conv):
                try:
                    diag, _n = diagnostico_texto(conv, emit, stop_ev, max_items=6)
                except Exception:
                    diag = ""
            if nuevo:
                sup.escalados += 1
                prev = model_id
                model_id = nuevo
                chain = [nuevo] + [m for m in chain if m != nuevo]
                ci = 0
                mode = mode_for(model_id)
                compact = C.is_compact(model_id)
                handoff = prev
                breve = 0
                emit_raw("reset_segment", {})
                emit("notice", {"text": f"🚀 Escalado: {prev.split('::')[-1]} se atascó ({motivo[:180]}). Paso el trabajo a "
                                        f"{nuevo.replace('::', ' · ')}, la IA más capaz que tienes habilitada con cuota; "
                                        "continúa con todo lo hecho hasta ahora."})
                emit_raw("model_switch", {"model": nuevo})
                T.append_log(conv, f"🚀 escalado de IA: {prev} → {nuevo} ({motivo[:100]})")
                E.record_model(conv, nuevo)
                conv["messages"].append({"role": "user", "content": E.handoff_message(conv, prev, nuevo, "se atascó: " + motivo[:200])
                                         + "\n\nEres una IA más capaz que toma el relevo porque la anterior no avanzaba. NO repitas lo "
                                         "que ya falló: mide el problema real (diagnosticar / probar_web / ejecutar), encuentra la causa "
                                         "raíz, corrige lo mínimo y verifica." + ("\n\n" + diag if diag else "")})
            else:
                sup.intervenciones += 1
                if sup.intervenciones > 2:
                    conv["en_progreso"] = True
                    E.save_file(conv)
                    emit("notice", {"text": f"🧭 La IA sigue atascada ({motivo[:160]}) y {info_}. La detuve para no gastar recursos. "
                                            "💡 Activa una IA más capaz en 🎁 IA gratis (o elige otra en la lista) y pulsa «▶ Continuar el trabajo»."})
                    save_conv(conv)
                    return
                breve = 2
                emit("notice", {"text": f"🧭 Supervisor: la IA no avanza ({motivo[:160]}); {info_}. Le doy un diagnóstico y una estrategia nueva."})
                conv["messages"].append({"role": "user", "content": msg_supervisor(motivo, diag)})
            sup.reiniciar()
            save_conv(conv)
        tool_defs = (T.BUILTIN + MANAGER.tool_defs()) if mode != "ninguno" else []
        valid = {t["function"]["name"] for t in tool_defs} | set(T.FUNCS)
        if V.lacks_vision(model_id) and any(isinstance(m.get("content"), list) for m in conv["messages"]):
            errs = V.ensure_descriptions(conv, emit_raw)
            if errs and not vision_warned:
                vision_warned = True
                emit("notice", {"text": "No pude analizar una imagen con ningún modelo visual (" + errs[0][:150]
                                        + "). Activa un proveedor con visión (Gemini, NVIDIA GLM-5.3, etc.)."})
        if compact:
            msgs, tools_arg, cinfo = C.build(conv, mode, tool_defs, model_id, T.ToolContext(conv, emit, stop_ev).cwd, handoff)
            msgs = apply_no_system(msgs, model_id)
        else:
            msgs = build_messages(conv, mode, tool_defs, model_id, handoff)
            tools_arg = tool_defs if mode == "nativo" else None
            cinfo = {"usado": C.tok(msgs) + (C.tok(tools_arg) if tools_arg else 0), "limite": C.budget(model_id), "compacto": False}
        emit_raw("context", cinfo)
        guard = G.Guardian(factor=(0.6 if compact else 1.0) * (0.8 if tools_used else 1.0))
        extra_used = extra_breve(model_id) if breve > 0 else None
        try:
            raw, reasoning, calls, finish = stream_chat(
                model_id, msgs, tools_arg, emit, stop_ev, extra=extra_used,
                max_attempts=3 if (ci < len(chain) - 1 or rounds < max_rounds) else 5, guard=guard)
            if breve > 0:
                breve -= 1
            if not calls and mode != "ninguno" and any(x in raw for x in ("<tool_call>", "[TOOL_REQUEST]", '"name"', "<function=")):
                calls = parse_text_tool_calls(raw, valid, allow_fenced=(mode == "texto"))
            if not calls and mode != "ninguno" and finish != "guardian" and reasoning and not strip_tool_text(raw).strip() \
                    and any(x in reasoning for x in ("<tool_call>", "<function=", "[TOOL_REQUEST]")):
                # algunos modelos locales escriben la llamada a la herramienta DENTRO del razonamiento
                calls = parse_text_tool_calls(reasoning, valid, allow_fenced=False)
            if not calls and not strip_tool_text(raw).strip() and not reasoning.strip() and not stop_ev.is_set():
                raise APIError("respuesta vacía", 599)
        except APIError as e:
            t = str(e).lower()
            key = (model_id, )
            if e.kind in S.BLOQUEA or e.kind in ("limite", "apagado"):
                # modelo no operativo (clave, 404, crédito, memoria…): no es culpa de las herramientas → pasa al respaldo
                if ci >= len(chain) - 1 and CONFIG.get("fallback_enabled", True):
                    extend_chain(chain, max_add=3)
                if ci < len(chain) - 1:
                    prev = model_id
                    ci += 1
                    while ci < len(chain) - 1 and S.blocked(chain[ci]):
                        ci += 1
                    model_id = chain[ci]
                    mode = mode_for(model_id)
                    compact = C.is_compact(model_id)
                    handoff = prev
                    emit_raw("reset_segment", {})
                    emit("notice", {"text": str(e).split("\n\nDetalle")[0] + f"\n➡ Continúa {model_id.replace('::', ' · ')} "
                                                                             "con todo lo hecho hasta ahora."})
                    emit_raw("model_switch", {"model": model_id})
                    T.append_log(conv, f"⚠ relevo de IA: {prev} → {model_id} ({e.kind})")
                    E.record_model(conv, model_id)
                    if any(m.get("role") == "assistant" for m in conv["messages"]):
                        last = conv["messages"][-1] if conv["messages"] else {}
                        if not (last.get("role") == "user" and str(last.get("content", "")).startswith("[RELEVO")):
                            conv["messages"].append({"role": "user", "content": E.handoff_message(conv, prev, model_id, e.kind)})
                    save_conv(conv)
                    step -= 1
                    continue
                E.save_file(conv)
                raise APIError(str(e) + "\n\n💾 El trabajo quedó guardado. 💡 Activa más IAs en 🎁 IA gratis (o «🧠 Usar los más "
                                        "inteligentes gratis» en la lista de modelos) para que Noviark cambie solo a otra que funcione.",
                               e.status, e.kind)
            if mode == "nativo" and e.status in (400, 404, 422, 500) and any(w in t for w in ("tool", "function")) \
                    and "not found for account" not in t and not e.kind and ("tools",) + key not in retried:
                retried.add(("tools",) + key)
                set_override(model_id, "tool_mode", "texto")
                emit("notice", {"text": f"{model_id.split('::')[-1]} no acepta herramientas nativas: uso el modo por texto (se recordará)."})
                mode = "texto"
                step -= 1
                continue
            if "system" in t and ("role" in t or "not supported" in t) and ("system",) + key not in retried:
                retried.add(("system",) + key)
                set_override(model_id, "no_system", True)
                step -= 1
                continue
            if e.status in (400, 422) and any(w in t for w in ("max_tokens", "max_completion_tokens", "maximum context",
                                                               "too large", "context length", "context_length")) \
                    and ("maxtok",) + key not in retried:
                retried.add(("maxtok",) + key)
                set_override(model_id, "max_tokens", 4096)
                CONFIG_MAX = int(CONFIG.get("max_tokens", 16384))
                if CONFIG_MAX > 8192:
                    emit("notice", {"text": "El modelo no acepta tantos tokens de respuesta; ajusto el límite automáticamente."})
                step -= 1
                continue
            if extra_used and e.status in (400, 422) and ("breve",) + key not in retried:
                # el proveedor no acepta los parámetros de «razonamiento breve»: se recuerda y se reintenta sin ellos
                retried.add(("breve",) + key)
                if "chat_template_kwargs" in extra_used:
                    set_override(model_id, "no_ctk", True)
                if "reasoning_effort" in extra_used and ("reasoning" in t or "chat_template_kwargs" not in extra_used):
                    set_override(model_id, "no_reasoning_effort", True)
                step -= 1
                continue
            if "reasoning_effort" in t and ("reasoning",) + key not in retried:
                retried.add(("reasoning",) + key)
                set_override(model_id, "no_reasoning_effort", True)
                step -= 1
                continue
            if stop_ev.is_set():
                emit("notice", {"text": "Detenido por el usuario."})
                return
            img_err = any(w in t for w in ("image", "vision", "multimodal", "image_url")) and e.status in (400, 422)
            if img_err and not model_override(model_id).get("no_vision") and ("vision",) + key not in retried:
                # el modelo no ve imágenes: un modelo visual las analiza y le pasa un resumen
                retried.add(("vision",) + key)
                set_override(model_id, "no_vision", True)
                emit("notice", {"text": f"{model_id.split('::')[-1]} no puede ver imágenes: otro modelo con visión "
                                        "las analiza y le envía un resumen detallado."})
                step -= 1
                continue
            worthy = img_err or _failover_worthy(e)
            retryable = e.status not in (401, 402, 403, 404) and "falta la api key" not in t
            if worthy and (ci < len(chain) - 1 or (not img_err and retryable and rounds < max_rounds)):
                prev = model_id
                if ci < len(chain) - 1:
                    ci += 1
                else:
                    # ninguna IA respondió: espera y vuelve a intentar la cadena completa (no se abandona el trabajo)
                    rounds += 1
                    wait = 20 * rounds
                    emit_raw("reset_segment", {})
                    emit("notice", {"text": f"⚠ Ninguna IA respondió. Reintento la cadena en {wait} s "
                                            f"(intento {rounds}/{max_rounds}); el trabajo está guardado."})
                    for _ in range(wait * 2):
                        if stop_ev.is_set():
                            emit("notice", {"text": "Detenido por el usuario."})
                            return
                        time.sleep(0.5)
                    ci = 0
                model_id = chain[ci]
                mode = mode_for(model_id)
                compact = C.is_compact(model_id)
                emit_raw("reset_segment", {})
                if model_id != prev:
                    handoff = prev
                    emit("notice", {"text": f"⚠ {prev.replace('::', ' · ')} falló ({_short(e)}). Continúa "
                                            f"{model_id.replace('::', ' · ')} con todo lo hecho hasta ahora."})
                    emit_raw("model_switch", {"model": model_id})
                    T.append_log(conv, f"⚠ relevo de IA: {prev} → {model_id} ({_short(e)[:80]})")
                    E.record_model(conv, model_id)
                    last = conv["messages"][-1] if conv["messages"] else {}
                    if not (last.get("role") == "user" and str(last.get("content", "")).startswith("[RELEVO")):
                        conv["messages"].append({"role": "user", "content": E.handoff_message(conv, prev, model_id, _short(e)[:120])})
                save_conv(conv)
                E.save_file(conv)
                step -= 1
                continue
            if img_err:
                raise APIError("Este modelo no acepta imágenes. Elige un modelo con visión (ej. z-ai/glm-5.3-flash, "
                               "Gemini, llama-4-maverick) o envía el mensaje sin imagen.\n\nDetalle: " + str(e)[:400])
            E.save_file(conv)
            if len(chain) == 1 and _failover_worthy(e):
                raise APIError(str(e) + "\n\n💾 El trabajo quedó guardado: pulsa «▶ Continuar el trabajo» para seguir donde quedó."
                               "\n💡 Configura IAs de respaldo en ⚙ Ajustes → Respaldo para que otra IA continúe automáticamente.", e.status)
            if _failover_worthy(e):
                raise APIError(str(e) + "\n\n💾 El trabajo quedó guardado: pulsa «▶ Continuar el trabajo» para seguir donde quedó.", e.status)
            raise

        text = strip_tool_text(raw)
        if stop_ev.is_set():
            if text:
                conv["messages"].append({"role": "assistant", "content": text})
                conv["display"].append({"type": "assistant", "text": text, "reasoning": reasoning, "model": model_id})
            emit("notice", {"text": "Detenido por el usuario."})
            return

        # ── 🛡 Guardián: cortó un razonamiento eterno o un bucle de texto → se le pide actuar ya, con razonamiento breve ──
        if finish == "guardian" and not calls:
            quien = model_id.split("::")[-1]
            sup.registrar("guardian", f"{quien} {guard.tripped}")
            conv["display"].append({"type": "assistant", "text": text, "reasoning": reasoning, "model": model_id})
            if reasoning and not conv.get("tasks"):
                E.record_plan_text(conv, G.resumen_razonamiento(reasoning, 3000))
            res_r = G.resumen_razonamiento(reasoning)
            body = (text.strip()[:1500] + "\n\n") if text.strip() else ""
            if res_r:
                body += "(Mi razonamiento se cortó por ser demasiado largo. Lo último que pensé:)\n" + res_r
            conv["messages"].append({"role": "assistant", "content": body.strip() or "(razonamiento cortado)"})
            conv["messages"].append({"role": "user", "content": msg_guardian(conv, guard.tripped)})
            breve = 2
            emit_raw("assistant_break", {})
            emit("notice", {"text": f"🛡 Guardián: {quien} {guard.tripped}. Lo detuve y le pedí actuar ya, con razonamiento breve."})
            T.append_log(conv, f"🛡 guardián: {quien} {guard.tripped}")
            save_conv(conv)
            continue

        # ── Respuesta cortada por límite de tokens: continuar solo, sin perder el progreso ──
        broken = [c for c in calls if "_error" in parse_args(c["function"]["arguments"])]
        if finish == "length" and (not calls or broken) and cuts < 4:
            cuts += 1
            cur = int(model_override(model_id).get("max_tokens") or CONFIG.get("max_tokens", 16384))
            new_max = min(cur * 2, 65536)
            set_override(model_id, "max_tokens", new_max)
            if reasoning and not text and not model_override(model_id).get("no_reasoning_effort"):
                set_override(model_id, "reasoning_effort", "low")
            if reasoning and not text and not conv.get("tasks"):
                E.record_plan_text(conv, reasoning)
            conv["display"].append({"type": "assistant", "text": text, "reasoning": reasoning, "model": model_id})
            if broken:
                names = ", ".join(sorted({c["function"]["name"] for c in broken}))
                conv["messages"].append({"role": "assistant", "content": text or "(llamada a herramienta cortada)"})
                conv["messages"].append({"role": "user", "content":
                    f"[Sistema] Tu llamada a {names} se cortó porque el contenido era demasiado largo. "
                    "Escribe los archivos grandes POR PARTES: escribir_archivo con la primera parte y luego "
                    "escribir_archivo con modo='agregar' para el resto (máx. ~300 líneas por llamada). Continúa ahora."})
            elif text:
                conv["messages"].append({"role": "assistant", "content": text})
                conv["messages"].append({"role": "user", "content":
                    "[Sistema] Tu respuesta se cortó por longitud. Continúa EXACTAMENTE donde te quedaste, sin repetir."})
            else:
                conv["messages"].append({"role": "assistant", "content":
                    "Mi plan (resumen de mi razonamiento):\n" + reasoning[-3500:]})
                conv["messages"].append({"role": "user", "content":
                    "[Sistema] Ya tienes el plan. NO vuelvas a planificar ni a razonar largo: EJECÚTALO AHORA "
                    "llamando a las herramientas (una o varias), paso por paso."})
            emit_raw("assistant_break", {})
            emit("notice", {"text": f"La respuesta se cortó por el límite de tokens. Continúo automáticamente "
                                    f"(límite subido a {new_max}{', razonamiento breve' if reasoning and not text else ''})."})
            save_conv(conv)
            continue

        msg = {"role": "assistant", "content": text}
        if calls:
            msg["tool_calls"] = calls
        conv["messages"].append(msg)
        conv["display"].append({"type": "assistant", "text": text, "reasoning": reasoning, "model": model_id})
        save_conv(conv)

        # ── Agente ejecutor: la IA escribió código en texto en vez de usar herramientas ──
        auto_ok = CONFIG.get("ejecutor", "auto") == "siempre" or not (mode == "nativo" and tools_used)
        if not calls and ejec_passes < 6 and auto_ok:
            synth = EJ.synthesize(text, conv, mode, T.ToolContext(conv, emit, stop_ev).cwd)
            if synth:
                ejec_passes += 1
                calls = synth
                conv["messages"][-1]["tool_calls"] = calls
                emit("notice", {"text": f"🤖 Agente ejecutor: la IA escribió código sin usar herramientas; aplico "
                                        f"{len(calls)} acción(es) por ella y le devuelvo los resultados para que continúe."})

        if not calls:
            pending = [t for t in conv.get("tasks") or [] if t.get("estado") != "completada"]
            # ── Modo compacto: el orquestador pasa al siguiente paso con la mesa limpia ──
            if compact and pending and mode != "ninguno":
                key = pending[0]["contenido"]
                stalls[key] = stalls.get(key, 0) + 1
                if stalls[key] <= 3:
                    conv["seg_start"] = len(conv["messages"])
                    msg_ = C.step_message(conv)
                    conv["messages"].append({"role": "user", "content": msg_ + (
                        " (Llevas varios intentos: haz un avance concreto con una herramienta.)" if stalls[key] > 1 else "")})
                    emit_raw("assistant_break", {})
                    emit("notice", {"text": "🧭 Orquestador: " + msg_.split("]")[0] + "] " + key[:80]})
                    save_conv(conv)
                    continue
            # ── Agente de pruebas: verificación final antes de dar el trabajo por terminado ──
            if CONFIG.get("pruebas_auto", True) and changed_run and not pending and final_fixes < 4 and mode != "ninguno":
                cwd = T.ToolContext(conv, emit, stop_ev).cwd
                pm = conv.get("permiso") or CONFIG.get("permission_mode", "preguntar")
                emit_raw("status", {"text": "🧪 Agente de pruebas revisando y ejecutando el proyecto…"})
                res = PR.run_checks(cwd, dynamic=(pm == "auto"), allow_install=(pm != "preguntar"),
                                    emit=lambda t: emit("notice", {"text": t}), web=True)
                rep_ = PR.report(res, max_errors=2 if compact else 3)
                if not res["ok"] and rep_ != last_report:
                    final_fixes += 1
                    if final_fixes >= 2:
                        sup.registrar("pruebas", "las pruebas finales siguen fallando: " + rep_.split("\n")[1][:120] if "\n" in rep_ else rep_[:120])
                    last_report = rep_
                    if compact:
                        conv["seg_start"] = len(conv["messages"])
                    conv["messages"].append({"role": "user", "content": "[PRUEBAS FINALES] " + rep_})
                    E.record_action(conv, "probar_proyecto", {"accion": "final"}, "ERROR " + rep_.split("\n")[0])
                    emit("notice", {"text": f"🧪 Agente de pruebas: {len(res['errores'])} problema(s); se los paso a la IA para corregir (intento {final_fixes}/4)."})
                    emit_raw("assistant_break", {})
                    save_conv(conv)
                    continue
                if res["ok"]:
                    emit("notice", {"text": "🧪 " + rep_})
                    changed_run.clear()
                    A.resolve_all(conv)
            # ── Anunció acciones pero no llamó herramientas: se le recuerda que actúe ──
            intent = re.search(r"\b(voy a|vamos a|procedo|proceder[ée]|a continuaci[óo]n|crear[ée]|escribir[ée]|"
                               r"ejecutar[ée]|let me|i will|i'll|now i|next,? i)\b", (text[-600:] + " " + reasoning[-400:]).lower())
            short = len(text.strip()) < 500
            if mode != "ninguno" and nudges < 3 and ((intent and short and not text.rstrip().endswith("?")) or (pending and tools_used)):
                nudges += 1
                if pending or tools_used:
                    sup.registrar("sin_herramientas", "respondió sin usar herramientas con trabajo pendiente")
                conv["messages"].append({"role": "user", "content":
                    "[Sistema] No llamaste a ninguna herramienta. Si aún hay trabajo por hacer, EJECÚTALO AHORA "
                    "llamando a las herramientas (no lo describas). Si ya terminaste todo, responde solo con el resumen final."
                    + (f" Tareas pendientes: {', '.join(t['contenido'] for t in pending[:6])}." if pending else "")
                    + f" Siguiente paso: {E.next_step(conv)}"})
                emit_raw("assistant_break", {})
                save_conv(conv)
                continue
            if finish == "length":
                emit("notice", {"text": "La respuesta se cortó por el límite de tokens varias veces. Pulsa «▶ Continuar el trabajo»."})
            conv["en_progreso"] = bool(E.pending_tasks(conv)) or finish == "length"
            E.save_file(conv)
            return
        tools_used += len(calls)

        emit_raw("assistant_break", {})
        tool_images = []
        for tc in calls:
            name = tc["function"]["name"]
            args = parse_args(tc["function"]["arguments"])
            call_id = uuid.uuid4().hex
            label = T.LABELS.get(name) or ("🔌 " + name.replace("mcp__", "").replace("__", " › "))
            if tc["id"].startswith("ejec_"):
                label = "🤖 Ejecutor · " + label
            emit_raw("tool_start", {"id": call_id, "name": name, "label": label, "args": display_args(args)})
            conv["display"].append({"type": "tool", "id": call_id, "name": name, "label": label, "args": display_args(args)})
            ctx = T.ToolContext(conv, emit, stop_ev, call_id)
            sig = name + ":" + json.dumps(args, sort_keys=True, ensure_ascii=False)[:4000] + (f"@{state_ver}" if name in READ_TOOLS else "")
            seen_sigs[sig] = seen_sigs.get(sig, 0) + 1
            repetida = seen_sigs[sig] >= 3
            if name not in valid:
                result = f"ERROR: herramienta desconocida '{name}'. Disponibles: {', '.join(sorted(valid))}"
            elif "_error" in args:
                result = "ERROR: los argumentos no son JSON válido. Reenvía la llamada con JSON correcto (escapa comillas y saltos de línea)."
            elif repetida and name not in READ_TOOLS:
                # detector de bucles: la IA repite exactamente la misma acción
                loops += 1
                sup.registrar("bucle", f"repitió {name} {seen_sigs[sig]} veces igual")
                result = (f"ERROR: ya hiciste exactamente esta acción {seen_sigs[sig] - 1} veces. No la repitas: revisa el "
                          f"ESTADO DEL TRABAJO (siguiente paso: {E.next_step(conv)}) y avanza, o termina con un resumen.")
            else:
                approved = True
                if T.needs_permission(name, args, ctx):
                    ev = threading.Event()
                    PENDING[call_id] = {"event": ev, "ok": False, "always": False}
                    rz = getattr(ctx, "riesgo", None)
                    emit_raw("confirm", {"id": call_id, "name": name, "label": label, "args": display_args(args),
                                         "riesgo": rz[0] if rz else None, "fuente_riesgo": rz[1] if rz else None})
                    t0 = time.time()
                    while not ev.wait(0.5):
                        if stop_ev.is_set() or time.time() - t0 > 1800:
                            break
                    ans = PENDING.pop(call_id, {})
                    approved = ans.get("ok", False)
                    if approved and ans.get("always"):
                        conv.setdefault("allowed_tools", []).append(name)
                if approved and name == "actualizar_tareas" and not conv.get("plan_cerebro") and not conv.get("_plan_revisado") \
                        and len(args.get("tareas") or []) >= 3 and not (conv.get("tasks") or []):
                    # primer plan de la IA principal: el usuario puede revisarlo/editarlo (se aprueba solo al acabar el tiempo)
                    conv["_plan_revisado"] = True
                    from . import cerebro as CB
                    pl = CB.review(conv, emit_raw, stop_ev, {"resumen": "", "tareas": [t.get("contenido", "") if isinstance(t, dict) else str(t)
                                                                                       for t in args.get("tareas") or []]}, model_id)
                    if pl is not None:
                        old_t = {(t.get("contenido") if isinstance(t, dict) else str(t)): t for t in args.get("tareas") or []}
                        args["tareas"] = [old_t.get(t) if isinstance(old_t.get(t), dict) else {"contenido": t, "estado": "pendiente"}
                                          for t in pl["tareas"]]
                if stop_ev.is_set():
                    result = "Cancelado: el usuario detuvo la ejecución."
                elif not approved:
                    result = "El usuario RECHAZÓ esta acción. No la repitas; propón otra alternativa o pregunta."
                else:
                    try:
                        if name.startswith("mcp__"):
                            result = MANAGER.call(name, args)
                        else:
                            result = T.FUNCS[name](args, ctx)
                    except Exception as e:
                        result = f"ERROR ejecutando {name}: {type(e).__name__}: {e}"
            if isinstance(result, dict):
                if not (name in ("probar_web", "diagnosticar") and V.lacks_vision(model_id)):
                    tool_images += result.get("images") or []  # sin visión, el reporte de texto ya dice lo importante
                result = result.get("text", "")
            result = str(result)
            if repetida and name in READ_TOOLS and not result.startswith("ERROR"):
                loops += 1
                sup.registrar("bucle", f"repitió {name} {seen_sigs[sig]} veces sin cambiar nada")
                result = (f"⚠ [Ya hiciste esta misma consulta {seen_sigs[sig] - 1} veces sin cambiar nada entre medio: NO la repitas; "
                          "usa lo que ya sabes y ACTÚA (editar/escribir/ejecutar).]\n" + result)
            es_err = E._is_error(result)
            sup.resultado(name, args, result, es_err)
            if name in STATE_TOOLS and not es_err:
                state_ver += 1
            if name not in ("actualizar_tareas", "listar_directorio", "leer_archivo", "memoria"):
                T.append_log(conv, log_line(name, args, result))
            reminder = E.record_action(conv, name, args, result)
            reminder += A.on_result(conv, name, args, result)  # agente de aprendizaje: pista si el error ya se resolvió antes
            if tc["id"].startswith("ejec_"):
                result = "[Aplicado por el agente ejecutor a partir de tu código] " + result
            emit_raw("tool_result", {"id": call_id, "name": name, "result": T.cut(result, 8000)})
            conv["display"].append({"type": "tool_result", "id": call_id, "name": name, "result": T.cut(result, 8000)})
            conv["messages"].append({"role": "tool", "tool_call_id": tc["id"], "name": name, "content": result + reminder})
            save_conv(conv)
            if stop_ev.is_set():
                break
        if tool_images:
            conv["messages"].append({"role": "user", "content": [{"type": "text", "text": "[Imágenes devueltas por las herramientas]"}]
                                     + [{"type": "image_url", "image_url": {"url": u}} for u in tool_images[:4]]})
        # ── Agente de pruebas rápido: revisa solo los archivos que se acaban de cambiar ──
        batch_changed = []
        for tc in calls:
            if tc["function"]["name"] in ("escribir_archivo", "editar_archivo", "deshacer_cambio"):
                r_ = parse_args(tc["function"]["arguments"]).get("ruta")
                if r_ and Path(r_).suffix.lower() in PR.EXTS:
                    batch_changed.append(r_)
        if batch_changed and CONFIG.get("pruebas_auto", True) and not tool_images:
            cwd = T.ToolContext(conv, emit, stop_ev).cwd
            rels = []
            for r_ in batch_changed:
                p_ = Path(r_) if Path(r_).is_absolute() else cwd / r_
                try:
                    rels.append(p_.resolve().relative_to(cwd.resolve()).as_posix())
                except (ValueError, OSError):
                    pass
            changed_run.update(rels)
            if rels:
                res = PR.run_checks(cwd, only=rels, dynamic=False, allow_install=False)
                if not res["ok"]:
                    rep_ = PR.report(res, max_errors=2)
                    rep_ += A.on_result(conv, "prueba_auto", {"ruta": rels[0]},
                                       "ERROR " + "\n".join(str(e_.get("msg", "")) for e_ in res["errores"][:2]))
                    for m_ in reversed(conv["messages"]):
                        if m_["role"] == "tool":
                            m_["content"] += "\n\n[PRUEBA AUTOMÁTICA] " + rep_
                            break
                    first = res["errores"][0]
                    emit("notice", {"text": f"🧪 Agente de pruebas: {first['archivo']}:{first['linea']} — {first['msg'][:90]}"})
                else:
                    A.on_result(conv, "prueba_auto", {"ruta": rels[0]}, "OK")
        # ── Modo compacto: al completar una tarea, la siguiente empieza con la mesa limpia ──
        if compact and any(tc["function"]["name"] == "actualizar_tareas" for tc in calls):
            done_now = sum(t.get("estado") == "completada" for t in conv.get("tasks") or [])
            if done_now > conv.get("_done_prev", 0) and E.pending_tasks(conv):
                conv["seg_start"] = len(conv["messages"])
                conv["messages"].append({"role": "user", "content": C.step_message(conv)})
            conv["_done_prev"] = done_now
        save_conv(conv)
        E.save_file(conv)
        if loops >= 6:
            conv["en_progreso"] = True
            emit("notice", {"text": "🔁 La IA está repitiendo las mismas acciones sin avanzar; la detuve para no gastar recursos. "
                                    "Revisa el 📋 Estado y pulsa «▶ Continuar el trabajo» o prueba otro modelo."})
            return
        if stop_ev.is_set():
            emit("notice", {"text": "Detenido por el usuario."})
            return
    conv["en_progreso"] = True
    E.save_file(conv)
    emit("notice", {"text": f"Se alcanzó el máximo de {max_steps} pasos seguidos. Pulsa «▶ Continuar el trabajo» para seguir."})
