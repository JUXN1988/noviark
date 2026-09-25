# -*- coding: utf-8 -*-
"""Configuración, rutas y utilidades compartidas."""
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
from pathlib import Path

VERSION = "4.2.0"
# Empaquetado (PyInstaller): los archivos del programa van en _MEIPASS y los datos del usuario en su carpeta personal
FROZEN = bool(getattr(sys, "frozen", False))


def user_data_dir():
    if os.environ.get("NOVIQ_DATOS"):
        return Path(os.environ["NOVIQ_DATOS"]).expanduser()
    if platform.system() == "Windows":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Noviark"
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Noviark"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "Noviark"


if FROZEN:
    BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    DATA_DIR = user_data_dir()
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    DATA_DIR = Path(os.environ["NOVIQ_DATOS"]).expanduser() if os.environ.get("NOVIQ_DATOS") else BASE_DIR / "datos"
CONV_DIR = DATA_DIR / "conversaciones"
CONFIG_FILE = DATA_DIR / "config.json"
MEMORY_FILE = DATA_DIR / "memoria.md"
MCP_FILE = DATA_DIR / "mcp.json"
for d in (DATA_DIR, CONV_DIR):
    d.mkdir(parents=True, exist_ok=True)

IS_WINDOWS = platform.system() == "Windows"

_py_cache = []


def python_exe():
    """Python con el que se ejecuta el código de los proyectos. En el programa instalado (.exe/.app) no se puede usar
    el propio ejecutable de Noviark: se busca el Python del sistema. Devuelve None si no hay ninguno."""
    if not FROZEN:
        return sys.executable
    if _py_cache:
        return _py_cache[0]
    cands = []
    if shutil.which("py"):
        try:
            r = subprocess.run(["py", "-3", "-c", "import sys;print(sys.executable)"], capture_output=True, text=True, timeout=20,
                               creationflags=0x08000000 if platform.system() == "Windows" else 0)
            if r.returncode == 0 and r.stdout.strip():
                cands.append(r.stdout.strip())
        except Exception:
            pass
    for n in ("python3", "python"):
        w = shutil.which(n)
        if w and "WindowsApps" not in w:  # el «python» de la Tienda de Windows solo abre la tienda
            cands.append(w)
    res = next((c for c in cands if Path(c).exists()), None)
    if res:
        _py_cache.append(res)
    return res
OS_NAME = "Windows" if IS_WINDOWS else platform.system()
NO_WINDOW = 0x08000000 if IS_WINDOWS else 0

# Proveedores compatibles con la API de OpenAI (chat/completions). Las claves van en la bóveda cifrada.
DEFAULT_PROVIDERS = {
    "nvidia": {"name": "NVIDIA", "base_url": "https://integrate.api.nvidia.com/v1", "enabled": True,
               "context_chars": 400000, "web": "https://build.nvidia.com/models"},
    "ollama": {"name": "Ollama (local)", "base_url": "http://localhost:11434/v1", "enabled": True, "local": True,
               "context_chars": 60000, "web": "https://ollama.com/download"},
    "lmstudio": {"name": "LM Studio (local)", "base_url": "http://localhost:1234/v1", "enabled": True, "local": True,
                 "context_chars": 60000, "web": "https://lmstudio.ai"},
    "gemini": {"name": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
               "enabled": False, "context_chars": 600000, "web": "https://aistudio.google.com/apikey"},
    "openai": {"name": "OpenAI", "base_url": "https://api.openai.com/v1", "enabled": False,
               "context_chars": 300000, "web": "https://platform.openai.com/api-keys"},
    "anthropic": {"name": "Anthropic (Claude)", "base_url": "https://api.anthropic.com/v1", "enabled": False,
                  "context_chars": 500000, "max_temp": 1.0, "anthropic_headers": True,
                  "web": "https://console.anthropic.com/settings/keys"},
    "openrouter": {"name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "enabled": False,
                   "context_chars": 300000, "web": "https://openrouter.ai/keys", "solo_gratis": True},
    "groq": {"name": "Groq", "base_url": "https://api.groq.com/openai/v1", "enabled": False,
             "context_chars": 100000, "web": "https://console.groq.com/keys"},
    "deepseek": {"name": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "enabled": False,
                 "context_chars": 200000, "web": "https://platform.deepseek.com/api_keys"},
    "mistral": {"name": "Mistral", "base_url": "https://api.mistral.ai/v1", "enabled": False,
                "context_chars": 200000, "web": "https://console.mistral.ai/api-keys"},
    "xai": {"name": "xAI (Grok)", "base_url": "https://api.x.ai/v1", "enabled": False,
            "context_chars": 300000, "web": "https://console.x.ai"},
    "cerebras": {"name": "Cerebras", "base_url": "https://api.cerebras.ai/v1", "enabled": False,
                 "context_chars": 120000, "web": "https://cloud.cerebras.ai/"},
    "huggingface": {"name": "Hugging Face", "base_url": "https://router.huggingface.co/v1", "enabled": False,
                    "context_chars": 120000, "web": "https://huggingface.co/settings/tokens"},
    # ── Gratis SIN cuenta ni clave (anónimos, con límites bajos) ──
    "kilo": {"name": "Kilo Gateway (sin cuenta)", "base_url": "https://api.kilo.ai/api/gateway", "enabled": False,
             "context_chars": 200000, "web": "https://kilo.ai", "anonimo": True, "solo_gratis": True},
    "llm7": {"name": "LLM7 (sin cuenta)", "base_url": "https://api.llm7.io/v1", "enabled": False, "context_chars": 200000,
             "web": "https://token.llm7.io", "anonimo": True, "clave_anonima": "unused"},
    "ovh": {"name": "OVHcloud AI Endpoints (sin cuenta)", "base_url": "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1",
            "enabled": False, "context_chars": 100000, "web": "https://endpoints.ai.cloud.ovh.net", "anonimo": True},
    # ── Gratis con cuenta (sin tarjeta) ──
    "zai": {"name": "Z.ai (GLM Flash gratis)", "base_url": "https://api.z.ai/api/paas/v4", "enabled": False,
            "context_chars": 200000, "web": "https://z.ai/manage-apikey/apikey-list", "filtro_gratis": "flash"},
    "cohere": {"name": "Cohere", "base_url": "https://api.cohere.ai/compatibility/v1", "enabled": False,
               "context_chars": 200000, "web": "https://dashboard.cohere.com/api-keys",
               "modelos_fijos": ["command-a-03-2025", "command-a-reasoning-08-2025", "command-a-vision-07-2025", "command-r-plus-08-2024"]},
    "cloudflare": {"name": "Cloudflare Workers AI", "base_url": "https://api.cloudflare.com/client/v4/accounts/{cuenta}/ai/v1",
                   "enabled": False, "context_chars": 100000, "web": "https://dash.cloudflare.com/profile/api-tokens",
                   "necesita_cuenta": True, "modelos_fijos": ["@cf/openai/gpt-oss-120b", "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
                                                                "@cf/qwen/qwen3-30b-a3b-fp8", "@cf/moonshotai/kimi-k2-instruct",
                                                                "@cf/zai-org/glm-4.7-flash", "@cf/google/gemma-3-12b-it"]},
    "aion": {"name": "Aion Labs", "base_url": "https://api.aionlabs.ai/v1", "enabled": False, "context_chars": 100000,
             "web": "https://platform.aionlabs.ai"},
    "pollinations": {"name": "Pollinations", "base_url": "https://gen.pollinations.ai/v1", "enabled": False,
                     "context_chars": 100000, "web": "https://enter.pollinations.ai"},
    "ollamacloud": {"name": "Ollama Cloud", "base_url": "https://ollama.com/v1", "enabled": False, "context_chars": 200000,
                    "web": "https://ollama.com/settings/keys"},
    "vercel": {"name": "Vercel AI Gateway", "base_url": "https://ai-gateway.vercel.sh/v1", "enabled": False,
               "context_chars": 200000, "web": "https://vercel.com/d?to=%2F%5Bteam%5D%2F%7E%2Fai%2Fapi-keys"},
    "custom": {"name": "Otro (compatible OpenAI)", "base_url": "", "enabled": False, "context_chars": 200000},
    "remoto": {"name": "Servidor GPU en la nube (Kaggle)", "base_url": "", "enabled": False, "context_chars": 100000,
               "web": "https://www.kaggle.com/code", "remoto": True},
    # No es de chat: decisiones rápidas tipadas (System One). Lo usa el decisor de Noviark si tiene clave.
    "typesafe": {"name": "TypeSafe Jev (decisiones)", "base_url": "https://api.typesafe.ai/v1", "enabled": False,
                 "decisor": True, "web": "https://typesafe.ai", "modelo": "jev-latest"},
}

DEFAULT_CONFIG = {
    "providers": DEFAULT_PROVIDERS,
    "model": "nvidia::z-ai/glm-5.3-flash",
    "image_model": "black-forest-labs/flux.1-schnell",
    "projects_dir": "",               # vacío = Documentos\Noviq_Proyectos
    "permission_mode": "preguntar",   # preguntar | auto_seguro | auto
    "tool_mode": "auto",              # auto | nativo | texto | ninguno
    "temperature": 0.6,
    "top_p": 0.95,
    "max_tokens": 16384,
    "reasoning_effort": "",
    "max_steps": 40,
    "system_prompt": "",
    "model_overrides": {},            # "prov::modelo": {"tool_mode": "texto", "no_system": true, ...}
    "fallback_enabled": True,         # si una IA falla, continúa con la siguiente
    "fallback_models": [],            # orden de respaldo, ej. ["gemini::gemini-3.8-flash", "ollama::qwen3:8b"]
    "read_timeout": 240,
    "fallback_rounds": 3,
    "ejecutor": "auto",               # agente ejecutor de bloques de código: auto | siempre | nunca
    "modelo_vision": "",              # modelo que analiza imágenes si el principal no ve ("" = automático)
    "modelo_auxiliar": "",            # modelo para subagentes (navegador) ("" = automático)
    "navegador_directo": False,
    "equipo_max": 3,
    "vanguardia": {"activo": False, "planificar": True},
    "modelo_cerebro": "auto",
    "respaldo_auto": True,
    "verificar_modelos": True,        # agente verificador: prueba en segundo plano qué modelos responden
    "solo_operativos": True,          # la lista de modelos oculta los que no funcionan
    "revisar_plan_seg": 30,           # segundos para revisar/editar el plan antes de aprobarlo solo (0 = no esperar)
    "local": {"vram_gb": 16, "ram_gb": 32, "num_ctx": 0, "max_ctx": 32768, "kv_q8": False, "ollama_nativo": True,
              "modo_compacto": "auto", "pensar": "auto", "keep_alive": "30m", "max_steps": 150},
    "pruebas_auto": True,             # agente de pruebas tras cada cambio de código
    "diagnostico_auto": True,         # si el usuario dice que algo no funciona, diagnostica el proyecto antes de que la IA empiece
    # guardián: corta el razonamiento eterno (caracteres/segundos pensando sin actuar) y los bucles de texto repetido
    "guardian": {"activo": True, "max_razonamiento": 16000, "max_seg_razonamiento": 150, "repeticion": True},
    # escalador: si la IA se atasca, pasa el trabajo a la IA más capaz habilitada y con cuota
    "escalado": {"activo": True, "umbral": 5, "max_escalados": 2, "permitir_pago": True},
    "proyectos_externos": {},         # nombre -> carpeta de proyectos que ya existían en la PC                  # agentes en paralelo en planificar_en_equipo / trabajar_en_equipo       # True = la IA principal recibe todas las herramientas del navegador             # si ninguna IA responde, reintenta la cadena completa N veces              # segundos sin recibir datos = la IA no responde
}

_lock = threading.RLock()


def _merge(base, extra):
    out = dict(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


CONFIG_VERSION = 4


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if CONFIG_FILE.exists():
        try:
            cfg = _merge(cfg, json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    if cfg.get("config_version", 0) < CONFIG_VERSION:
        # v2.1: más tokens por respuesta (los modelos con razonamiento se cortaban antes de actuar)
        cfg["max_tokens"] = max(int(cfg.get("max_tokens") or 0), 16384)
        if cfg.get("config_version", 0) < 4:
            # v4: un error 404 «Function not found» se confundía con «no acepta herramientas»; se reaprende
            for ov in (cfg.get("model_overrides") or {}).values():
                if ov.get("tool_mode") == "texto":
                    ov.pop("tool_mode")
        cfg["config_version"] = CONFIG_VERSION
    return cfg


def migrate_keys(cfg):
    """Mueve las claves que estuvieran en texto plano a la bóveda cifrada."""
    from . import vault
    changed = False
    for pid, p in cfg["providers"].items():
        keys = p.pop("api_keys", None)
        if keys:
            real = [k for k in keys if k and k not in ("ollama", "lm-studio", "sin-clave") and "…" not in k]
            if real:
                vault.set_keys(pid, list(dict.fromkeys(vault.get_keys(pid) + real)))
            changed = True
    old = BASE_DIR / "config.json"  # versión 1
    if old.exists():
        try:
            o = json.loads(old.read_text(encoding="utf-8"))
            if o.get("api_key") and not vault.get_keys("nvidia"):
                vault.set_keys("nvidia", [o["api_key"]])
            old.rename(old.with_suffix(".json.v1_migrado"))
        except Exception:
            pass
    env_key = os.environ.get("NVIDIA_API_KEY")
    if env_key and not vault.get_keys("nvidia"):
        vault.set_keys("nvidia", [env_key])
    return changed


CONFIG = load_config()
if migrate_keys(CONFIG):
    CONFIG_FILE.write_text(json.dumps(CONFIG, indent=2, ensure_ascii=False), encoding="utf-8")


def save_config():
    with _lock:
        CONFIG_FILE.write_text(json.dumps(CONFIG, indent=2, ensure_ascii=False), encoding="utf-8")


def model_override(model_id):
    return CONFIG.setdefault("model_overrides", {}).setdefault(model_id, {})


def set_override(model_id, key, value):
    with _lock:
        model_override(model_id)[key] = value
        save_config()


# ───────────── Carpeta Documentos real (incluye OneDrive redirigido) ─────────────
_documents = None


def documents_dir() -> Path:
    global _documents
    if _documents:
        return _documents
    p = None
    if IS_WINDOWS:
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command",
                                "[Environment]::GetFolderPath('MyDocuments')"],
                               capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW)
            if r.stdout.strip():
                p = Path(r.stdout.strip())
        except Exception:
            pass
    if not p:
        p = Path.home() / "Documents"
        if not p.exists() and (Path.home() / "Documentos").exists():
            p = Path.home() / "Documentos"
    _documents = p
    return p


def projects_root() -> Path:
    raw = (CONFIG.get("projects_dir") or "").strip()
    if raw:
        p = Path(os.path.expandvars(os.path.expanduser(raw)))
    else:
        p = documents_dir() / "Noviq_Proyectos"
        if not p.exists():
            for oldname in ("Rurak_Proyectos", "NVIDIA_Chat_Proyectos"):  # carpetas de versiones anteriores
                old = documents_dir() / oldname
                if old.exists():
                    try:
                        old.rename(p)
                    except OSError:
                        p = old
                    break
    p.mkdir(parents=True, exist_ok=True)
    return p


META_DIR, META_FILE = ".noviq", ".noviq.json"


def project_path(name) -> Path:
    """Carpeta de un proyecto: los externos (ya existentes en la PC) o los de la carpeta de proyectos."""
    ext = (CONFIG.get("proyectos_externos") or {}).get(name)
    if ext:
        return Path(ext)
    return projects_root() / name


def all_roots():
    """Carpetas donde la IA puede escribir sin pedir permiso (proyectos propios y externos)."""
    return [projects_root()] + [Path(p) for p in (CONFIG.get("proyectos_externos") or {}).values()]


def meta_dir(project, create=True):
    """Carpeta oculta del proyecto (memoria, bitácora, ESTADO.md, respaldos)."""
    base = project_path(project)
    new = base / META_DIR
    for old in (base / ".rurak", base / ".nvchat"):
        if old.exists() and not new.exists():
            try:
                old.rename(new)
            except OSError:
                return old
    if create and base.exists():
        new.mkdir(exist_ok=True)
    return new


def meta_file(project):
    base = project_path(project)
    new = base / META_FILE
    for old in (base / ".rurak.json", base / ".nvchat.json"):
        if old.exists() and not new.exists():
            try:
                old.rename(new)
            except OSError:
                return old
    return new


def general_dir() -> Path:
    """Carpeta para conversaciones sin proyecto."""
    p = projects_root() / "_General"
    p.mkdir(parents=True, exist_ok=True)
    return p


def powershell_exe():
    if IS_WINDOWS:
        # PowerShell 7 (pwsh) si el usuario lo pide; si no, Windows PowerShell 5.1 (siempre instalado)
        if os.environ.get("NVCHAT_USE_PWSH") and shutil.which("pwsh"):
            return "pwsh"
        return "powershell"
    return shutil.which("pwsh")
