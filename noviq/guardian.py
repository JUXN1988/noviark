# -*- coding: utf-8 -*-
"""Guardián de razonamiento: vigila en vivo lo que escribe la IA y corta a tiempo los bucles.

Problemas que resuelve (vistos en la práctica con GLM, DeepSeek, Qwen y modelos locales):
  • Razonamiento eterno: la IA «piensa» minutos enteros (escribe el programa completo dentro del razonamiento,
    duda, vuelve a empezar…) sin llamar a ninguna herramienta. El usuario solo ve «Razonando…».
  • Texto repetido: la IA entra en bucle y repite el mismo párrafo o las mismas líneas una y otra vez.

Cuando se dispara, el streaming se corta, el agente conserva un resumen de lo pensado, le pide actuar YA con
herramientas (con razonamiento breve) y, si vuelve a pasar, el escalador pasa el trabajo a una IA más capaz."""
import re
import time

from .config import CONFIG

DEFAULTS = {"activo": True, "max_razonamiento": 16000, "max_seg_razonamiento": 150, "repeticion": True}


def cfg():
    return dict(DEFAULTS, **(CONFIG.get("guardian") or {}))


class Guardian:
    """Se alimenta con cada trozo de razonamiento/texto. `tripped` queda con el motivo si hay que cortar."""

    def __init__(self, max_chars=None, max_secs=None, repeticion=None, factor=1.0):
        c = cfg()
        self.activo = bool(c.get("activo", True))
        self.max_chars = int((max_chars or c["max_razonamiento"]) * factor)
        self.max_secs = float((max_secs or c["max_seg_razonamiento"]) * factor)
        self.rep = c.get("repeticion", True) if repeticion is None else repeticion
        self.reason, self.content = "", ""
        self.t_reason = None
        self.tools = False
        self.tripped = None
        self._chk_r = self._chk_c = 0

    # ── entradas ──
    def on_reasoning(self, t):
        if not self.activo or self.tripped or not t:
            return
        if self.t_reason is None:
            self.t_reason = time.time()
        self.reason += t
        if self.tools:
            return
        if not self.content.strip():
            n = len(self.reason)
            if n > self.max_chars:
                self.tripped = f"razonó {n:,} caracteres sin actuar".replace(",", ".")
                return
            if time.time() - self.t_reason > self.max_secs and n > 1500:
                self.tripped = f"razonó {int(time.time() - self.t_reason)} s sin actuar"
                return
        if self.rep and len(self.reason) - self._chk_r >= 500:
            self._chk_r = len(self.reason)
            m = repeticion(self.reason)
            if m:
                self.tripped = "repite el mismo razonamiento en bucle: «" + m[:70] + "…»"

    def on_content(self, t):
        if not self.activo or self.tripped or not t:
            return
        self.content += t
        if self.rep and not self.tools and len(self.content) - self._chk_c >= 500:
            self._chk_c = len(self.content)
            m = repeticion(self.content, min_line=40, veces_linea=6)
            if m:
                self.tripped = "repite el mismo texto en bucle: «" + m[:70] + "…»"

    def on_tool(self):
        # ya está llamando a una herramienta: lo que falta es el contenido (código) y no se corta
        self.tools = True


_WS = re.compile(r"\s+")


def repeticion(text, ventana=7000, trozo=160, veces=3, min_line=30, veces_linea=5):
    """Devuelve el fragmento repetido si el final del texto está en bucle, o None.
    1) el último trozo de ~160 caracteres aparece ≥3 veces en la ventana final
    2) alguna línea larga aparece ≥5 veces en la ventana final."""
    t = _WS.sub(" ", text[-ventana:]).strip()
    if len(t) >= trozo * veces:
        needle = t[-trozo:]
        if len(set(needle)) > 12 and t.count(needle) >= veces:
            return needle
    lines = [ln.strip() for ln in text[-ventana:].splitlines() if len(ln.strip()) >= min_line]
    if len(lines) >= veces_linea:
        cnt = {}
        for ln in lines:
            cnt[ln] = cnt.get(ln, 0) + 1
        top = max(cnt.items(), key=lambda x: x[1])
        if top[1] >= veces_linea and len(set(top[0])) > 10:
            return top[0]
    return None


def resumen_razonamiento(reasoning, max_chars=1800):
    """Lo útil de un razonamiento cortado: el final (donde suele estar la decisión), sin código largo."""
    r = re.sub(r"```.*?```", "[código omitido]", reasoning or "", flags=re.S)
    r = re.sub(r"\n{3,}", "\n\n", r).strip()
    return ("…" + r[-max_chars:]) if len(r) > max_chars else r
