# -*- coding: utf-8 -*-
"""Catálogo de modelos para ayudar a elegir: para qué sirve cada uno, qué tan bueno es programando,
su inteligencia, velocidad, consumo de tokens, si usa herramientas o ve imágenes, y si cabe en la GPU.
Las valoraciones (1-5) son orientativas y se basan en la familia del modelo."""
import re

from .config import CONFIG

# patrón → datos (se usa la primera coincidencia)
FAMILIAS = [
    (r"flux|ideogram|fooocus|stable-?diffusion|sdxl|dall-e|imagen|veo", dict(
        familia="Modelo de IMÁGENES", prog=0, intel=0, vel=0, tokens="—", tools=False, vision=False, chat=False,
        desc="No es un modelo de chat: genera imágenes. No sirve para conversar ni programar.")),
    (r"embed|rerank|bge|nomic", dict(familia="Modelo de embeddings", prog=0, intel=0, vel=0, tokens="—", tools=False,
                                     vision=False, chat=False, desc="Sirve para búsquedas semánticas, no para chatear.")),
    (r"kimi-k[3-9]", dict(familia="Kimi K3+ (Moonshot)", prog=5, intel=5, razona=5, vel=3, tokens="medio", tools=True, vision=True,
        desc="Generación más nueva de Kimi: de lo mejor en modelos abiertos para programar como agente, razonar y seguir "
        "planes largos con herramientas.", para=["programar", "agente", "planificar"])),
    (r"kimi-k2[\w.-]*think", dict(familia="Kimi K2 Thinking (Moonshot)", prog=5, intel=5, razona=5, vel=2, tokens="alto (piensa mucho)",
        tools=True, vision=False, desc="De lo más avanzado en modelos abiertos: razona a fondo Y usa herramientas durante cientos de "
        "pasos. Ideal como cerebro para planificar y crear programas completos.", para=["planificar", "programar", "agente"])),
    (r"qwen3[\w.-]*(235b|480b|397b|max)|qwen3\.[5-9][\w.-]*(1\d\db|2\d\db|3\d\db|max)", dict(familia="Qwen3 grande (Alibaba)",
        prog=5, intel=5, vel=3, tokens="medio", tools=True, vision=False,
        desc="Versión grande de Qwen: nivel de vanguardia en programación y razonamiento.", para=["programar", "planificar", "agente"])),
    (r"nemotron[\w.-]*(ultra|super)", dict(familia="Nemotron Super/Ultra (NVIDIA)", prog=4, intel=5, razona=5, vel=3,
        tokens="medio (razona)", tools=True, vision=False, desc="Razonador grande de NVIDIA, gratis en build.nvidia.com. "
        "Muy bueno para planificar y analizar.", para=["planificar", "razonar"])),
    (r"minimax-m\d", dict(familia="MiniMax M (agente)", prog=5, intel=4, razona=4, vel=4, tokens="medio", tools=True, vision=False,
        desc="Pensado para agentes de programación: rápido, eficiente y usa herramientas muy bien.", para=["programar", "agente"])),
    (r"gpt-oss-120b", dict(familia="GPT-OSS 120B (OpenAI, abierto)", prog=4, intel=5, razona=5, vel=4, tokens="medio (razona)", tools=True,
        vision=False, desc="Razonador abierto grande de OpenAI; gratis en NVIDIA, Groq y Cerebras (muy rápido allí).",
        para=["planificar", "razonar", "agente"])),
    (r"gemini-[3-9][\w.-]*pro|gemini-2\.5-pro", dict(familia="Gemini Pro (Google)", prog=5, intel=5, razona=5, vel=3, tokens="medio",
        tools=True, vision=True, desc="De los más inteligentes; razona a fondo, contexto enorme y ve imágenes. "
        "Tiene plan gratuito en Google AI Studio (con límite diario).", para=["planificar", "programar", "visión"])),
    (r"glm-5[\w.-]*flash", dict(familia="GLM-5 Flash (Z.ai)", prog=4, intel=4, vel=5, tokens="medio (razona)", tools=True, vision=True,
        desc="Rápido, ve imágenes y usa herramientas muy bien. Excelente agente todoterreno y para programar.",
        para=["agente", "programar", "visión"])),
    (r"glm-5", dict(familia="GLM-5 (Z.ai)", prog=5, intel=5, vel=3, tokens="alto", tools=True, vision=False,
        desc="Modelo grande de primer nivel para programar y tareas largas de agente.", para=["programar", "planificar"])),
    (r"glm-4\.\d", dict(familia="GLM-4.x (Z.ai)", prog=4, intel=4, vel=4, tokens="medio", tools=True, vision=False,
        desc="Muy bueno programando y usando herramientas.", para=["programar", "agente"])),
    (r"kimi-k2", dict(familia="Kimi K2 (Moonshot)", prog=5, intel=5, vel=3, tokens="medio", tools=True, vision=False,
        desc="Uno de los mejores para agentes de programación: sigue planes largos y usa herramientas con precisión.",
        para=["programar", "agente", "planificar"])),
    (r"deepseek-r1|deepseek-reasoner", dict(familia="DeepSeek-R1 (razonador)", prog=3, intel=5, vel=2, tokens="alto (piensa mucho)",
        tools=False, vision=False, desc="Razona paso a paso muy bien (matemáticas, lógica), pero es lento, gasta muchos tokens "
        "pensando y usa mal las herramientas. Úsalo para planificar o analizar, no como agente.", para=["razonar"])),
    (r"deepseek-coder-v2", dict(familia="DeepSeek-Coder-V2 (2024)", prog=4, intel=3, vel=4, tokens="bajo", tools=False, vision=False,
        desc="Buen generador de código (MoE ligero), pero antiguo y con herramientas limitadas.", para=["código suelto"])),
    (r"deepseek-coder", dict(familia="DeepSeek-Coder (2023)", prog=2, intel=2, vel=4, tokens="bajo", tools=False, vision=False,
        desc="Antiguo. Escribe fragmentos de código pero no sirve como agente.", evitar=True)),
    (r"deepseek", dict(familia="DeepSeek V3/V4", prog=5, intel=5, vel=3, tokens="medio", tools=True, vision=False,
        desc="Nivel top para programar y razonar a bajo costo.", para=["programar", "planificar"])),
    (r"qwen3[\w.-]*-coder|qwen3-coder", dict(familia="Qwen3-Coder (Alibaba)", prog=5, intel=4, vel=4, tokens="bajo", tools=True, vision=False,
        desc="El mejor modelo LOCAL para programar como agente (MoE: 30B total, ~3B activos → rápido). Usa herramientas muy bien.",
        para=["programar", "agente", "local"])),
    (r"qwen[\d.]*-?vl", dict(familia="Qwen-VL (visión)", prog=2, intel=3, vel=4, tokens="bajo", tools=True, vision=True,
        desc="Especialista en ver imágenes y leer texto en capturas. Ideal como ayudante de visión local.", para=["visión"])),
    (r"qwen3[.\d]*:?(0\.6|1\.7|4)b|qwen3-?4b", dict(familia="Qwen3 pequeño", prog=2, intel=2, vel=5, tokens="bajo", tools=True, vision=False,
        desc="Muy rápido y ligero. Útil para tareas simples o resúmenes; se pierde en proyectos grandes.", para=["rápido"])),
    (r"qwen3|qwen-3|qwen3\.\d", dict(familia="Qwen3 (Alibaba)", prog=4, intel=4, vel=4, tokens="medio", tools=True, vision=False,
        desc="Muy buen modelo general, usa herramientas bien; puede pensar (razonamiento) o responder directo.",
        para=["agente", "programar"])),
    (r"qwen2\.5-coder|codeqwen", dict(familia="Qwen2.5-Coder / CodeQwen (2024)", prog=3, intel=3, vel=4, tokens="bajo", tools=False,
        vision=False, desc="Generación de código aceptable, generación anterior; herramientas limitadas.")),
    (r"devstral", dict(familia="Devstral (Mistral)", prog=5, intel=4, vel=3, tokens="bajo", tools=True, vision=False,
        desc="Hecho para agentes de programación (edita varios archivos, usa herramientas). Muy recomendado.",
        para=["programar", "agente", "local"])),
    (r"codestral", dict(familia="Codestral (Mistral)", prog=4, intel=3, vel=4, tokens="bajo", tools=True, vision=False,
        desc="Bueno para completar y generar código.", para=["programar"])),
    (r"mistral-(large|medium)|magistral", dict(familia="Mistral grande", prog=4, intel=4, vel=3, tokens="medio", tools=True, vision=True,
        desc="Modelo general sólido.", para=["agente"])),
    (r"gpt-oss", dict(familia="GPT-OSS (OpenAI, abierto)", prog=4, intel=4, vel=4, tokens="medio (razona)", tools=True, vision=False,
        desc="Razona y usa herramientas bien. La versión 20B cabe en 16 GB y funciona en local.", para=["agente", "razonar", "local"])),
    (r"gpt-5|gpt-4\.1|o[34]-|o[34]$", dict(familia="OpenAI GPT", prog=5, intel=5, vel=3, tokens="alto (de pago)", tools=True, vision=True,
        desc="Primer nivel en todo; cuesta dinero por token.", para=["programar", "planificar", "visión"])),
    (r"gpt-4o", dict(familia="GPT-4o", prog=4, intel=4, vel=4, tokens="medio (de pago)", tools=True, vision=True,
        desc="Bueno y rápido con visión. OJO: si aparece en Ollama/LM Studio es otro modelo con ese nombre, no el real de OpenAI.",
        para=["visión"])),
    (r"claude", dict(familia="Claude (Anthropic)", prog=5, intel=5, vel=3, tokens="alto (de pago)", tools=True, vision=True,
        desc="Excelente programando y como agente; de pago.", para=["programar", "agente", "planificar"])),
    (r"gemini-[\d.]+-pro", dict(familia="Gemini Pro (Google)", prog=5, intel=5, vel=3, tokens="medio", tools=True, vision=True,
        desc="Muy inteligente, contexto enorme, ve imágenes y video.", para=["programar", "planificar", "visión"])),
    (r"gemini", dict(familia="Gemini Flash (Google)", prog=4, intel=4, vel=5, tokens="bajo", tools=True, vision=True,
        desc="Rápido y barato, ve imágenes, contexto enorme. Gran opción de respaldo y para visión.", para=["visión", "rápido", "agente"])),
    (r"gemma-?4[\w:.-]*code|gemma4-code", dict(familia="Gemma 4 Code", prog=4, intel=3, vel=4, tokens="bajo", tools=True, vision=False,
        desc="Variante de Gemma 4 orientada a código.", para=["programar", "local"])),
    (r"gemma-?4", dict(familia="Gemma 4 (Google)", prog=4, intel=4, vel=3, tokens="bajo", tools=True, vision=True,
        desc="Multimodal (ve imágenes) y usa herramientas. La 26B es MoE (~4B activos): rinde bien en local aunque use algo de RAM.",
        para=["visión", "agente", "local"])),
    (r"gemma-?3|codegemma|gemma", dict(familia="Gemma (Google)", prog=3, intel=3, vel=4, tokens="bajo", tools=False, vision=True,
        desc="Modelo abierto ligero; generación anterior.")),
    (r"llama-?4|maverick|scout", dict(familia="Llama 4 (Meta)", prog=3, intel=4, vel=4, tokens="medio", tools=True, vision=True,
        desc="Ve imágenes y usa herramientas; programación correcta.", para=["visión"])),
    (r"llama-?3\.[13]-(70|405)b|llama3\.3", dict(familia="Llama 3.x grande", prog=3, intel=4, vel=3, tokens="medio", tools=True, vision=False,
        desc="Buen modelo general.")),
    (r"llama-?3\.2.*vision", dict(familia="Llama 3.2 Vision", prog=2, intel=3, vel=4, tokens="bajo", tools=False, vision=True,
        desc="Ve imágenes; útil como ayudante de visión.")),
    (r"llama-?3\.2|llama3\.2", dict(familia="Llama 3.2 pequeño", prog=2, intel=2, vel=5, tokens="bajo", tools=True, vision=False,
        desc="Muy pequeño (1-3B): rápido pero se equivoca en tareas complejas.", para=["rápido"])),
    (r"llama-?2|llama2", dict(familia="Llama 2 (2023)", prog=1, intel=1, vel=4, tokens="bajo", tools=False, vision=False,
        desc="Antiguo y débil. No lo uses para programar.", evitar=True)),
    (r"hermes", dict(familia="Hermes (Nous)", prog=2, intel=3, vel=4, tokens="bajo", tools=True, vision=False,
        desc="Afinado para usar herramientas; los pequeños (3B) son limitados.")),
    (r"dolphin", dict(familia="Dolphin", prog=2, intel=3, vel=4, tokens="bajo", tools=False, vision=False,
        desc="Conversación sin filtros; no es bueno como agente.")),
    (r"moondream", dict(familia="Moondream (visión mini)", prog=0, intel=1, vel=5, tokens="bajo", tools=False, vision=True,
        desc="Diminuto: solo describe imágenes. Úsalo como ayudante de visión local.", para=["visión"])),
    (r"llava|minicpm-v|bakllava", dict(familia="Modelo de visión local", prog=1, intel=2, vel=4, tokens="bajo", tools=False, vision=True,
        desc="Describe imágenes; útil como ayudante de visión.", para=["visión"])),
    (r"nemotron.*(vl|nano-\d+b-v)", dict(familia="Nemotron VL (NVIDIA)", prog=3, intel=3, vel=4, tokens="bajo", tools=True, vision=True,
        desc="Visión y documentos.", para=["visión"])),
    (r"nemotron", dict(familia="Nemotron (NVIDIA)", prog=4, intel=4, vel=4, tokens="medio (razona)", tools=True, vision=False,
        desc="Razona y usa herramientas; buena opción gratuita en NVIDIA.", para=["agente", "razonar"])),
    (r"phi-?4", dict(familia="Phi-4 (Microsoft)", prog=3, intel=3, vel=5, tokens="bajo", tools=False, vision=False,
        desc="Pequeño y listo para su tamaño; herramientas limitadas.")),
    (r"grok", dict(familia="Grok (xAI)", prog=4, intel=5, vel=3, tokens="alto (de pago)", tools=True, vision=True,
        desc="Modelo grande de xAI.")),
    (r"minimax", dict(familia="MiniMax", prog=4, intel=4, vel=4, tokens="medio", tools=True, vision=False,
        desc="Bueno en agentes y programación.", para=["agente"])),
    (r"coder|code", dict(familia="Modelo de código", prog=3, intel=2, vel=4, tokens="bajo", tools=False, vision=False,
        desc="Especializado en código; verifica si usa herramientas con 🩺 Probar modelo.")),
]
RAZ_RX = re.compile(r"think|reason|r1\b|-r1|qwq|magistral|\bo[134]\b|gpt-5|gpt-oss|nemotron|glm-4\.[5-9]|glm-5|kimi-k2|"
                    r"deepseek-v3\.[12]|deepseek-v4|qwen3|gemini-[2-9]|minimax-m|claude|grok", re.I)
GRATIS_PROV = {"nvidia", "groq", "cerebras", "gemini", "mistral", "huggingface"}
DEFAULT = dict(familia="Modelo general", prog=3, intel=3, vel=3, tokens="medio", tools=None, vision=False,
               desc="Sin datos específicos. Prueba si usa herramientas con ⚙ Ajustes → Avanzado → 🩺 Probar modelo.")


def _params_from_name(name):
    m = re.search(r"(\d+(?:\.\d+)?)\s*[bB]\b|[-:_](\d+(?:\.\d+)?)b", name)
    return float(m.group(1) or m.group(2)) if m else None


def info(model_id, local_info=None):
    pid, name = model_id.split("::", 1) if "::" in model_id else ("nvidia", model_id)
    base = dict(DEFAULT)
    for pat, d in FAMILIAS:
        if re.search(pat, name, re.I):
            base = dict(DEFAULT, **d)
            break
    p = CONFIG["providers"].get(pid, {})
    base["proveedor"] = p.get("name", pid)
    base["local"] = bool(p.get("local"))
    ov = CONFIG.get("model_overrides", {}).get(model_id, {})
    if ov.get("tool_mode") == "nativo":
        base["tools"] = True
    elif ov.get("tool_mode") == "texto":
        base["tools"] = "texto"
    if ov.get("vision"):
        base["vision"] = True
    if ov.get("no_vision"):
        base["vision"] = False
    params = _params_from_name(name)
    if params:  # los modelos chicos de una familia grande rinden menos (también los locales: un «claude-distill-9b» no es Claude)
        if params < 15:
            base["intel"], base["prog"] = min(base["intel"], 3), min(base["prog"], 3)
        elif params < 40:
            base["intel"] = min(base["intel"], 4)
        elif params >= 200 and base["intel"] >= 4 and not p.get("local"):
            base["intel"] = 5
    if "razona" not in base or base["razona"] is True:
        base["razona"] = base["intel"] if RAZ_RX.search(name) else max(1, base["intel"] - 1)
    base["gratis"] = bool(p.get("local") or name.endswith(":free") or pid in GRATIS_PROV)
    if name.endswith(":free"):
        base["tokens"] = "gratis (con límite diario)"
    elif pid in ("nvidia", "groq", "cerebras"):
        base["tokens"] = "gratis (con límite por minuto/día)"
    if base["local"]:
        base["tokens"] = "gratis (usa tu PC)"
        li = local_info or {}
        caps = li.get("caps") or []
        if "tools" in caps:
            base["tools"] = True
        if "vision" in caps:
            base["vision"] = True
        size = li.get("size_gb")
        params = li.get("params_b") or _params_from_name(name)
        if not size and params:
            size = params * 0.62
        L = dict({"vram_gb": 16, "ram_gb": 32}, **(CONFIG.get("local") or {}))
        if size:
            base["tamano_gb"] = round(size, 1)
            if size <= L["vram_gb"] * 0.85:
                base["cabe"] = f"✅ Cabe en tu GPU ({L['vram_gb']} GB): rápido"
                base["vel"] = max(base["vel"], 4) if size < 10 else base["vel"]
            elif size <= L["vram_gb"] + L["ram_gb"] * 0.6:
                moe = re.search(r"a3b|a4b|30b|26b|coder:30b|moe", name, re.I)
                base["cabe"] = ("⚠ Parte va a la RAM" + (": al ser MoE sigue siendo usable" if moe else ": será lento"))
                base["vel"] = min(base["vel"], 3 if moe else 2)
            else:
                base["cabe"] = "❌ Demasiado grande para tu equipo"
                base["vel"] = 1
        if li.get("num_ctx"):
            base["contexto"] = li["num_ctx"]
    else:
        base["cabe"] = "☁ En la nube (no usa tu GPU)"
    if "thinking" in ((local_info or {}).get("caps") or []):
        base["piensa"] = True
    usable = base.get("chat", True) and not base.get("evitar")
    base["vanguardia"] = bool(usable and base["intel"] >= 5 and base["prog"] >= 4)
    # puntaje de "cerebro": inteligencia y razonamiento primero, luego programación y herramientas
    base["cerebro"] = (base["intel"] * 3 + base["razona"] * 2 + base["prog"] * 2 + (2 if base["tools"] is True else 0)) if usable else -1
    from . import salud
    base["verificado"] = salud.verificado(model_id)
    st = salud.get(model_id)
    if st:
        base["estado"] = {"kind": st["kind"], "icono": salud.ICONO.get(st["kind"], "⚠"), "motivo": st["motivo"],
                          "solucion": st["solucion"], "bloqueado": st["kind"] in salud.BLOQUEA}
        if st["kind"] in salud.BLOQUEA:
            base["vanguardia"], base["cerebro"] = False, -1
    score = base["prog"] * 2 + (2 if base["tools"] is True else 0) + base["vel"] + base["intel"]
    base["puntaje"] = score if base.get("chat", True) and not base.get("evitar") and not (base.get("estado") or {}).get("bloqueado") else -1
    base["estrellas"] = min(5, max(1, round(score / 22 * 5))) if base["puntaje"] >= 0 else 0
    return base


def recomendaciones(models_info):
    """models_info: {model_id: info}. Mejor opción disponible por categoría."""
    def best(filt, key):
        c = [(m, i) for m, i in models_info.items() if i.get("puntaje", -1) >= 0 and filt(m, i)]
        probados = [x for x in c if x[1].get("verificado") or x[1].get("local")]
        c = probados or [x for x in c if not x[1].get("estado")]  # primero lo que ya se probó con tus claves
        return max(c, key=lambda x: key(x[1]))[0] if c else None
    def free_ok(m, i):
        return i.get("gratis") and not str(i.get("cabe", "")).startswith("❌")
    cloud_free = any(free_ok(m, i) and not i["local"] for m, i in models_info.items())
    return {
        "🧠 Cerebro gratis (planificar y crear programas)": best(
            lambda m, i: free_ok(m, i) and (not i["local"] or not cloud_free),
            lambda i: (i["vanguardia"], i["intel"], i["razona"], i["prog"], i["tools"] is True)),
        "🚀 Construir gratis (agente de vanguardia)": best(
            lambda m, i: free_ok(m, i) and i["tools"] is True and (not i["local"] or not cloud_free),
            lambda i: (i["vanguardia"], i["prog"], i["intel"], i["razona"])),
        "Programar (mejor calidad)": best(lambda m, i: i["prog"] >= 4, lambda i: (i["prog"], i["tools"] is True, i["intel"])),
        "Programar en tu PC (local)": best(lambda m, i: i["local"] and i["prog"] >= 3 and not i.get("cabe", "").startswith("❌"),
                                           lambda i: (i["prog"], i["tools"] is True, i["vel"])),
        "Agente autónomo (herramientas)": best(lambda m, i: i["tools"] is True, lambda i: (i["prog"] + i["intel"], i["vel"])),
        "Ver imágenes / capturas": best(lambda m, i: i["vision"], lambda i: (i["intel"], i["vel"])),
        "Razonar y planificar": best(lambda m, i: i["intel"] >= 4, lambda i: (i["intel"], i["prog"])),
        "Rápido y económico": best(lambda m, i: i["vel"] >= 4, lambda i: (i["vel"], i["prog"])),
    }


def ranking(models_info, need_tools=True, solo_gratis=True, n=6, incluir_local=False):
    """Los mejores modelos por 'cerebro' (inteligencia + razonamiento + programación), alternando proveedores
    para que si uno llega a su límite gratuito el siguiente sea de otra empresa."""
    c = [(m, i) for m, i in models_info.items() if i.get("cerebro", -1) >= 0
         and (not solo_gratis or i.get("gratis")) and (incluir_local or not i.get("local"))
         and (not need_tools or i.get("tools") is not False) and not str(i.get("cabe", "")).startswith("❌")]
    c.sort(key=lambda x: (bool(x[1].get("verificado")), x[1]["cerebro"], x[1]["tools"] is True), reverse=True)
    out, last = [], None
    while c and len(out) < n:
        pick = 0
        for k, (m, i) in enumerate(c):
            if m.split("::")[0] != last:
                if i["cerebro"] >= c[0][1]["cerebro"] - 4:
                    pick = k
                break
        m, i = c.pop(pick)
        out.append(m)
        last = m.split("::")[0]
    return out


_cache = {"t": 0, "infos": {}}


def all_infos(max_age=300):
    """Info de todos los modelos disponibles de los proveedores activos (con caché de 5 min)."""
    import threading
    import time
    from . import local as LOC
    from .providers import _models_cache
    if _cache["infos"] and time.time() - _cache["t"] < max_age:
        return _cache["infos"]
    from .providers import list_models
    ids = []
    for pid, pc in CONFIG["providers"].items():
        if not pc.get("enabled"):
            continue
        c = _models_cache.get(pid)
        if not c:
            try:
                c = list_models(pid)  # aún no se había pedido la lista (ej. tarea programada al iniciar)
            except Exception:
                c = None
        if c and c.get("ok"):
            ids += [f"{pid}::{m}" for m in c["models"]]
    infos = {}

    def one(mid):
        li = {}
        pid, name = mid.split("::", 1)
        p = CONFIG["providers"].get(pid, {})
        try:
            if p.get("local") and (pid == "ollama" or ":11434" in p.get("base_url", "")):
                li = dict(LOC.ollama_info(p, name))
                li["num_ctx"] = LOC.choose_num_ctx(li)
        except Exception:
            li = {}
        infos[mid] = info(mid, li)
    ths = [threading.Thread(target=one, args=(m,), daemon=True) for m in ids]
    for t in ths:
        t.start()
    for t in ths:
        t.join(15)
    _cache.update(t=time.time(), infos=infos)
    return infos
