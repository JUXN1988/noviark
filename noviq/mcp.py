# -*- coding: utf-8 -*-
"""Cliente MCP (Model Context Protocol) por stdio, compatible con el formato de Claude Desktop:

datos/mcp.json
{
  "mcpServers": {
    "filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:/Users/yo/Desktop"]},
    "otro": {"command": "uvx", "args": ["mcp-server-fetch"], "env": {"CLAVE": "valor"}}
  }
}
Soporta servidores modernos (2026-07-28, sin handshake) y clásicos (initialize).
"""
import json
import os
import queue
import re
import shutil
import subprocess
import threading

from .config import IS_WINDOWS, MCP_FILE, NO_WINDOW

MODERN = "2026-07-28"
LEGACY = "2025-06-18"
CLIENT_INFO = {"name": "Noviark", "version": "4.0"}

EXAMPLE = {
    "mcpServers": {
        "_ejemplo_desactivado_filesystem": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:/Users/TU_USUARIO/Desktop"],
            "disabled": True
        }
    }
}


# Servidores listos para activar con un clic (requieren Node.js 18+)
PRESETS = {
    "navegador_chrome": {"command": "npx", "args": ["-y", "@playwright/mcp@latest", "--browser", "chrome"]},
    "navegador_edge": {"command": "npx", "args": ["-y", "@playwright/mcp@latest", "--browser", "msedge"]},
    # Windows-MCP (CursorTouch): controla el escritorio de Windows con el mismo esquema que el navegador:
    # Snapshot (lee la ventana y sus elementos) → Click/Type/Shortcut → verificar. Se instala solo con uvx.
    "control_pc": {"command": "uvx", "args": ["windows-mcp", "serve"],
                   "env": {"WINDOWS_MCP_EXCLUDE_TOOLS": "PowerShell,Registry,FileSystem", "ANONYMIZED_TELEMETRY": "false",
                           "WINDOWS_MCP_SCREENSHOT_SCALE": "0.5"}},
}
PC_SERVERS = {"control_pc"}  # sus herramientas se delegan al agente del PC (no se envían en cada mensaje)


class MCPError(Exception):
    pass


class MCPServer:
    def __init__(self, name, cfg):
        self.name, self.cfg = name, cfg
        self.proc = None
        self.tools = []
        self.status = "detenido"
        self.error = ""
        self.modern = False
        self.version = LEGACY
        self._id = 0
        self._pending = {}
        self._lock = threading.Lock()
        self.stderr_tail = []

    # ── transporte ──
    def _cmd(self):
        cmd = self.cfg.get("command", "")
        exe = shutil.which(cmd) or cmd
        args = [str(a) for a in self.cfg.get("args", [])]
        if IS_WINDOWS and exe.lower().endswith((".cmd", ".bat")):
            return ["cmd", "/c", exe] + args
        return [exe] + args

    def start(self):
        self.status, self.error = "iniciando", ""
        env = dict(os.environ)
        env.update({k: str(v) for k, v in (self.cfg.get("env") or {}).items()})
        try:
            self.proc = subprocess.Popen(self._cmd(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, env=env, cwd=self.cfg.get("cwd") or None,
                                         creationflags=NO_WINDOW)
        except Exception as e:
            self.status, self.error = "error", f"No se pudo iniciar '{self.cfg.get('command')}': {e}"
            return
        threading.Thread(target=self._read_out, daemon=True).start()
        threading.Thread(target=self._read_err, daemon=True).start()
        try:
            self._handshake()
            self.tools = self._list_tools()
            self.status = "conectado"
        except Exception as e:
            self.status = "error"
            self.error = f"{e} {' | '.join(self.stderr_tail[-3:])}"[:600]

    def _read_out(self):
        for raw in iter(self.proc.stdout.readline, b""):
            try:
                msg = json.loads(raw.decode("utf-8"))
            except Exception:
                continue
            if "id" in msg and ("result" in msg or "error" in msg):
                q = self._pending.pop(msg["id"], None)
                if q:
                    q.put(msg)
        self.status = "detenido" if self.status != "error" else self.status
        for q in list(self._pending.values()):
            q.put({"error": {"code": -1, "message": "el servidor MCP se cerró"}})

    def _read_err(self):
        for raw in iter(self.proc.stderr.readline, b""):
            self.stderr_tail = (self.stderr_tail + [raw.decode("utf-8", "replace").strip()])[-20:]

    def _send(self, obj):
        with self._lock:
            self.proc.stdin.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
            self.proc.stdin.flush()

    def request(self, method, params=None, timeout=60, meta=True):
        if not self.proc or self.proc.poll() is not None:
            raise MCPError("el servidor no está en ejecución")
        self._id += 1
        rid = self._id
        params = dict(params or {})
        if self.modern and meta:
            params["_meta"] = {**params.get("_meta", {}),
                               "io.modelcontextprotocol/protocolVersion": self.version,
                               "io.modelcontextprotocol/clientInfo": CLIENT_INFO,
                               "io.modelcontextprotocol/clientCapabilities": {}}
        q = queue.Queue()
        self._pending[rid] = q
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        try:
            msg = q.get(timeout=timeout)
        except queue.Empty:
            self._pending.pop(rid, None)
            try:
                self._send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": rid}})
            except Exception:
                pass
            raise MCPError(f"tiempo agotado esperando '{method}'")
        if "error" in msg:
            e = msg["error"]
            err = MCPError(f"{e.get('message')} (código {e.get('code')})")
            err.code, err.data = e.get("code"), e.get("data")
            raise err
        return msg.get("result") or {}

    # ── ciclo de vida ──
    def _handshake(self):
        # 1) sondeo moderno
        self.modern, self.version = True, MODERN
        try:
            res = self.request("server/discover", {}, timeout=6)
            vers = res.get("supportedVersions") or [MODERN]
            self.version = MODERN if MODERN in vers else vers[0]
            return
        except MCPError as e:
            if getattr(e, "code", None) == -32022:  # moderno pero otra versión
                sup = (getattr(e, "data", None) or {}).get("supported") or []
                if sup:
                    self.version = sup[0]
                    return
        # 2) servidor clásico → initialize
        self.modern, self.version = False, LEGACY
        res = self.request("initialize", {"protocolVersion": LEGACY, "capabilities": {},
                                          "clientInfo": CLIENT_INFO},
                                         timeout=240 if self.cfg.get("command") in ("uvx", "npx") else 60)
        self.version = res.get("protocolVersion", LEGACY)
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _list_tools(self):
        tools, cursor = [], None
        for _ in range(20):
            res = self.request("tools/list", {"cursor": cursor} if cursor else {}, timeout=30)
            tools += res.get("tools", [])
            cursor = res.get("nextCursor")
            if not cursor:
                break
        return tools

    def call(self, tool, args, timeout=300):
        res = self.request("tools/call", {"name": tool, "arguments": args or {}}, timeout=timeout)
        if res.get("resultType") == "input_required":
            return {"text": "ERROR: el servidor MCP pidió datos adicionales (no soportado todavía).", "images": []}
        texts, images = [], []
        for c in res.get("content", []):
            t = c.get("type")
            if t == "text":
                texts.append(c.get("text", ""))
            elif t == "image" and c.get("data"):
                images.append(f"data:{c.get('mimeType', 'image/png')};base64,{c['data']}")
            elif t == "resource":
                r = c.get("resource", {})
                texts.append(r.get("text") or f"[recurso {r.get('uri')}]")
            else:
                texts.append(json.dumps(c, ensure_ascii=False)[:2000])
        if res.get("structuredContent") and not texts:
            texts.append(json.dumps(res["structuredContent"], ensure_ascii=False, indent=1))
        text = "\n".join(texts) or "(sin contenido)"
        if res.get("isError"):
            text = "ERROR: " + text
        return {"text": text, "images": images}

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=3)
            except Exception:
                self.proc.kill()
        self.status = "detenido"


def _safe(s):
    return re.sub(r"[^a-zA-Z0-9_-]", "_", s)


class MCPManager:
    def __init__(self):
        self.servers = {}

    def load_config_text(self):
        if not MCP_FILE.exists():
            MCP_FILE.write_text(json.dumps(EXAMPLE, indent=2, ensure_ascii=False), encoding="utf-8")
        return MCP_FILE.read_text(encoding="utf-8")

    def save_config_text(self, text):
        json.loads(text)  # valida
        MCP_FILE.write_text(text, encoding="utf-8")

    def reload(self):
        for s in self.servers.values():
            s.stop()
        self.servers = {}
        try:
            cfg = json.loads(self.load_config_text()).get("mcpServers", {})
        except Exception as e:
            self.servers["_config"] = type("X", (), {"status": "error", "error": f"mcp.json inválido: {e}",
                                                      "tools": [], "stop": lambda s: None})()
            return
        for name, c in cfg.items():
            if c.get("disabled") or not c.get("command"):
                continue
            s = MCPServer(name, c)
            self.servers[name] = s
            threading.Thread(target=s.start, daemon=True).start()

    def status(self):
        return [{"name": n, "status": s.status, "error": s.error, "tools": [t.get("name") for t in s.tools]}
                for n, s in self.servers.items()]

    def tool_defs(self, include_browser=None):
        """Herramientas MCP. Las del navegador (browser_*) se delegan al subagente navegador salvo que
        la configuración pida exponerlas directamente (ahorra muchos tokens por mensaje)."""
        from .config import CONFIG
        if include_browser is None:
            include_browser = bool(CONFIG.get("navegador_directo"))
        out, self._map = [], getattr(self, "_map", {})
        for n, s in self.servers.items():
            if getattr(s, "status", "") != "conectado":
                continue
            for t in s.tools:
                if n in PC_SERVERS and not include_browser:
                    fname = f"mcp__{_safe(n)}__{_safe(t['name'])}"[:64]
                    self._map[fname] = (n, t["name"])
                    continue
                if not include_browser and t["name"].startswith("browser_"):
                    fname = f"mcp__{_safe(n)}__{_safe(t['name'])}"[:64]
                    self._map[fname] = (n, t["name"])
                    continue
                fname = f"mcp__{_safe(n)}__{_safe(t['name'])}"[:64]
                self._map[fname] = (n, t["name"])
                schema = t.get("inputSchema") or {"type": "object", "properties": {}}
                schema = {k: v for k, v in schema.items() if k != "$schema"}
                out.append({"type": "function", "function": {
                    "name": fname, "description": f"[MCP {n}] " + (t.get("description") or t["name"])[:900],
                    "parameters": schema}})
        return out

    def has_browser(self):
        return any(getattr(s, "status", "") == "conectado" and any(t["name"].startswith("browser_") for t in s.tools)
                   for s in self.servers.values())

    def has_pc(self):
        return any(n in PC_SERVERS and getattr(s, "status", "") == "conectado" for n, s in self.servers.items())

    def pc_tools(self):
        self.tool_defs(include_browser=True)
        out = []
        for n, s in self.servers.items():
            if n in PC_SERVERS and getattr(s, "status", "") == "conectado":
                for t in s.tools:
                    schema = {k: v for k, v in (t.get("inputSchema") or {"type": "object", "properties": {}}).items() if k != "$schema"}
                    out.append({"type": "function", "function": {"name": f"mcp__{_safe(n)}__{_safe(t['name'])}"[:64],
                                                                  "description": (t.get("description") or t["name"])[:700],
                                                                  "parameters": schema}})
        return out

    def add_preset(self, key):
        from .config import DATA_DIR
        cfg = json.loads(self.load_config_text())
        work = DATA_DIR / "navegador"
        work.mkdir(exist_ok=True)
        cfg.setdefault("mcpServers", {})[key] = dict(PRESETS[key], cwd=str(work))
        self.save_config_text(json.dumps(cfg, indent=2, ensure_ascii=False))
        self.reload()

    def call(self, fname, args):
        if not hasattr(self, "_map") or fname not in self._map:
            self.tool_defs(include_browser=True)
        if fname not in self._map:
            return f"ERROR: herramienta MCP desconocida {fname}"
        server, tool = self._map[fname]
        return self.servers[server].call(tool, args)


MANAGER = MCPManager()
