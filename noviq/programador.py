# -*- coding: utf-8 -*-
"""Tareas programadas de Noviark: la IA hace un trabajo sola a una hora (una vez, cada día, ciertos días
o cada N minutos) — revisar algo, generar un informe, abrir programas, probar un proyecto…
Funcionan mientras Noviark está abierto (activa «Iniciar Noviark con Windows» para que siempre lo esté).
Si el PC estaba apagado a la hora programada, la tarea se hace al abrir Noviark (si «recuperar» está activo)."""
import json
import threading
import time
import uuid
from datetime import datetime, timedelta

from .config import DATA_DIR

FILE = DATA_DIR / "tareas_programadas.json"
_lock = threading.Lock()
_runner = None
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def _load():
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(tasks):
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(FILE)


def _hm(s):
    h, m = (s or "08:00").split(":")[:2]
    return int(h), int(m)


def next_run(t, after=None):
    """Próxima ejecución (timestamp) o None."""
    now = after or datetime.now()
    c = t.get("cuando") or {}
    tipo = c.get("tipo", "una_vez")
    try:
        if tipo == "una_vez":
            d = datetime.fromisoformat(c.get("fecha"))
            return d.timestamp() if d > now or not t.get("ultima") else None
        if tipo == "intervalo":
            n = max(5, int(c.get("cada_min") or 60))
            base = datetime.fromtimestamp(t["ultima"]) if t.get("ultima") else now
            d = base + timedelta(minutes=n)
            return max(d, now + timedelta(seconds=20)).timestamp()
        if tipo in ("diario", "semanal"):
            h, m = _hm(c.get("hora"))
            dias = c.get("dias") if c.get("dias") else list(range(7))
            for k in range(0, 8):
                d = (now + timedelta(days=k)).replace(hour=h, minute=m, second=0, microsecond=0)
                if d > now and d.weekday() in dias:
                    return d.timestamp()
    except Exception:
        return None
    return None


def describe(t):
    c = t.get("cuando") or {}
    tipo = c.get("tipo")
    if tipo == "una_vez":
        return "una vez, " + (c.get("fecha") or "").replace("T", " ")[:16]
    if tipo == "intervalo":
        return f"cada {c.get('cada_min')} min"
    dias = c.get("dias")
    txt = "todos los días" if not dias or len(dias) == 7 else ", ".join(DIAS[d] for d in sorted(dias))
    return f"{txt} a las {c.get('hora', '08:00')}"


def listar():
    with _lock:
        ts = _load()
    for t in ts:
        t["descripcion"] = describe(t)
    return ts


def crear(nombre, instruccion, cuando, proyecto=None, modelo=None, autonomo=True, misma_conv=False, recuperar=True, id=None):
    with _lock:
        ts = _load()
        t = next((x for x in ts if x["id"] == id), None) if id else None
        if not t:
            t = {"id": uuid.uuid4().hex[:10], "creada": time.time(), "ultima": None, "historial": [], "activa": True}
            ts.append(t)
        t.update({"nombre": (nombre or instruccion[:40]).strip(), "instruccion": instruccion.strip(), "cuando": cuando,
                  "proyecto": proyecto or None, "modelo": modelo or None, "autonomo": bool(autonomo),
                  "misma_conv": bool(misma_conv), "recuperar": bool(recuperar)})
        t["proxima"] = next_run(t)
        if t["proxima"] is None or t["proxima"] < time.time() - 60:
            raise ValueError("La fecha/hora ya pasó o no es válida (usa AAAA-MM-DDTHH:MM en el futuro).")
        _save(ts)
        return t


def eliminar(tid):
    with _lock:
        ts = [t for t in _load() if t["id"] != tid]
        _save(ts)


def activar(tid, on):
    with _lock:
        ts = _load()
        for t in ts:
            if t["id"] == tid:
                t["activa"] = bool(on)
                t["proxima"] = next_run(t) if on else None
        _save(ts)


def _mark(tid, result, conv_id=None):
    with _lock:
        ts = _load()
        for t in ts:
            if t["id"] == tid:
                t["ultima"] = time.time()
                if conv_id:
                    t["conv_id"] = conv_id
                t["historial"] = (t.get("historial") or [])[-19:] + [{"t": time.time(), "resultado": result, "conv": conv_id}]
                t["proxima"] = next_run(t)
                if t["proxima"] is None:
                    t["activa"] = False
        _save(ts)


def ejecutar_ahora(tid):
    t = next((x for x in _load() if x["id"] == tid), None)
    if not t or not _runner:
        return "no encontrada"
    try:
        cid = _runner(t)
        _mark(tid, "iniciada" if cid else "ocupada", cid)
        return cid or "ocupada"
    except Exception as e:
        _mark(tid, f"error: {e}")
        return f"error: {e}"


def _loop():
    first = True
    while True:
        try:
            now = time.time()
            for t in _load():
                if not t.get("activa") or not t.get("proxima"):
                    continue
                due = t["proxima"] <= now
                missed = first and due and now - t["proxima"] > 120
                if due and (not missed or t.get("recuperar", True)):
                    ejecutar_ahora(t["id"])
                elif missed:
                    _mark(t["id"], "omitida (PC apagado)")
            first = False
        except Exception:
            pass
        time.sleep(20)


def iniciar(runner):
    """runner(tarea) → id de la conversación iniciada (o None si estaba ocupada)."""
    global _runner
    if _runner:
        return
    _runner = runner
    threading.Thread(target=_loop, daemon=True, name="programador").start()


def tool(a, ctx):
    """Herramienta para la IA: programar_tarea."""
    acc = (a.get("accion") or "listar").lower()
    try:
        if acc == "listar":
            ts = listar()
            if not ts:
                return "No hay tareas programadas."
            return "\n".join(f"- [{t['id']}] {t['nombre']}: {t['descripcion']} · {'activa' if t.get('activa') else 'pausada'}"
                             + (f" · próxima {datetime.fromtimestamp(t['proxima']):%Y-%m-%d %H:%M}" if t.get("proxima") else "")
                             for t in ts)
        if acc == "eliminar":
            eliminar(a.get("id", ""))
            return f"Tarea {a.get('id')} eliminada."
        if acc in ("pausar", "reanudar"):
            activar(a.get("id", ""), acc == "reanudar")
            return f"Tarea {a.get('id')} {'reanudada' if acc == 'reanudar' else 'pausada'}."
        if acc == "crear":
            tipo = a.get("tipo") or ("una_vez" if a.get("fecha") else "diario")
            cuando = {"tipo": tipo}
            if tipo == "una_vez":
                cuando["fecha"] = a.get("fecha")
            elif tipo == "intervalo":
                cuando["cada_min"] = int(a.get("cada_min") or 60)
            else:
                cuando["hora"] = a.get("hora") or "08:00"
                if a.get("dias"):
                    cuando["dias"] = [int(x) for x in a["dias"]]
            t = crear(a.get("nombre"), a.get("instruccion") or "", cuando, a.get("proyecto") or ctx.conv.get("project"),
                      ctx.conv.get("model"), autonomo=a.get("autonomo", True))
            return (f"✔ Tarea programada [{t['id']}] «{t['nombre']}»: {describe(t)}. Próxima: "
                    f"{datetime.fromtimestamp(t['proxima']):%Y-%m-%d %H:%M}. (Se ejecuta mientras Noviark esté abierto; "
                    "el usuario la ve en 🖥 PC y tareas.)")
        return "ERROR: accion debe ser crear, listar, eliminar, pausar o reanudar."
    except Exception as e:
        return f"ERROR: {e}"


TOOL_DEF = {"type": "function", "function": {
    "name": "programar_tarea",
    "description": "Programa un trabajo para que Noviark lo haga solo más tarde o de forma repetida (una vez, diario, ciertos días o cada N minutos). También lista, pausa, reanuda o elimina tareas programadas.",
    "parameters": {"type": "object", "properties": {
        "accion": {"type": "string", "enum": ["crear", "listar", "eliminar", "pausar", "reanudar"]},
        "nombre": {"type": "string"}, "instruccion": {"type": "string", "description": "Qué debe hacer la IA cuando se ejecute (instrucción completa)"},
        "tipo": {"type": "string", "enum": ["una_vez", "diario", "semanal", "intervalo"]},
        "fecha": {"type": "string", "description": "Para una_vez: AAAA-MM-DDTHH:MM (hora local)"},
        "hora": {"type": "string", "description": "Para diario/semanal: HH:MM"},
        "dias": {"type": "array", "items": {"type": "integer"}, "description": "0=lunes … 6=domingo"},
        "cada_min": {"type": "integer"}, "proyecto": {"type": "string"}, "id": {"type": "string"},
        "autonomo": {"type": "boolean", "description": "Ejecutar sin pedir permisos (por defecto true)"}},
        "required": ["accion"]}}}
