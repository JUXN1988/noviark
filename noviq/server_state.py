# -*- coding: utf-8 -*-
"""Guardado de conversaciones."""
import json
import re
import threading
import time

from .config import CONV_DIR

_lock = threading.Lock()


def conv_path(cid):
    return CONV_DIR / f"{re.sub(r'[^a-zA-Z0-9_-]', '', cid)}.json"


def new_conv(cid, project=None, model=None):
    return {"id": cid, "title": "Nueva conversación", "created": time.time(), "updated": time.time(),
            "project": project, "model": model, "messages": [], "display": [], "tasks": [], "allowed_tools": []}


def load_conv(cid):
    p = conv_path(cid)
    if p.exists():
        c = json.loads(p.read_text(encoding="utf-8"))
        c.setdefault("tasks", [])
        c.setdefault("allowed_tools", [])
        c.setdefault("project", None)
        return c
    return None


def save_conv(conv):
    conv["updated"] = time.time()
    with _lock:
        tmp = conv_path(conv["id"]).with_suffix(".tmp")
        tmp.write_text(json.dumps(conv, ensure_ascii=False), encoding="utf-8")
        tmp.replace(conv_path(conv["id"]))


def list_convs():
    out = []
    for p in CONV_DIR.glob("*.json"):
        try:
            c = json.loads(p.read_text(encoding="utf-8"))
            out.append({"id": c["id"], "title": c.get("title", ""), "updated": c.get("updated", 0),
                        "project": c.get("project"), "model": c.get("model")})
        except Exception:
            pass
    return sorted(out, key=lambda x: -x["updated"])
