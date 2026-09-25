# -*- coding: utf-8 -*-
"""Escalador: cuando la IA se atasca, el trabajo pasa a la IA MÁS CAPAZ que tengas habilitada y con cuota.

Señales de atasco (se suman puntos; al llegar al umbral se escala):
  • el guardián cortó un razonamiento eterno o un bucle de texto ......... 3
  • repitió exactamente la misma acción (detector de bucles) ............ 2
  • la misma edición/herramienta falló otra vez sobre el mismo archivo ... 2
  • errores seguidos de herramientas ..................................... 1 c/u (desde el 2.º)
  • terminó sin usar herramientas cuando aún había trabajo ............... 1
  • las pruebas finales siguen fallando con el mismo error ............... 2
  • respuesta vacía ....................................................... 1

La IA elegida es la de mayor «cerebro» del catálogo (inteligencia + razonamiento + programación + herramientas)
entre los proveedores ACTIVOS, que no esté bloqueada (sin clave, sin crédito, 404) ni en pausa por límite (429),
priorizando las verificadas con tus claves. Si la IA actual ya es la mejor, en vez de cambiar se le da un
diagnóstico automático y una estrategia distinta."""
import re
import time

from .config import CONFIG

DEFAULTS = {"activo": True, "umbral": 5, "max_escalados": 2, "permitir_pago": True}
PESOS = {"guardian": 3, "bucle": 2, "fallo_repetido": 2, "error": 1, "sin_herramientas": 1, "pruebas": 2, "vacia": 1}


def cfg():
    return dict(DEFAULTS, **(CONFIG.get("escalado") or {}))


class Supervisor:
    def __init__(self):
        c = cfg()
        self.activo = bool(c.get("activo", True))
        self.umbral = int(c.get("umbral", 5))
        self.max = int(c.get("max_escalados", 2))
        self.puntos = 0
        self.motivos = []
        self.escalados = 0
        self.errores_seguidos = 0
        self.fallos = {}  # (herramienta, objetivo) → veces que falló
        self.intervenciones = 0

    def registrar(self, tipo, detalle=""):
        self.puntos += PESOS.get(tipo, 1)
        if detalle:
            self.motivos.append(detalle)
            del self.motivos[:-6]

    def resultado(self, name, args, result, es_error):
        """Se llama tras cada herramienta."""
        if not es_error:
            self.errores_seguidos = 0
            if name in ("escribir_archivo", "editar_archivo", "probar_proyecto", "diagnosticar", "probar_web"):
                self.puntos = max(0, self.puntos - 1)  # avanzar de verdad descuenta puntos
            return
        self.errores_seguidos += 1
        obj = str(args.get("ruta") or args.get("comando") or args.get("codigo") or "")[:120]
        k = (name, obj)
        self.fallos[k] = self.fallos.get(k, 0) + 1
        linea = str(result).strip().splitlines()[0] if str(result).strip() else "error"
        linea = re.sub(r"^ERROR(?: en la edición \d+ de \d+)?(?: \(no se modificó nada\))?:\s*", "", linea).split(". ")[0][:90]
        if self.fallos[k] >= 2:
            self.registrar("fallo_repetido", f"{name} falló {self.fallos[k]} veces sobre {obj[:60] or 'lo mismo'}: {linea}")
        elif self.errores_seguidos >= 2:
            self.registrar("error", f"{self.errores_seguidos} errores seguidos ({name}: {linea})")

    def atascado(self):
        return self.activo and self.puntos >= self.umbral

    def reiniciar(self):
        self.puntos = 0
        self.errores_seguidos = 0
        self.fallos.clear()

    def explicacion(self):
        return "; ".join(dict.fromkeys(self.motivos[-4:])) or "no avanzaba"


def _limitado(model_id):
    from . import salud
    st = salud.get(model_id)
    return bool(st and st.get("kind") in salud.BLOQUEA | {"limite"})


def candidatos(actual, excluir=(), need_tools=True):
    """Modelos habilitados, ordenados de más a menos capaz, que se pueden usar ahora (con cuota)."""
    from . import catalogo as K
    try:
        infos = K.all_infos()
    except Exception:
        infos = {}
    c = cfg()
    pool = []
    for m, i in infos.items():
        if m == actual or m in excluir or i.get("cerebro", -1) < 0 or _limitado(m):
            continue
        if need_tools and i.get("tools") is False:
            continue
        if i.get("local"):
            continue  # un modelo local no es «más capaz» que uno de la nube para rescatar un trabajo atascado
        if not c.get("permitir_pago", True) and not i.get("gratis"):
            continue
        if str(i.get("cabe", "")).startswith("❌"):
            continue
        pool.append((m, i))
    # también los de respaldo configurados por el usuario, aunque su lista no esté en caché
    for m in CONFIG.get("fallback_models") or []:
        if m and m != actual and m not in excluir and m not in infos and not _limitado(m):
            try:
                pool.append((m, K.info(m)))
            except Exception:
                pass
    pool.sort(key=lambda x: (bool(x[1].get("verificado")), x[1].get("cerebro", 0), x[1].get("tools") is True,
                             x[1].get("prog", 0)), reverse=True)
    return pool


def mejor(actual, excluir=()):
    """(modelo, info) de la IA a la que conviene escalar, o (None, motivo) si no hay una mejor."""
    from . import catalogo as K
    try:
        cur = K.info(actual)
    except Exception:
        cur = {"cerebro": 0}
    cur_score = cur.get("cerebro", 0) if cur.get("cerebro", -1) >= 0 else 0
    if cur.get("local"):
        cur_score = min(cur_score, 18)  # los locales pequeños se quedan cortos en depuración difícil
    pool = candidatos(actual, excluir)
    if not pool:
        return None, "no hay otra IA habilitada con cuota disponible"
    # la lista viene ordenada: primero las verificadas con tus claves, luego por capacidad
    for m, i in pool:
        if i.get("cerebro", 0) > cur_score:
            return m, i
    # otra IA igual de capaz o casi (otra «mente») también sirve para destrabar un trabajo
    for cond in (lambda c, v: c == cur_score and v, lambda c, v: c == cur_score, lambda c, v: c >= cur_score - 2):
        for m, i in pool:
            if cond(i.get("cerebro", 0), bool(i.get("verificado"))):
                return m, i
    return None, f"{actual.split('::')[-1]} ya es la IA más capaz que tienes habilitada"


class Registro:
    """Recuerda por conversación a qué modelos ya se escaló (para no volver al que se atascó)."""
    def __init__(self, conv):
        self.conv = conv

    def excluidos(self):
        now = time.time()
        return [m for m, t in (self.conv.get("_atascados") or {}).items() if now - t < 3600]

    def marcar(self, model_id):
        d = self.conv.setdefault("_atascados", {})
        d[model_id] = time.time()
        for k in [k for k, t in d.items() if time.time() - t > 3600]:
            d.pop(k, None)
