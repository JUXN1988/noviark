# -*- coding: utf-8 -*-
"""
Noviark 4.0 — agente de IA de escritorio para modelos de NVIDIA (build.nvidia.com), Gemini, OpenAI,
Ollama y LM Studio, con herramientas estilo Claude: proyectos, archivos, PowerShell, Python,
internet, imágenes, capturas, tareas, memoria y servidores MCP.

Uso:  python app.py        → se abre en el navegador (http://127.0.0.1:7860)
"""
import json
from html import escape as html_escape
import os
import queue
import re
import secrets
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_file, stream_with_context

from noviq import tools as T
from noviq.agent import PENDING, run_agent
from noviq.config import BASE_DIR, CONFIG, IS_WINDOWS, MEMORY_FILE, general_dir, meta_file, project_path, projects_root, save_config
from noviq import estado as E
from noviq import vault
from noviq.mcp import MANAGER
from noviq.providers import APIError, list_models
from noviq.server_state import conv_path, list_convs, load_conv, new_conv, save_conv

PORT = int(os.environ.get("NVIDIA_CHAT_PORT", "7860"))
TOKEN = secrets.token_urlsafe(24)
STATIC = BASE_DIR / "static"
app = Flask(__name__, static_folder=str(STATIC), static_url_path="/static")
app.json.sort_keys = False  # conserva el orden de los proveedores
STOP = {}
RUNNING = set()
JOBS = {}  # conversación → trabajo en curso (eventos para reengancharse)


# ───────────── Seguridad: solo esta PC y solo esta página ─────────────
@app.before_request
def guard():
    host = (request.host or "").split(":")[0]
    if host not in ("127.0.0.1", "localhost"):
        abort(403)
    if request.path.startswith("/api/") or request.path == "/f":
        tok = request.headers.get("X-Token") or request.args.get("t")
        if tok != TOKEN:
            abort(403)


@app.get("/")
def index():
    html = (STATIC / "index.html").read_text(encoding="utf-8").replace("__TOKEN__", TOKEN)
    return Response(html, mimetype="text/html")


def J():
    return request.get_json(force=True, silent=True) or {}


# ───────────── Configuración ─────────────
def public_config():
    c = json.loads(json.dumps(CONFIG))
    for pid, p in c["providers"].items():
        keys = vault.get_keys(pid)
        p["api_keys"] = [vault.mask(k) for k in keys]
        p["has_key"] = bool(keys)
    c["vault"] = "Cifrada con DPAPI de Windows" if IS_WINDOWS else "Protegida con permisos de archivo"
    c["projects_root"] = str(projects_root())
    c["os"] = "Windows" if IS_WINDOWS else sys.platform
    return c


@app.get("/api/config")
def get_config():
    return jsonify(public_config())


@app.post("/api/config")
def set_config():
    d = J()
    for k, v in d.items():
        if k == "providers":
            for pid, pv in v.items():
                cur = CONFIG["providers"].setdefault(pid, {})
                for kk, vv in pv.items():
                    if kk == "api_keys":
                        before = vault.get_keys(pid)
                        pool = {}
                        for k in before:  # cada línea enmascarada recupera su clave real (aunque dos máscaras coincidan)
                            pool.setdefault(vault.mask(k), []).append(k)
                        nuevas = []
                        for x in vv:
                            x = (x or "").strip()
                            if not x:
                                continue
                            nuevas.append(pool[x].pop(0) if pool.get(x) else x)
                        vault.set_keys(pid, list(dict.fromkeys(nuevas)))
                        if vault.get_keys(pid) != before:  # claves nuevas: se vuelve a probar qué modelos funcionan
                            from noviq import salud as S, verificador
                            S.reset_proveedor(pid)
                            verificador.pedir(pid, forzar=True)
                    elif kk != "has_key":
                        cur[kk] = vv
        elif k in CONFIG and k not in ("model_overrides",):
            CONFIG[k] = v
    save_config()
    return jsonify(public_config())


@app.post("/api/reset_model_overrides")
def reset_overrides():
    CONFIG["model_overrides"] = {}
    save_config()
    return jsonify({"ok": True})


@app.get("/api/models")
def models():
    refresh = request.args.get("refresh") == "1"
    res = []
    threads = []
    out = {}

    def one(pid):
        out[pid] = list_models(pid, refresh)

    for pid, pc in CONFIG["providers"].items():
        if not pc.get("enabled"):
            out[pid] = {"id": pid, "name": pc.get("name", pid), "ok": False, "models": [], "error": "desactivado"}
            continue
        th = threading.Thread(target=one, args=(pid,))
        th.start()
        threads.append(th)
    for th in threads:
        th.join(25)
    for pid in CONFIG["providers"]:
        r = out.get(pid) or {"id": pid, "name": pid, "ok": False, "models": [], "error": "tiempo agotado"}
        res.append({k: r.get(k) for k in ("id", "name", "ok", "models", "error", "kind")})
    return jsonify(res)


# ───────────── Proyectos ─────────────
@app.get("/api/projects")
def projects():
    ps = T.list_projects()
    convs_ = list_convs()
    for p in ps:
        cs = [c for c in convs_ if c.get("project") == p["name"]]
        p["conversaciones"] = len(cs)
        p["trabajando"] = sum(1 for c in cs if c["id"] in RUNNING)
        if cs:
            p["actividad"] = max(p.get("actividad", 0), cs[0]["updated"])
            p["ultima_conv"] = cs[0]["id"]
    ps.sort(key=lambda x: -x.get("actividad", 0))
    return jsonify({"root": str(projects_root()), "projects": ps, "tipos": list(T.TIPOS)})


@app.post("/api/projects")
def create_project():
    d = J()
    p, log = T.create_project(d.get("nombre"), d.get("tipo", "general"), d.get("descripcion", ""), d.get("instrucciones", ""))
    return jsonify({"ok": True, "name": p.name, "path": str(p), "log": log})


@app.post("/api/projects/<name>")
def update_project(name):
    p = project_path(name)
    if not p.exists():
        abort(404)
    meta = T.project_info(name)
    meta.update({k: v for k, v in J().items() if k in ("descripcion", "instrucciones", "tipo", "modelo")})
    for k in ("name", "path", "externo", "existe", "actividad", "conversaciones", "ultima_conv", "trabajando"):
        meta.pop(k, None)
    (meta_file(name)).write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return jsonify({"ok": True})


# ───────────── Conversaciones ─────────────
@app.get("/api/conversations")
def convs():
    out = list_convs()
    for c in out:
        c["running"] = c["id"] in RUNNING
    return jsonify(out)


@app.get("/api/conversations/<cid>")
def get_conv(cid):
    jb = JOBS.get(cid)
    if jb and not jb["done"]:
        c = jb["conv"]  # sigue trabajando: se devuelve lo previo al turno actual y el cliente reproduce los eventos
        out = {k: c.get(k) for k in ("id", "title", "project", "model", "tasks", "en_progreso")}
        out["display"] = c["display"][:jb["display_start"]]
        return jsonify(out | {"running": True})
    c = load_conv(cid)
    if not c:
        abort(404)
    return jsonify({k: c.get(k) for k in ("id", "title", "display", "project", "model", "tasks", "en_progreso")} |
                   {"running": cid in RUNNING})


@app.get("/api/conversations/<cid>/estado")
def conv_estado(cid):
    c = load_conv(cid)
    if not c:
        abort(404)
    return jsonify({"text": E.build(c) or E.read_project_file(c.get("project")) or "Aún no hay trabajo registrado."})


@app.delete("/api/conversations/<cid>")
def del_conv(cid):
    conv_path(cid).unlink(missing_ok=True)
    return jsonify({"ok": True})


@app.post("/api/conversations/<cid>")
def patch_conv(cid):
    c = load_conv(cid)
    if not c:
        abort(404)
    d = J()
    for k in ("title", "project", "model"):
        if k in d:
            c[k] = d[k]
    save_conv(c)
    return jsonify({"ok": True})


@app.post("/api/confirm")
def confirm():
    d = J()
    p = PENDING.get(d.get("id"))
    if p:
        p["ok"], p["always"] = bool(d.get("approved")), bool(d.get("always"))
        p["event"].set()
    return jsonify({"ok": bool(p)})


@app.post("/api/plan/<rid>")
def plan_resp(rid):
    from noviq import cerebro as CB
    d = J()
    return jsonify({"ok": CB.responder(rid, d.get("accion", "aprobar"), d.get("plan"))})


@app.post("/api/stop")
def stop():
    cid = J().get("conversation_id")
    if cid in STOP:
        STOP[cid].set()
    return jsonify({"ok": True})


@app.post("/api/chat")
def chat():
    d = J()
    cid = d.get("conversation_id") or uuid.uuid4().hex[:16]
    conv = load_conv(cid) or new_conv(cid, d.get("project"), d.get("model") or CONFIG["model"])
    if d.get("model"):
        conv["model"] = d["model"]
    if d.get("idioma") in ("es", "en"):
        conv["idioma"] = d["idioma"]
    if "project" in d and not conv["messages"]:
        conv["project"] = d.get("project")
    if cid in RUNNING:
        return jsonify({"error": "Esta conversación ya está trabajando."}), 409

    if d.get("regenerate"):
        # vuelve al último mensaje del usuario
        idx = max((i for i, x in enumerate(conv["display"]) if x["type"] == "user"), default=None)
        if idx is None:
            return jsonify({"error": "nada que regenerar"}), 400
        conv["messages"] = conv["messages"][:conv["display"][idx].get("msg_index", 0) + 1]
        conv["display"] = conv["display"][:idx + 1]
    else:
        text = (d.get("text") or "").strip()
        images = d.get("images") or []
        files = d.get("files") or []
        is_continue = bool(d.get("continuar")) or (not images and not files and re.fullmatch(
            r"(?i)\W*(contin[uú]a(r)?|sigue|seguir|prosigue|dale|contin[uú]a por favor)\W*", text or "") is not None)
        if is_continue and conv["messages"]:
            content = E.continue_message(conv)
            shown = text if text and not d.get("continuar") else "▶ Continuar el trabajo"
        else:
            E.record_user(conv, text)
            if files:
                text += "\n\n[Archivos adjuntos por el usuario: " + ", ".join(files) + " — léelos con leer_archivo]"
            content = ([{"type": "text", "text": text or "Describe esta imagen."}]
                       + [{"type": "image_url", "image_url": {"url": u}} for u in images[:8]]) if images else text
            shown = d.get("text", "")
        conv["display"].append({"type": "user", "text": shown, "images": images[:8], "files": files,
                                "msg_index": len(conv["messages"])})
        conv["messages"].append({"role": "user", "content": content})
        if conv["title"] == "Nueva conversación":
            conv["title"] = (d.get("text") or "Imagen").strip()[:60] or "Conversación"
    save_conv(conv)

    start_job(conv)
    return _stream_response(cid, 0)


def start_job(conv):
    """Arranca el agente de una conversación en su propio hilo. Cada conversación/proyecto trabaja en paralelo
    e independiente: puedes cambiar de chat, abrir otro proyecto con otra IA, y volver cuando quieras."""
    cid = conv["id"]
    for k, jb in list(JOBS.items()):  # limpia trabajos terminados hace más de 15 min
        if jb["done"] and time.time() - jb["t_end"] > 900:
            JOBS.pop(k, None)
    job = {"events": [], "cond": threading.Condition(), "done": False, "conv": conv,
           "display_start": len(conv["display"]), "t": time.time(), "t_end": 0}
    JOBS[cid] = job
    stop_ev = threading.Event()
    STOP[cid] = stop_ev
    RUNNING.add(cid)

    def emit(kind, payload):
        with job["cond"]:
            job["events"].append((kind, payload))
            job["cond"].notify_all()

    def worker():
        try:
            run_agent(conv, emit, stop_ev)
        except APIError as e:
            conv["en_progreso"] = True
            emit("error", {"text": str(e)})
            conv["display"].append({"type": "error", "text": str(e)})
        except Exception as e:
            import traceback
            traceback.print_exc()
            emit("error", {"text": f"{type(e).__name__}: {e}"})
            conv["display"].append({"type": "error", "text": f"{type(e).__name__}: {e}"})
        finally:
            try:
                save_conv(conv)
            finally:
                RUNNING.discard(cid)
                STOP.pop(cid, None)
                with job["cond"]:
                    job["done"], job["t_end"] = True, time.time()
                    job["cond"].notify_all()

    threading.Thread(target=worker, daemon=True, name=f"agente-{cid}").start()
    return job


def _stream_response(cid, since=0):
    job = JOBS.get(cid)
    conv = job["conv"]
    from noviq.tools import ASK
    from noviq import cerebro as CB

    def gen():
        yield f"event: meta\ndata: {json.dumps({'conversation_id': cid, 'title': conv['title'], 'project': conv.get('project'), 'model': conv.get('model')})}\n\n"
        i = since
        while True:
            with job["cond"]:
                if i >= len(job["events"]) and not job["done"]:
                    job["cond"].wait(15)
                evs = job["events"][i:]
                done = job["done"]
            if not evs and not done:
                yield ": ping\n\n"
                continue
            for kind, payload in evs:
                i += 1
                # al volver a una conversación, no se repiten preguntas ya respondidas
                if kind == "confirm" and payload.get("id") not in PENDING:
                    continue
                if kind == "ask_user" and payload.get("id") not in ASK:
                    continue
                if kind == "plan_review" and payload.get("id") not in CB.PLANS:
                    continue
                yield f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            if done and i >= len(job["events"]):
                break
        yield "event: done\ndata: {}\n\n"

    return Response(stream_with_context(gen()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/chat/<cid>/stream")
def chat_stream(cid):
    """Reengancharse a una conversación que sigue trabajando (tras cambiar de chat o recargar la página)."""
    if cid not in JOBS:
        return jsonify({"error": "Esta conversación no está trabajando."}), 404
    return _stream_response(cid, int(request.args.get("since") or 0))


@app.get("/api/trabajando")
def trabajando():
    out = []
    for cid, jb in JOBS.items():
        if not jb["done"]:
            c = jb["conv"]
            pend = any(k in ("confirm", "ask_user") and p.get("id") in PENDING for k, p in jb["events"][-50:]) if PENDING else False
            out.append({"id": cid, "title": c.get("title"), "project": c.get("project"), "model": c.get("model"),
                        "desde": jb["t"], "espera_permiso": pend})
    return jsonify(out)


# ───────────── Archivos ─────────────
@app.get("/f")
def serve_file():
    p = Path(request.args.get("p", ""))
    if not p.is_file():
        abort(404)
    return send_file(p, as_attachment=request.args.get("d") == "1", max_age=0)


@app.get("/raw/<tok>/<path:fp>")
def serve_raw(tok, fp):
    """Sirve archivos por ruta absoluta para la vista previa (HTML con sus CSS/JS relativos)."""
    if tok != TOKEN:
        abort(403)
    p = Path(fp if IS_WINDOWS else "/" + fp)
    if p.is_dir() and (p / "index.html").exists():
        p = p / "index.html"
    if not p.is_file():
        abort(404)
    return send_file(p, max_age=0)


@app.get("/api/file_text")
def file_text():
    p = Path(request.args.get("p", ""))
    if not p.is_file() or p.stat().st_size > 3_000_000:
        abort(404)
    return jsonify({"text": T._read_text(p), "name": p.name, "path": str(p)})


@app.post("/api/upload")
def upload():
    project = request.form.get("project") or ""
    base = project_path(project) if project and project_path(project).exists() else general_dir()
    dest = base / "adjuntos"
    dest.mkdir(exist_ok=True)
    saved = []
    for f in request.files.getlist("files"):
        name = T.safe_name(Path(f.filename).name) or "archivo"
        p = dest / name
        if p.exists():
            p = dest / f"{p.stem}_{int(time.time())}{p.suffix}"
        f.save(p)
        saved.append(str(p))
    return jsonify({"files": saved})


@app.post("/api/abrir")
def abrir():
    ruta = J().get("ruta") or str(projects_root())
    p = Path(ruta)
    if not p.exists():
        return jsonify({"ok": False}), 404
    if IS_WINDOWS:
        if p.is_file():
            subprocess.Popen(["explorer", "/select,", str(p)])
        else:
            os.startfile(str(p))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(p)] if p.is_file() else ["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p.parent if p.is_file() else p)])
    return jsonify({"ok": True})


@app.post("/api/guardar_codigo")
def guardar_codigo():
    d = J()
    project = d.get("project")
    base = project_path(project) if project and project_path(project).exists() else general_dir()
    p = Path(d.get("nombre") or "codigo.txt")
    p = p if p.is_absolute() else base / p
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(d.get("contenido", ""), encoding="utf-8")
    return jsonify({"ok": True, "path": str(p), "name": p.name})


# ───────────── Memoria y MCP ─────────────
@app.get("/api/memoria")
def get_mem():
    return jsonify({"text": T.read_memory()})


@app.post("/api/memoria")
def set_mem():
    MEMORY_FILE.write_text(J().get("text", ""), encoding="utf-8")
    return jsonify({"ok": True})


@app.get("/api/mcp")
def mcp_get():
    return jsonify({"config": MANAGER.load_config_text(), "servers": MANAGER.status()})


@app.post("/api/mcp")
def mcp_set():
    try:
        MANAGER.save_config_text(J().get("config", "{}"))
    except Exception as e:
        return jsonify({"ok": False, "error": f"JSON inválido: {e}"}), 400
    MANAGER.reload()
    time.sleep(1.5)
    return jsonify({"ok": True, "servers": MANAGER.status()})


@app.post("/api/diagnostico")
def diagnostico():
    """Prueba rápida de un modelo: ¿responde?, ¿usa herramientas nativas?, ¿cuánto razona?"""
    from noviq.config import set_override
    from noviq.providers import parse_text_tool_calls, stream_chat, strip_tool_text
    model = J().get("model") or CONFIG["model"]
    tool = {"type": "function", "function": {"name": "obtener_hora", "description": "Devuelve la hora actual de una ciudad",
            "parameters": {"type": "object", "properties": {"ciudad": {"type": "string"}}, "required": ["ciudad"]}}}
    msgs = [{"role": "system", "content": "Eres un asistente. Cuando se pida, usa las herramientas disponibles."},
            {"role": "user", "content": "¿Qué hora es en Quito? Usa la herramienta obtener_hora."}]
    res = {"model": model}
    t0 = time.time()
    try:
        raw, reasoning, calls, finish = stream_chat(model, msgs, [tool], lambda k, v: None, threading.Event(), max_attempts=2)
        res.update(ok=True, finish=finish, reasoning_chars=len(reasoning), content=strip_tool_text(raw)[:300],
                   native=bool(calls), text_format=False)
        if calls:
            set_override(model, "tool_mode", "nativo")
            res["verdict"] = "✔ Usa herramientas nativas correctamente."
        else:
            tc = parse_text_tool_calls(raw, {"obtener_hora"})
            if tc:
                set_override(model, "tool_mode", "texto")
                res.update(text_format=True, verdict="✔ Usa herramientas escritas como texto (configurado en modo texto).")
            elif finish == "length":
                res["verdict"] = "⚠ Se quedó sin tokens razonando. El programa subirá el límite y reducirá el razonamiento automáticamente."
            else:
                res["verdict"] = "⚠ Respondió sin usar la herramienta. Puede funcionar para chat, pero no es bueno como agente."
    except APIError as e:
        res.update(ok=False, error=str(e)[:600], verdict="✖ Error: " + str(e)[:200])
    res["seconds"] = round(time.time() - t0, 1)
    return jsonify(res)


@app.get("/api/registro")
def registro():
    from noviq.config import DATA_DIR
    f = DATA_DIR / "registro.log"
    lines = f.read_text(encoding="utf-8").splitlines()[-80:] if f.exists() else []
    return jsonify({"lines": lines})


@app.post("/api/responder")
def responder():
    """Respuesta del usuario a pedir_ayuda_usuario (texto + capturas)."""
    d = J()
    p = T.ASK.get(d.get("id"))
    if p:
        p["texto"], p["imagenes"] = d.get("texto", ""), d.get("imagenes") or []
        p["event"].set()
    return jsonify({"ok": bool(p)})


@app.post("/api/mcp/preset")
def mcp_preset():
    from noviq.mcp import PRESETS
    key = J().get("key")
    if key not in PRESETS:
        abort(400)
    MANAGER.add_preset(key)
    time.sleep(2)
    return jsonify({"ok": True, "config": MANAGER.load_config_text(), "servers": MANAGER.status()})


@app.get("/api/sistema")
def sistema():
    import shutil
    chrome = edge = None
    if IS_WINDOWS:
        pf = [os.environ.get(k, "") for k in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
        chrome = any(Path(b, "Google/Chrome/Application/chrome.exe").exists() for b in pf if b)
        edge = any(Path(b, "Microsoft/Edge/Application/msedge.exe").exists() for b in pf if b)
    return jsonify({"node": bool(shutil.which("npx")), "chrome": chrome, "edge": edge,
                    "navegador_activo": MANAGER.has_browser()})


# ───────────── Catálogo de modelos (globo informativo) ─────────────
@app.get("/api/catalogo")
def catalogo_api():
    from noviq import catalogo as K
    infos = K.all_infos(max_age=0 if request.args.get("refresh") else (3 if request.args.get("rapido") else 20))
    return jsonify({"modelos": infos, "recomendaciones": K.recomendaciones(infos),
                    "vanguardia": K.ranking(infos, need_tools=True), "cerebros": K.ranking(infos, need_tools=False, n=3),
                    "config_vanguardia": CONFIG.get("vanguardia") or {}, "modelo_cerebro": CONFIG.get("modelo_cerebro", "auto")})


@app.post("/api/vanguardia")
def vanguardia_api():
    """Modo vanguardia: usar siempre los modelos gratuitos más inteligentes (principal + respaldo)."""
    from noviq import catalogo as K
    d = request.get_json(silent=True) or {}
    V = dict(CONFIG.get("vanguardia") or {})
    for k in ("activo", "planificar"):
        if k in d:
            V[k] = bool(d[k])
    if "modelo_cerebro" in d:
        CONFIG["modelo_cerebro"] = (d.get("modelo_cerebro") or "auto").strip()
    out = {}
    if d.get("aplicar"):
        from noviq.providers import probe
        infos = K.all_infos(max_age=0)
        cand = K.ranking(infos, need_tools=True, n=10)
        res = {}
        ths = [threading.Thread(target=lambda m=m: res.__setitem__(m, probe(m, 40)), daemon=True) for m in cand]
        for t in ths:
            t.start()
        for t in ths:
            t.join(50)
        rank = [m for m in cand if (res.get(m) or {}).get("ok")][:6]
        out["descartados"] = {m: r for m, r in res.items() if not r.get("ok")}
        if not rank:
            return jsonify({"ok": False, "error": "Ningún modelo gratuito en la nube respondió. Conecta alguno en 🎁 IA gratis.", **out})
        CONFIG["model"] = rank[0]
        CONFIG["fallback_models"] = rank[1:]
        CONFIG["fallback_enabled"] = True
        V["activo"] = True
        out.update({"modelo": rank[0], "respaldo": rank[1:]})
    CONFIG["vanguardia"] = V
    save_config()
    return jsonify({"ok": True, "vanguardia": V, **out})


# ───────────── Salud de modelos ─────────────
@app.get("/api/salud")
def salud_api():
    from noviq import salud as S
    from noviq.providers import _models_cache
    prov = []
    for pid, pc in CONFIG["providers"].items():
        if not pc.get("enabled"):
            continue
        c = _models_cache.get(pid) or {}
        st = S.provider_state(pid)
        if (c and not c.get("ok")) or st:
            prov.append({"id": pid, "nombre": pc.get("name", pid), "error": c.get("error") or (st or {}).get("motivo", ""),
                         "kind": c.get("kind") or (st or {}).get("kind"), "solucion": (st or {}).get("solucion", "")})
    return jsonify({"problemas": prov, **S.resumen()})


@app.post("/api/claves/probar")
def claves_probar():
    """Prueba cada API key de un proveedor por separado (lista de modelos + un mensaje mínimo)."""
    import requests as rq
    from noviq import salud as S
    from noviq.providers import _headers, provider_cfg
    pid = J().get("pid")
    try:
        p = provider_cfg(pid)
    except Exception as e:
        return jsonify({"error": str(e)})
    keys = vault.get_keys(pid)
    test_model = next((m.split("::", 1)[1] for m, t in S._load().get("verificados", {}).items() if m.startswith(pid + "::")), None)
    out = []
    for n, k in enumerate(keys, 1):
        item = {"n": n, "mask": vault.mask(k), "ok": False, "modelos": None, "error": ""}
        try:
            r = rq.get(p["base_url"].rstrip("/") + "/models", headers=_headers(k, p), timeout=20)
            if r.status_code in (401, 403):
                item["error"] = "clave inválida o vencida"
            else:
                try:
                    item["modelos"] = len((r.json() or {}).get("data") or [])
                except ValueError:
                    pass
                item["ok"] = r.status_code == 200
                if test_model:
                    c = rq.post(p["base_url"].rstrip("/") + "/chat/completions", headers=_headers(k, p), timeout=40,
                                json={"model": test_model, "messages": [{"role": "user", "content": "ok"}], "max_tokens": 8})
                    if c.status_code in (401, 403):
                        item.update(ok=False, error="la clave no tiene permiso para chatear")
                    elif c.status_code == 404 and "account" in c.text.lower():
                        item.update(ok=True, error="")
                        item["nota"] = f"{test_model} no está en esta cuenta"
                if not item["ok"] and not item["error"]:
                    item["error"] = f"respondió {r.status_code}"
        except rq.RequestException as e:
            item["error"] = f"sin conexión ({type(e).__name__})"
        out.append(item)
    return jsonify({"claves": out})


@app.post("/api/salud/probar")
def salud_probar():
    from noviq.providers import probe
    ids = (J().get("ids") or [])[:12]
    res = {}
    ths = [threading.Thread(target=lambda m=m: res.__setitem__(m, probe(m, 40)), daemon=True) for m in ids]
    for t in ths:
        t.start()
    for t in ths:
        t.join(50)
    return jsonify(res)


@app.route("/api/verificador", methods=["GET", "POST"])
def verificador_api():
    from noviq import verificador
    if request.method == "POST":
        d = J()
        verificador.pedir(d.get("pid") or None, forzar=bool(d.get("forzar")))
    return jsonify(verificador.estado())


@app.post("/api/salud/reset")
def salud_reset():
    from noviq import salud as S
    S.reset(J().get("model") or None)
    return jsonify({"ok": True})


# ───────────── IA local ─────────────
@app.post("/api/optimizar_ollama")
def optimizar_ollama():
    from noviq import local as LOC
    env = LOC.optimizar_ollama_windows()
    done = []
    if IS_WINDOWS:
        for k, v in env.items():
            r = subprocess.run(["setx", k, v], capture_output=True, text=True, creationflags=0x08000000)
            done.append({"var": k, "valor": v, "ok": r.returncode == 0})
        CONFIG.setdefault("local", {})["kv_q8"] = True
        save_config()
        return jsonify({"ok": True, "hecho": done, "nota": "Cierra Ollama (icono junto al reloj → Quit) y vuelve a abrirlo para aplicar."})
    return jsonify({"ok": False, "hecho": [], "nota": "En este sistema agrega estas variables al servicio de Ollama: "
                    + ", ".join(f"{k}={v}" for k, v in env.items())})


# ───────────── Proyectos existentes ─────────────
@app.post("/api/elegir_carpeta")
def elegir_carpeta():
    """Abre el selector de carpetas nativo del sistema y devuelve la ruta elegida."""
    code = ("import tkinter as tk\nfrom tkinter import filedialog\nr=tk.Tk();r.withdraw();r.attributes('-topmost',True)\n"
            "print(filedialog.askdirectory(title='Elige la carpeta raíz del proyecto') or '')")
    ruta = ""
    try:
        from noviq.config import FROZEN
        cmd = [sys.executable, "--elegir-carpeta"] if FROZEN else [sys.executable, "-c", code]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        ruta = r.stdout.strip()
    except Exception:
        pass
    if not ruta and IS_WINDOWS:
        ps = ("Add-Type -AssemblyName System.Windows.Forms; $d=New-Object System.Windows.Forms.FolderBrowserDialog;"
              "$d.Description='Elige la carpeta raíz del proyecto'; if($d.ShowDialog() -eq 'OK'){$d.SelectedPath}")
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps], capture_output=True, text=True, timeout=600)
            ruta = r.stdout.strip()
        except Exception:
            pass
    return jsonify({"ruta": ruta})


@app.get("/api/projects/<name>/estado")
def project_estado(name):
    return jsonify({"text": E.read_project_file(name) or ""})


@app.post("/api/projects/importar")
def importar_proyecto():
    d = J()
    try:
        name, p, det = T.import_project(d.get("ruta", ""), d.get("nombre", ""))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "name": name, "path": str(p), **det})


@app.post("/api/projects/<name>/quitar")
def quitar_proyecto(name):
    return jsonify({"ok": T.unlink_project(name)})


# ───────────── Explorador de archivos ─────────────
def _safe_write_path(ruta):
    p = Path(ruta).resolve()
    if not T.inside_root(p):
        abort(403, "Solo se puede modificar dentro de tus proyectos")
    return p


@app.get("/api/ruta_info")
def ruta_info():
    raw = (request.args.get("p") or "").strip().strip('"').strip("'")
    if raw.startswith("file:///"):
        raw = raw[8:] if IS_WINDOWS else raw[7:]
    from urllib.parse import unquote
    p = Path(unquote(raw)).expanduser()
    if not p.is_absolute():
        cands = [project_path(n) / p for n in ([request.args.get("proyecto")] if request.args.get("proyecto") else [])] + [projects_root() / p]
        p = next((c for c in cands if c.exists()), p)
    return jsonify({"existe": p.exists(), "dir": p.is_dir(), "ruta": str(p)})


@app.get("/api/arbol")
def arbol():
    p = Path(request.args.get("ruta", "")).resolve()
    if not p.is_dir():
        abort(404)
    items = []
    try:
        for c in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if c.name in (".git", "node_modules", "__pycache__", ".venv", "venv", ".noviq", ".pytest_cache"):
                continue
            try:
                st = c.stat()
            except OSError:
                continue
            items.append({"name": c.name, "path": str(c), "dir": c.is_dir(), "size": st.st_size if c.is_file() else None,
                          "mtime": st.st_mtime})
            if len(items) >= 500:
                break
    except PermissionError:
        pass
    return jsonify({"path": str(p), "items": items, "editable": T.inside_root(p)})


@app.post("/api/archivo/guardar")
def archivo_guardar():
    d = J()
    p = _safe_write_path(d.get("ruta", ""))
    if p.exists():
        ctx = T.ToolContext({"project": d.get("proyecto"), "respaldos": []}, lambda *a: None, threading.Event())
        T._backup(ctx, p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(d.get("contenido", ""), encoding="utf-8", newline="")
    return jsonify({"ok": True, "size": p.stat().st_size})


@app.post("/api/archivo/mover")
def archivo_mover():
    import shutil as _sh
    d = J()
    src = _safe_write_path(d.get("origen", ""))
    dst_dir = _safe_write_path(d.get("destino", ""))
    if not dst_dir.is_dir():
        dst_dir = dst_dir.parent
    dst = dst_dir / src.name
    if dst.exists() or str(dst_dir).startswith(str(src)):
        return jsonify({"ok": False, "error": "Ya existe un archivo con ese nombre en el destino o destino inválido."}), 400
    _sh.move(str(src), str(dst))
    return jsonify({"ok": True, "path": str(dst)})


@app.post("/api/archivo/renombrar")
def archivo_renombrar():
    d = J()
    src = _safe_write_path(d.get("ruta", ""))
    nuevo = T.safe_name(d.get("nombre", ""))
    dst = src.parent / nuevo
    if dst.exists():
        return jsonify({"ok": False, "error": "Ya existe ese nombre."}), 400
    src.rename(dst)
    return jsonify({"ok": True, "path": str(dst)})


@app.post("/api/archivo/nuevo")
def archivo_nuevo():
    d = J()
    carpeta = _safe_write_path(d.get("carpeta", ""))
    p = carpeta / T.safe_name(d.get("nombre", "nuevo.txt"))
    if p.exists():
        return jsonify({"ok": False, "error": "Ya existe."}), 400
    if d.get("tipo") == "carpeta":
        p.mkdir(parents=True)
    else:
        p.write_text("", encoding="utf-8")
    return jsonify({"ok": True, "path": str(p)})


@app.post("/api/archivo/eliminar")
def archivo_eliminar():
    p = _safe_write_path(J().get("ruta", ""))
    ctx = T.ToolContext({"project": None}, lambda *a: None, threading.Event())
    r = T.t_eliminar({"ruta": str(p)}, ctx)
    return jsonify({"ok": not r.startswith("ERROR"), "msg": r})


# ───────────── IA gratis ─────────────
@app.get("/api/gratis")
def gratis_list():
    from noviq import gratis as G
    from noviq.providers import _models_cache
    out = []
    for g in G.GRATIS:
        p = CONFIG["providers"].get(g["id"], {})
        c = _models_cache.get(g["id"]) or {}
        out.append(dict(g, activo=bool(p.get("enabled")), tiene_clave=bool(vault.get_keys(g["id"])),
                        ok=bool(c.get("ok")), modelos=len(c.get("models") or []), error=c.get("error", ""),
                        solo_gratis=p.get("solo_gratis"), cuenta=p.get("cuenta", ""),
                        url=(p.get("base_url") or "").removesuffix("/v1") if g.get("remoto") else ""))
    return jsonify(out)


@app.post("/api/gratis/guardar")
def gratis_guardar():
    from noviq.providers import list_models
    d = J()
    pid, key = d.get("id"), (d.get("clave") or "").strip()
    if pid not in CONFIG["providers"]:
        abort(400)
    if key:
        vault.set_keys(pid, list(dict.fromkeys(vault.get_keys(pid) + [key])))
        from noviq import salud as S
        S.reset_proveedor(pid)
    if d.get("cuenta"):
        CONFIG["providers"][pid]["cuenta"] = d["cuenta"].strip()
    if d.get("url"):
        u = d["url"].strip().rstrip("/")
        CONFIG["providers"][pid]["base_url"] = u if u.endswith("/v1") else u + "/v1"
    if key and CONFIG["providers"][pid].get("remoto"):
        vault.set_keys(pid, [key])  # el token del servidor remoto cambia en cada sesión
    CONFIG["providers"][pid]["enabled"] = True
    if CONFIG["providers"][pid].get("decisor"):
        save_config()
        from noviq import decisor
        nivel, fuente = decisor.riesgo("ejecutar_powershell", {"comando": "Get-ChildItem"})
        return jsonify({"ok": True, "modelos": 0, "error": "", "ejemplos": [],
                        "nota": f"Decisor: {'Jev respondió ✔' if fuente == 'jev' else 'Jev no respondió; se usan las reglas locales (' + decisor.estado().get('ultimo_error', '') + ')'}"})
    if "solo_gratis" in d:
        CONFIG["providers"][pid]["solo_gratis"] = bool(d["solo_gratis"])
    save_config()
    r = list_models(pid, refresh=True)
    if r["ok"]:
        from noviq import verificador
        verificador.pedir(pid, forzar=bool(key))  # el verificador comprueba qué modelos responden de verdad
    return jsonify({"ok": r["ok"], "modelos": len(r["models"]), "error": r["error"], "ejemplos": r["models"][:6]})


@app.get("/api/remoto/cuaderno")
def remoto_cuaderno():
    from noviq import remoto
    nb, token = remoto.cuaderno(request.args.get("modelo") or "qwen3-coder:30b")
    return Response(nb, mimetype="application/x-ipynb+json",
                    headers={"Content-Disposition": "attachment; filename=noviq_servidor_gpu_kaggle.ipynb"})


@app.get("/api/decisor")
def decisor_estado():
    from noviq import decisor
    return jsonify(decisor.estado())


@app.post("/api/gratis/openrouter")
def gratis_openrouter():
    from noviq import gratis as G
    return jsonify({"url": G.openrouter_auth_url(PORT)})


@app.get("/oauth/openrouter")
def oauth_openrouter():
    from noviq import gratis as G
    from noviq.providers import list_models
    try:
        key = G.openrouter_exchange(request.args.get("state", ""), request.args.get("code", ""))
        vault.set_keys("openrouter", list(dict.fromkeys(vault.get_keys("openrouter") + [key])))
        CONFIG["providers"]["openrouter"]["enabled"] = True
        CONFIG["providers"]["openrouter"].setdefault("solo_gratis", True)
        save_config()
        list_models("openrouter", refresh=True)
        msg, color = "✅ ¡OpenRouter conectado! Ya puedes cerrar esta pestaña y volver a Noviark.", "#3fdc2b"
    except Exception as e:
        msg, color = f"❌ No se pudo conectar: {e}", "#ef5350"
    return Response(f"""<!doctype html><meta charset="utf-8"><title>Noviark</title>
<body style="background:#0a0f14;color:#e8f0ec;font:18px Segoe UI,sans-serif;display:grid;place-items:center;height:100vh;margin:0">
<div style="text-align:center"><img src="/static/noviq_icon.png" width="96" style="border-radius:18px"><p style="color:{color}">{html_escape(msg)}</p></div>
<script>setTimeout(()=>window.close(),2500)</script></body>""", mimetype="text/html")


@app.get("/api/tools")
def tools_list():
    return jsonify([{"name": t["function"]["name"], "desc": t["function"]["description"]} for t in T.BUILTIN + MANAGER.tool_defs(include_browser=True)])


# ───────────── Tareas programadas ─────────────
def _run_scheduled(t):
    """Arranca una tarea programada como una conversación más (trabaja en paralelo con las demás)."""
    from noviq import programador as PG  # noqa: F401
    cid = t.get("conv_id") if t.get("misma_conv") and t.get("conv_id") else None
    conv = load_conv(cid) if cid else None
    if conv and conv["id"] in RUNNING:
        return None
    if not conv:
        cid = uuid.uuid4().hex[:16]
        conv = new_conv(cid, t.get("proyecto"), t.get("modelo") or CONFIG["model"])
        conv["title"] = "⏰ " + (t.get("nombre") or "Tarea programada")[:55]
    if t.get("autonomo", True):
        conv["permiso"] = "auto"
    text = f"[Tarea programada «{t.get('nombre')}» · {time.strftime('%Y-%m-%d %H:%M')}]\n{t.get('instruccion', '')}"
    E.record_user(conv, text)
    conv["display"].append({"type": "user", "text": text, "images": [], "files": [], "msg_index": len(conv["messages"])})
    conv["messages"].append({"role": "user", "content": text})
    save_conv(conv)
    start_job(conv)
    return conv["id"]


@app.get("/api/programadas")
def prog_list():
    from noviq import programador as PG
    return jsonify(PG.listar())


@app.post("/api/programadas")
def prog_save():
    from noviq import programador as PG
    d = J()
    try:
        t = PG.crear(d.get("nombre"), d.get("instruccion") or "", d.get("cuando") or {}, d.get("proyecto"), d.get("modelo"),
                     d.get("autonomo", True), d.get("misma_conv", False), d.get("recuperar", True), d.get("id"))
        return jsonify({"ok": True, "tarea": dict(t, descripcion=PG.describe(t))})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.post("/api/programadas/<tid>/<accion>")
def prog_action(tid, accion):
    from noviq import programador as PG
    if accion == "ejecutar":
        return jsonify({"ok": True, "conv": PG.ejecutar_ahora(tid)})
    if accion in ("pausar", "reanudar"):
        PG.activar(tid, accion == "reanudar")
    elif accion == "eliminar":
        PG.eliminar(tid)
    return jsonify({"ok": True})


@app.route("/api/inicio_windows", methods=["GET", "POST"])
def inicio_windows():
    """Acceso directo en la carpeta Inicio de Windows para que Noviark (y sus tareas programadas) arranque con el PC."""
    if not IS_WINDOWS:
        return jsonify({"ok": False, "activo": False, "error": "Solo en Windows."})
    import subprocess
    startup = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup"
    lnk = startup / "Noviark.lnk"
    if request.method == "GET":
        return jsonify({"ok": True, "activo": lnk.exists()})
    on = bool(J().get("activo"))
    if not on:
        lnk.unlink(missing_ok=True)
        return jsonify({"ok": True, "activo": False})
    from noviq.config import FROZEN
    target = Path(sys.executable) if FROZEN else BASE_DIR / "iniciar.bat"
    ico = BASE_DIR / "static" / "noviq.ico"
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}'); $s.TargetPath='{target}'; "
          + ("$s.Arguments='--no-browser'; " if FROZEN else "")
          + f"$s.WorkingDirectory='{target.parent}'; $s.WindowStyle=7; $s.IconLocation='{ico}'; $s.Save()")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    return jsonify({"ok": lnk.exists(), "activo": lnk.exists(), "error": r.stderr[-300:]})


# ───────────── Control del PC ─────────────
@app.get("/api/pc")
def pc_estado():
    from noviq.mcp import PC_SERVERS
    st = [x for x in MANAGER.status() if x["name"] in PC_SERVERS]
    import shutil
    return jsonify({"windows": IS_WINDOWS, "windows_mcp": st[0] if st else None, "uv": bool(shutil.which("uvx"))})


@app.post("/api/pc/probar")
def pc_probar():
    from noviq import pc
    return jsonify(pc.probar())


@app.post("/api/pc/activar")
def pc_activar():
    """Instala uv (si falta) y agrega Windows-MCP como servidor MCP."""
    import shutil
    import subprocess
    log = []
    if not shutil.which("uvx"):
        from noviq.config import python_exe
        py = python_exe()
        if not py:
            return jsonify({"ok": False, "error": "Falta Python en tu PC. Instala uv con: winget install astral-sh.uv", "log": log})
        r = subprocess.run([py, "-m", "pip", "install", "--upgrade", "uv"], capture_output=True, text=True, timeout=300)
        log.append("pip install uv: " + ("ok" if r.returncode == 0 else r.stderr[-300:]))
        scripts = Path(py).parent / ("Scripts" if IS_WINDOWS else "")
        if (scripts / "uvx.exe").exists() or (scripts / "uvx").exists():
            os.environ["PATH"] = str(scripts) + os.pathsep + os.environ.get("PATH", "")
    if not shutil.which("uvx"):
        return jsonify({"ok": False, "error": "No pude instalar uv. Instálalo con: winget install astral-sh.uv", "log": log})
    MANAGER.add_preset("control_pc")
    return jsonify({"ok": True, "log": log, "nota": "Windows-MCP se está iniciando (la primera vez descarga Python 3.13 y tarda 1-2 min)."})


# ───────────── Aprendizaje ─────────────
@app.get("/api/aprendizaje")
def apr_list():
    from noviq import aprendizaje as A
    return jsonify(A.listar())


@app.post("/api/aprendizaje")
def apr_set():
    from noviq import aprendizaje as A
    d = J()
    if "activo" in d:
        CONFIG["aprendizaje"] = bool(d["activo"])
        save_config()
    if d.get("borrar") is not None:
        A.borrar(d.get("borrar") or None)
    return jsonify({"ok": True})


@app.post("/api/apagar")
def apagar():
    """Cierra Noviark por completo (botón ⏻ o el icono de la bandeja)."""
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return jsonify({"ok": True})


def puerto_ocupado(port=PORT):
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s_:
        s_.settimeout(0.5)
        return s_.connect_ex(("127.0.0.1", port)) == 0


def main(abrir_navegador=True, bloquear=True, abrir_si_ocupado=True):
    """Arranca el servidor. Si Noviark ya estaba abierto, solo muestra su ventana/página."""
    url = f"http://127.0.0.1:{PORT}"
    if puerto_ocupado():
        if abrir_si_ocupado:
            try:
                import noviq_app
                if not (noviq_app.ventana_nativa(url) or noviq_app.ventana_app(url)):
                    webbrowser.open(url)
            except Exception:
                webbrowser.open(url)
        return None
    from noviq.config import DATA_DIR, VERSION
    try:
        (DATA_DIR / ".token").write_text(TOKEN, encoding="utf-8")  # para «noviq --stop» y la bandeja
    except OSError:
        pass
    print("=" * 64)
    print(f"  Noviark {VERSION} listo en:", url)
    print("  Proyectos en:            ", projects_root())
    print("  Datos en:                ", DATA_DIR)
    print("=" * 64)
    threading.Thread(target=MANAGER.reload, daemon=True).start()
    from noviq import programador, verificador
    programador.iniciar(_run_scheduled)
    verificador.iniciar()
    if abrir_navegador:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    kw = dict(host="127.0.0.1", port=PORT, threaded=True, debug=False, use_reloader=False)
    if bloquear:
        app.run(**kw)
        return None
    th = threading.Thread(target=lambda: app.run(**kw), daemon=True)
    th.start()
    return url


if __name__ == "__main__":
    main("--no-browser" not in sys.argv)
