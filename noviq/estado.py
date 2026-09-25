# -*- coding: utf-8 -*-
"""ESTADO DEL TRABAJO: resumen estructurado y automático de cada conversación.

Lo mantiene el PROGRAMA (no depende de que la IA se acuerde): qué pidió el usuario, el plan,
lo ya hecho, los archivos creados, los errores sin resolver y el siguiente paso.
Se entrega a cualquier IA que continúe el trabajo (relevo, contexto recortado, "continúa",
reinicio del programa o una conversación nueva en el mismo proyecto).
También se guarda en <proyecto>/.noviq/ESTADO.md para que lo lea cualquier persona o IA.
"""
import re
from datetime import datetime

from .config import meta_dir, project_path, projects_root

READONLY = {"leer_archivo", "listar_directorio", "buscar_archivos", "buscar_en_archivos", "buscar_en_internet",
            "leer_pagina_web", "procesos", "memoria", "actualizar_tareas", "captura_pantalla", "probar_web", "mapa_codigo"}
ICON = {"completada": "✔", "en_progreso": "▶", "pendiente": "○"}


def _st(conv):
    st = conv.setdefault("estado", {})
    for k, v in (("pedidos", []), ("archivos", {}), ("acciones", []), ("errores", []), ("plan_texto", ""),
                 ("modelos", []), ("desde_tareas", 0)):
        st.setdefault(k, v)
    return st


def _is_error(result):
    r = str(result)
    return r.startswith(("ERROR", "El usuario RECHAZÓ", "Cancelado", "TIEMPO AGOTADO")) or \
        bool(re.match(r"Código de salida: [1-9]", r))


def record_user(conv, text):
    t = (text or "").strip()
    if t and not re.fullmatch(r"(?i)\W*(contin[uú]a(r)?|sigue|seguir|dale|ok|listo|si|sí)\W*", t):
        _st(conv)["pedidos"].append({"t": datetime.now().strftime("%H:%M"), "texto": t[:1500]})
        _st(conv)["pedidos"] = _st(conv)["pedidos"][-12:]


def record_plan_text(conv, text):
    if text and text.strip():
        _st(conv)["plan_texto"] = text.strip()[-3000:]


def record_model(conv, model_id):
    m = _st(conv)["modelos"]
    if not m or m[-1] != model_id:
        m.append(model_id)
        del m[:-8]


def record_file(conv, info):
    path = info.get("path")
    if not path:
        return
    st = _st(conv)
    root = _cwd(conv)
    rel = path
    try:
        from pathlib import Path
        rel = str(Path(path).resolve().relative_to(root.resolve())).replace("\\", "/")
    except Exception:
        pass
    prev = st["archivos"].get(rel)
    st["archivos"][rel] = info.get("action") or ("modificado" if prev else "creado")


def record_action(conv, name, args, result):
    """Registra la acción y devuelve un recordatorio (o "") para añadir al resultado de la herramienta."""
    st = _st(conv)
    arg = args.get("ruta") or args.get("nombre") or args.get("explicacion") or (args.get("comando") or "")[:100] \
        or args.get("consulta") or args.get("url") or (args.get("prompt") or "")[:80] or args.get("accion") or ""
    err = _is_error(result)
    if name not in READONLY or err:
        line = f"{'✗' if err else '✔'} {name}: {str(arg)[:140]}"
        if err:
            line += f" → {str(result).splitlines()[0][:160]}"
        st["acciones"].append(line)
        st["acciones"] = st["acciones"][-60:]
    # errores sin resolver: se limpian cuando la misma herramienta sobre el mismo objetivo funciona
    key = f"{name}:{str(arg)[:80]}"
    st["errores"] = [e for e in st["errores"] if e["k"] != key]
    if err:
        st["errores"].append({"k": key, "txt": f"{name} ({str(arg)[:80]}): {str(result)[:400]}"})
        st["errores"] = st["errores"][-6:]
    # recordatorio de mantener el plan al día
    if name == "actualizar_tareas":
        st["desde_tareas"] = 0
        return ""
    if name in READONLY:
        return ""
    st["desde_tareas"] += 1
    tasks = conv.get("tasks") or []
    if not tasks and st["desde_tareas"] == 3:
        return "\n\n[Recordatorio del sistema: registra el plan completo con actualizar_tareas para que el trabajo pueda continuarse si algo falla.]"
    if tasks and st["desde_tareas"] >= 6:
        st["desde_tareas"] = 0
        return "\n\n[Recordatorio del sistema: actualiza la lista de tareas (actualizar_tareas) marcando lo completado y lo que está en progreso.]"
    return ""


def _cwd(conv):
    from pathlib import Path
    pr = conv.get("project")
    if pr and project_path(pr).exists():
        return project_path(pr)
    return projects_root() / "_General"


def next_step(conv):
    tasks = conv.get("tasks") or []
    for t in tasks:
        if t.get("estado") == "en_progreso":
            return f"Terminar la tarea en progreso: «{t['contenido']}»"
    for t in tasks:
        if t.get("estado") == "pendiente":
            return f"Empezar la siguiente tarea pendiente: «{t['contenido']}»"
    st = _st(conv)
    if st["errores"]:
        return ("Resolver el último error sin resolver (ver «Errores sin resolver» arriba) y seguir con el pedido; si no está "
                "claro cuál es el problema real, usa diagnosticar.")
    if tasks:
        return ("Todas las tareas están completadas: VERIFICA el resultado final con una herramienta (diagnosticar / probar_web / "
                "ejecutar el programa) y entrega el resumen al usuario.")
    if st["plan_texto"]:
        return "Registrar el plan con actualizar_tareas y ejecutarlo paso a paso con las herramientas."
    return "Continuar con el pedido del usuario usando las herramientas."


def pending_tasks(conv):
    return [t for t in conv.get("tasks") or [] if t.get("estado") != "completada"]


def _backfill(conv):
    """Para conversaciones antiguas: recupera el pedido y el plan desde el historial."""
    st = _st(conv)
    if not st["pedidos"]:
        for m in conv.get("messages", []):
            c = m.get("content")
            if isinstance(c, list):
                c = " ".join(p.get("text", "") for p in c if p.get("type") == "text")
            if m.get("role") == "user" and isinstance(c, str) and c.strip() and not c.startswith("["):
                st["pedidos"].append({"t": "", "texto": c.strip()[:1500]})
                break
    if not st["plan_texto"] and not conv.get("tasks"):
        for d in reversed(conv.get("display", [])):
            if d.get("type") == "assistant" and (d.get("reasoning") or "").strip():
                st["plan_texto"] = d["reasoning"].strip()[-3000:]
                break


def build(conv, max_actions=35):
    _backfill(conv)
    st = _st(conv)
    if not st["pedidos"] and not st["acciones"] and not conv.get("tasks") and not st["plan_texto"]:
        return ""
    out = ["## 📋 ESTADO DEL TRABAJO (lo mantiene el programa automáticamente; es la fuente de verdad)"]
    if st["pedidos"]:
        out.append("\n### Lo que pidió el usuario")
        first = st["pedidos"][0]["texto"]
        out.append(f"- Pedido principal: {first}")
        for p in st["pedidos"][1:][-6:]:
            out.append(f"- Después ({p['t']}): {p['texto'][:600]}")
    if conv.get("project"):
        out.append(f"\n### Proyecto\n- {conv['project']} → {_cwd(conv)}")
    tasks = conv.get("tasks") or []
    if tasks:
        done = sum(t.get("estado") == "completada" for t in tasks)
        out.append(f"\n### Plan ({done}/{len(tasks)} completadas)")
        out += [f"{ICON.get(t.get('estado'), '○')} {t.get('contenido')}" for t in tasks]
    elif st["plan_texto"]:
        out.append("\n### Plan propuesto (aún no registrado como tareas)\n" + st["plan_texto"][-2000:])
    if st["acciones"]:
        out.append(f"\n### Hecho hasta ahora (últimas {min(len(st['acciones']), max_actions)} acciones)")
        out += st["acciones"][-max_actions:]
    if st["archivos"]:
        out.append("\n### Archivos creados/modificados (YA EXISTEN, no los vuelvas a crear salvo para corregirlos)")
        out += [f"- {k} ({v})" for k, v in list(st["archivos"].items())[-60:]]
    if st["errores"]:
        out.append("\n### Errores sin resolver")
        out += [f"- {e['txt']}" for e in st["errores"]]
    if len(st["modelos"]) > 1:
        out.append("\n### IAs que han trabajado en esto\n- " + " → ".join(st["modelos"]))
    out.append(f"\n### ▶ SIGUIENTE PASO\n{next_step(conv)}")
    return "\n".join(out)


def save_file(conv):
    """Guarda ESTADO.md en la carpeta del proyecto (para relevos y conversaciones futuras)."""
    if not conv.get("project"):
        return
    try:
        d = meta_dir(conv["project"])
        if not d.parent.exists():
            return
        d.mkdir(exist_ok=True)
        txt = build(conv)
        if txt:
            head = f"<!-- actualizado {datetime.now():%Y-%m-%d %H:%M} · conversación: {conv.get('title', '')} -->\n"
            (d / "ESTADO.md").write_text(head + txt + "\n", encoding="utf-8")
    except OSError:
        pass


def read_project_file(project):
    if not project:
        return ""
    f = meta_dir(project, create=False) / "ESTADO.md"
    return f.read_text(encoding="utf-8") if f.exists() else ""


def handoff_message(conv, prev, new, reason=""):
    verbo = "no avanzaba" if str(reason).startswith("se atascó") else "dejó de responder"
    return (f"[RELEVO DE IA] La IA anterior ({prev}) {verbo}{(' (' + reason + ')') if reason else ''}. "
            f"Tú ({new}) continúas EL MISMO trabajo: NO empieces de cero, NO vuelvas a planificar lo que ya está planificado "
            "y NO repitas lo que ya está hecho.\n\n" + build(conv) +
            "\n\nQué hacer ahora:\n1. Si hace falta, verifica rápido lo existente (listar_directorio / leer_archivo).\n"
            "2. Si la lista de tareas no refleja lo ya hecho, corrígela con actualizar_tareas.\n"
            "3. Continúa INMEDIATAMENTE con el SIGUIENTE PASO usando las herramientas.")


def continue_message(conv):
    est = build(conv) or read_project_file(conv.get("project"))
    return ("[CONTINUAR] El usuario pide continuar el trabajo exactamente donde quedó (sin empezar de cero ni repetir).\n\n"
            + (est or "(no hay estado previo registrado; revisa el historial)")
            + "\n\nContinúa AHORA con el siguiente paso usando las herramientas.")
