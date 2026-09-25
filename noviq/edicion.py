# -*- coding: utf-8 -*-
"""Motor de edición tolerante para editar_archivo (como la herramienta Edit de los mejores agentes, pero más
paciente con las IAs pequeñas).

Busca `texto_anterior` en el archivo con estrategias cada vez más flexibles y SOLO aplica el cambio si la
coincidencia es única:
  1. exacta
  2. sin los números de línea que la IA copió de leer_archivo («  392\\t…» o «392| …»)
  3. sin escapes dobles (\\" y \\n literales)
  4. línea a línea ignorando espacios al final, la sangría, los espacios internos o las líneas en blanco
     (la sangría del texto nuevo se ajusta a la del archivo)
  5. aproximada (≥ 90 % de similitud y sin empate)
Si no la encuentra, el error dice EXACTAMENTE dónde está lo más parecido (con números de línea y el texto real)
para que la IA copie el texto correcto o use desde_linea/hasta_linea."""
import difflib
import re

_NUM_PREFIX = re.compile(r"^\s*\d{1,6}(?:\t| ?\| ?|: )")


def _strip_numbers(s):
    lines = s.split("\n")
    body = [ln for ln in lines if ln.strip()]
    if body and all(_NUM_PREFIX.match(ln) for ln in body):
        return "\n".join(_NUM_PREFIX.sub("", ln, count=1) if ln.strip() else ln for ln in lines)
    return None


def _unescape(s):
    if "\n" not in s and ("\\n" in s or '\\"' in s):
        return s.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"').replace("\\'", "'")
    if '\\"' in s:
        return s.replace('\\"', '"')
    return None


def _indent(s):
    return s[:len(s) - len(s.lstrip())]


def _reindent(new_lines, old_first, file_first):
    ow, fw = _indent(old_first), _indent(file_first)
    if ow == fw:
        return new_lines
    body = [ln for ln in new_lines if ln.strip()]
    if not ow:
        return [fw + ln if ln.strip() else ln for ln in new_lines]
    if body and all(ln.startswith(ow) for ln in body):
        return [fw + ln[len(ow):] if ln.strip() else ln for ln in new_lines]
    return new_lines


KEYS = [
    ("sin espacios al final", lambda x: x.rstrip()),
    ("ignorando la sangría", lambda x: x.strip()),
    ("ignorando espacios", lambda x: re.sub(r"\s+", " ", x.strip())),
    ("ignorando todos los espacios", lambda x: re.sub(r"\s+", "", x)),
]


def _find_lines(tl, ol, key, skip_blank=False):
    """Posiciones (inicio, fin) donde las líneas ol aparecen en tl según key."""
    if skip_blank:
        idx = [i for i, x in enumerate(tl) if x.strip()]
        kt = [key(tl[i]) for i in idx]
        ko = [key(x) for x in ol if x.strip()]
        n = len(ko)
        if not n:
            return []
        return [(idx[j], idx[j + n - 1] + 1) for j in range(len(kt) - n + 1) if kt[j] == ko[0] and kt[j:j + n] == ko]
    ko = [key(x) for x in ol]
    n = len(ko)
    return [(i, i + n) for i in range(len(tl) - n + 1) if key(tl[i]) == ko[0] and [key(x) for x in tl[i:i + n]] == ko]


def _fuzzy(tl, ol, limit=4000):
    """Mejor ventana aproximada: (ratio, inicio, fin, mejor_ratio_de_otra_zona) o None."""
    if len(tl) > limit or not ol:
        return None
    target = "\n".join(x.strip() for x in ol)
    n = len(ol)
    sm = difflib.SequenceMatcher(autojunk=False)
    sm.set_seq2(target)
    found = []
    floor = 0.45
    for size in sorted({n, max(1, n - 1), n + 1}):
        for i in range(0, max(1, len(tl) - size + 1)):
            sm.set_seq1("\n".join(x.strip() for x in tl[i:i + size]))
            if sm.real_quick_ratio() < floor or sm.quick_ratio() < floor:
                continue
            r = sm.ratio()
            if r >= floor:
                found.append((r, i, i + size))
    if not found:
        return None
    best = max(found)
    others = [f[0] for f in found if f[2] <= best[1] or f[1] >= best[2]]
    return best[0], best[1], best[2], max(others) if others else 0.0


def buscar_parecido(text, old, max_lines=14):
    """Texto del error: dónde está lo más parecido (con números de línea) y qué líneas NO existen."""
    tl = text.split("\n")
    ol = [x for x in old.strip("\n").split("\n")]
    out = []
    fz = _fuzzy(tl, ol) if len(tl) <= 4000 else None
    if fz and fz[0] >= 0.45:
        r, a, b, _ = fz
        a0, b0 = a, min(b, a + max_lines)
        body = "\n".join(f"{i + 1:>5}\t{tl[i]}" for i in range(a0, b0))
        out.append(f"Lo más parecido está en las líneas {a + 1}-{b} (similitud {int(r * 100)}%). Texto REAL del archivo:\n{body}"
                   + ("\n  …" if b > b0 else "")
                   + f"\n→ Copia EXACTAMENTE ese texto en texto_anterior, o usa desde_linea={a + 1}, hasta_linea={b} con texto_nuevo.")
    first = next((x.strip() for x in ol if x.strip()), "")
    if first and not any(first == x.strip() for x in tl):
        close = difflib.get_close_matches(first, [x.strip() for x in tl if x.strip()], n=1, cutoff=0.8)
        if not close:
            out.append(f"OJO: la línea «{first[:90]}» NO existe en el archivo (¿inventaste código que no está? Lee el archivo "
                       "o usa buscar_en_archivos antes de editar).")
    return "\n".join(out)


def aplicar(text, old, new, todo=False, rango=None):
    """Aplica un reemplazo. Devuelve (texto_nuevo, n_cambios, error, nota).
    rango=(desde, hasta) opcional: si texto_anterior no aparece pero se parece a esas líneas, se usan esas líneas."""
    old = (old or "").replace("\r\n", "\n")
    new = (new or "").replace("\r\n", "\n")
    if not old:
        return text, 0, "texto_anterior está vacío", ""
    # 1) exacta
    n = text.count(old)
    if n == 1 or (n > 1 and todo):
        return (text.replace(old, new) if todo else text.replace(old, new, 1)), n, None, ""
    if n > 1:
        lines = []
        start = 0
        for _ in range(min(n, 5)):
            k = text.find(old, start)
            lines.append(text.count("\n", 0, k) + 1)
            start = k + 1
        return text, n, (f"texto_anterior aparece {n} veces (líneas {', '.join(map(str, lines))}): agrega líneas vecinas para que sea "
                         "único, usa desde_linea/hasta_linea, o reemplazar_todo=true si quieres cambiarlas todas"), ""
    # 2) números de línea copiados  3) escapes dobles
    for fix, nota in ((_strip_numbers, "quité los números de línea que copiaste de leer_archivo"),
                      (_unescape, "quité escapes dobles (\\\" o \\n literales)")):
        o2 = fix(old)
        if o2 and o2 != old:
            n2 = fix(new) or new
            t2, k, err, nota2 = aplicar(text, o2, n2, todo)
            if not err:
                return t2, k, None, nota + ("; " + nota2 if nota2 else "")
    if todo:
        return text, 0, "texto_anterior no se encontró exactamente (con reemplazar_todo solo se aceptan coincidencias exactas)", ""
    tl = text.split("\n")
    ol = old.strip("\n").split("\n")
    nl = new.strip("\n").split("\n") if new.strip("\n") else []
    # 4) línea a línea con tolerancias
    for desc, key in KEYS:
        for skip_blank in (False, True):
            hits = _find_lines(tl, ol, key, skip_blank)
            if len(hits) == 1:
                a, b = hits[0]
                first_old = next((x for x in ol if x.strip()), "")
                new_lines = _reindent(nl, first_old, tl[a]) if desc != "sin espacios al final" else nl
                out = tl[:a] + new_lines + tl[b:]
                return "\n".join(out), 1, None, (f"coincidencia {desc}" + (" y líneas en blanco" if skip_blank else "")
                                                 + f" (líneas {a + 1}-{b})")
            if len(hits) > 1:
                return text, len(hits), (f"texto_anterior aparece {len(hits)} veces ({desc}; líneas "
                                         f"{', '.join(str(h[0] + 1) for h in hits[:5])}): agrega líneas vecinas para que sea único "
                                         "o usa desde_linea/hasta_linea"), ""
    # 5) aproximada
    fz = _fuzzy(tl, ol)
    if fz:
        r, a, b, second = fz
        if r >= 0.90 and second < r - 0.04 and len(ol) >= 2:
            first_old = next((x for x in ol if x.strip()), "")
            out = tl[:a] + _reindent(nl, first_old, tl[a]) + tl[b:]
            return "\n".join(out), 1, None, (f"coincidencia APROXIMADA ({int(r * 100)}%) en las líneas {a + 1}-{b}: revisa el diff "
                                             "de abajo; si no era ahí, usa deshacer_cambio")
    # 6) rango indicado por la IA
    if rango:
        d, h = rango
        if 1 <= d <= h <= len(tl):
            seg = "\n".join(x.strip() for x in tl[d - 1:h])
            r = difflib.SequenceMatcher(None, seg, "\n".join(x.strip() for x in ol)).ratio()
            if r >= 0.6:
                first_old = next((x for x in ol if x.strip()), "")
                out = tl[:d - 1] + _reindent(nl, first_old, tl[d - 1]) + tl[h:]
                return "\n".join(out), 1, None, (f"texto_anterior no coincidía exacto; usé las líneas {d}-{h} que indicaste "
                                                 f"(similitud {int(r * 100)}%)")
    return text, 0, "texto_anterior no se encontró en el archivo. " + buscar_parecido(text, old), ""
