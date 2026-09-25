# -*- coding: utf-8 -*-
"""IA gratis (de forma legal): proveedores con planes gratuitos oficiales y conexión con un clic a OpenRouter
(OAuth PKCE oficial: el usuario inicia sesión en la web de OpenRouter y Noviark recibe su clave automáticamente)."""
import base64
import hashlib
import secrets
import time

import requests

# Datos orientativos: los límites gratuitos los fija cada proveedor y pueden cambiar.
GRATIS = [
    # ── 1. Sin cuenta: se activan con un clic, sin clave (límites bajos, ideales como respaldo) ──
    {"id": "kilo", "nombre": "Kilo Gateway", "icono": "🪁", "sin_cuenta": True, "grupo": "Sin cuenta ni clave",
     "gratis": "Modelos «:free» (GLM-5, MiniMax, Nemotron…) SIN cuenta ni clave; ~200 peticiones/hora por PC.",
     "clave_url": "https://kilo.ai"},
    {"id": "llm7", "nombre": "LLM7", "icono": "7️⃣", "sin_cuenta": True, "grupo": "Sin cuenta ni clave",
     "gratis": "GPT-OSS 120B, Gemma 4, MiniMax, Codestral SIN cuenta (~10 peticiones/min). Con token gratis (sin tarjeta) sube a 40/min.",
     "clave_url": "https://token.llm7.io"},
    {"id": "ovh", "nombre": "OVHcloud AI Endpoints", "icono": "☁", "sin_cuenta": True, "grupo": "Sin cuenta ni clave",
     "gratis": "Modelos abiertos (Llama 3.3 70B, Qwen…) sin cuenta, muy limitado (~2 peticiones/min por modelo): solo como último respaldo.",
     "clave_url": "https://endpoints.ai.cloud.ovh.net"},
    # ── 2. Con cuenta gratuita (sin tarjeta) ──
    {"id": "openrouter", "nombre": "OpenRouter", "icono": "🔀", "un_clic": True, "grupo": "Cuenta gratis, sin tarjeta",
     "gratis": "~20 modelos «:free» que van cambiando; ~20 peticiones/min y 50/día (1.000/día si alguna vez recargas 10 USD).",
     "clave_url": "https://openrouter.ai/keys"},
    {"id": "nvidia", "nombre": "NVIDIA build", "icono": "🟩", "grupo": "Cuenta gratis, sin tarjeta",
     "gratis": "Programa de desarrolladores: DeepSeek, Kimi, GLM, Qwen, Nemotron… (~40 peticiones/min). Pide verificar teléfono.",
     "clave_url": "https://build.nvidia.com/"},
    {"id": "gemini", "nombre": "Google Gemini (AI Studio)", "icono": "✨", "grupo": "Cuenta gratis, sin tarjeta",
     "gratis": "Gemini Flash y Gemma gratis (ven imágenes, contexto enorme) con límites diarios por modelo.",
     "clave_url": "https://aistudio.google.com/apikey"},
    {"id": "groq", "nombre": "Groq", "icono": "⚡", "grupo": "Cuenta gratis, sin tarjeta",
     "gratis": "Rapidísimo: GPT-OSS 120B/20B, Qwen… (~30 peticiones/min, ~1.000/día).",
     "clave_url": "https://console.groq.com/keys"},
    {"id": "zai", "nombre": "Z.ai (GLM Flash)", "icono": "🇿", "grupo": "Cuenta gratis, sin tarjeta",
     "gratis": "GLM-4.7-Flash, GLM-4.5-Flash y GLM-4.6V-Flash gratis (buenos para programar y agentes). Registro con correo.",
     "clave_url": "https://z.ai/manage-apikey/apikey-list"},
    {"id": "mistral", "nombre": "Mistral (plan Experiment)", "icono": "🌬", "grupo": "Cuenta gratis, sin tarjeta",
     "gratis": "Mistral Large/Medium/Small, Codestral y Devstral con cuota gratuita mensual. Pide teléfono.",
     "clave_url": "https://console.mistral.ai/api-keys"},
    {"id": "cloudflare", "nombre": "Cloudflare Workers AI", "icono": "🟧", "grupo": "Cuenta gratis, sin tarjeta", "pide_cuenta": True,
     "gratis": "10.000 «neurons» al día gratis: GPT-OSS 120B, Llama 3.3 70B, Qwen3, Kimi, GLM. Necesita la clave (API token) y el ID de cuenta.",
     "clave_url": "https://dash.cloudflare.com/profile/api-tokens"},
    {"id": "cohere", "nombre": "Cohere", "icono": "🟣", "grupo": "Cuenta gratis, sin tarjeta",
     "gratis": "Command A (incluye razonamiento y visión) — 1.000 llamadas al mes, uso no comercial.",
     "clave_url": "https://dashboard.cohere.com/api-keys"},
    {"id": "aion", "nombre": "Aion Labs", "icono": "🅰", "grupo": "Cuenta gratis, sin tarjeta",
     "gratis": "Plan gratuito (~15 peticiones/min, ~20 mil tokens/día).", "clave_url": "https://platform.aionlabs.ai"},
    {"id": "pollinations", "nombre": "Pollinations", "icono": "🌸", "grupo": "Cuenta gratis, sin tarjeta",
     "gratis": "Plataforma abierta: modelos de texto e imágenes con clave gratuita.", "clave_url": "https://enter.pollinations.ai"},
    {"id": "ollamacloud", "nombre": "Ollama Cloud", "icono": "🦙", "grupo": "Cuenta gratis, sin tarjeta",
     "gratis": "Modelos grandes en la nube de Ollama (gpt-oss, qwen3-coder, deepseek…) con límite por sesión/semana.",
     "clave_url": "https://ollama.com/settings/keys"},
    {"id": "huggingface", "nombre": "Hugging Face", "icono": "🤗", "grupo": "Cuenta gratis, sin tarjeta",
     "gratis": "Pequeño crédito mensual gratuito para modelos abiertos a través de su router.",
     "clave_url": "https://huggingface.co/settings/tokens/new?ownUserPermissions=inference.serverless.write&tokenType=fineGrained"},
    {"id": "vercel", "nombre": "Vercel AI Gateway", "icono": "▲", "grupo": "Cuenta gratis, sin tarjeta",
     "gratis": "Crédito gratuito mensual (~5 USD) para muchos modelos.", "clave_url": "https://vercel.com/ai-gateway"},
    {"id": "cerebras", "nombre": "Cerebras", "icono": "🧠", "grupo": "Cuenta gratis, sin tarjeta",
     "gratis": "Rapidísimo (GPT-OSS 120B, GLM). ⚠ Desde julio 2026 puede pedir tarjeta para la prueba: úsalo solo si tu cuenta ya tiene el plan gratis.",
     "clave_url": "https://cloud.cerebras.ai/"},
    # ── 3. Tu propio servidor con GPU gratis en la nube ──
    {"id": "remoto", "nombre": "Servidor GPU en la nube (Kaggle)", "icono": "🛰", "remoto": True, "grupo": "Tu servidor GPU gratis en la nube",
     "gratis": "Noviark te da un cuaderno listo: Kaggle pone 2 GPU T4 (32 GB, el doble que tu PC) gratis ~30 h/semana y la IA corre allá, "
               "no en tu PC. Sesiones de hasta 12 h; la URL cambia al reiniciar. Requiere cuenta de Kaggle verificada con teléfono.",
     "clave_url": "https://www.kaggle.com/code"},
    # ── 4. Decisiones rápidas (no es chat) ──
    {"id": "typesafe", "nombre": "Jev de TypeSafe (decisiones)", "icono": "⚖", "decisor": True, "grupo": "Decisiones rápidas (opcional)",
     "gratis": "Modelo «System One» (sept. 2026): no escribe, DECIDE (sí/no, elegir, puntuar) en ~0,1-0,5 s. Noviark lo usa para evaluar el "
               "riesgo de cada comando y decidir si un pedido necesita plan. De pago por uso pero muy barato (~0,04 USD por millón de "
               "tokens). Sin clave, Noviark decide con sus reglas locales (gratis).",
     "clave_url": "https://typesafe.ai"},
    # ── 5. En tu PC: ilimitado ──
    {"id": "ollama", "nombre": "Ollama (en tu PC)", "icono": "🦙", "local": True, "grupo": "En tu PC (ilimitado)",
     "gratis": "100 % gratis e ilimitado en tu PC. Con tu RTX 5060 16 GB: qwen3-coder:30b, gpt-oss:20b, qwen3-vl:4b.",
     "clave_url": "https://ollama.com/download"},
    {"id": "lmstudio", "nombre": "LM Studio (en tu PC)", "icono": "🧪", "local": True, "grupo": "En tu PC (ilimitado)",
     "gratis": "Gratis e ilimitado en tu PC, con interfaz para descargar modelos.",
     "clave_url": "https://lmstudio.ai/download"},
]

_pkce = {}  # state -> (verifier, t)


def openrouter_auth_url(port):
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(16)
    _pkce[state] = (verifier, time.time())
    cb = f"http://127.0.0.1:{port}/oauth/openrouter?state={state}"
    from urllib.parse import quote
    return (f"https://openrouter.ai/auth?callback_url={quote(cb, safe='')}&code_challenge={challenge}"
            f"&code_challenge_method=S256")


def openrouter_exchange(state, code):
    item = _pkce.pop(state, None)
    if not item or time.time() - item[1] > 900:
        raise ValueError("La conexión expiró; vuelve a pulsar «Conectar con un clic».")
    r = requests.post("https://openrouter.ai/api/v1/auth/keys",
                      json={"code": code, "code_verifier": item[0], "code_challenge_method": "S256"}, timeout=30)
    r.raise_for_status()
    key = r.json().get("key")
    if not key:
        raise ValueError("OpenRouter no devolvió una clave.")
    return key
