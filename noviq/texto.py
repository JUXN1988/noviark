# -*- coding: utf-8 -*-
"""Lectura de archivos de texto con detección correcta de la codificación.

Antes se probaba UTF-8 y, si fallaba, UTF-16: un archivo guardado por PowerShell en ANSI (Windows-1252, con
acentos) se decodificaba como UTF-16 y la IA veía «caracteres chinos» (ℼ佄呃偙…), creía que el archivo estaba
dañado y lo reescribía entero. Ahora UTF-16 solo se usa si hay BOM o el patrón de bytes nulos lo confirma."""
import codecs
import re
from pathlib import Path

NOMBRES = {"utf-8": "UTF-8", "utf-8-sig": "UTF-8 con BOM", "utf-16": "UTF-16", "utf-16-le": "UTF-16 LE",
           "utf-16-be": "UTF-16 BE", "cp1252": "Windows-1252 (ANSI)", "latin-1": "Latin-1"}
MOJIBAKE = re.compile(r"Ã[\u0080-¿¡-ÿ]|Â[¡-¿ ]|â€[\u0080-¿™œ“”˜¦]|ï»¿")


def decode(data: bytes):
    """(texto, codificación) de unos bytes."""
    if data.startswith(codecs.BOM_UTF8):
        return data[3:].decode("utf-8", "replace"), "utf-8-sig"
    if data.startswith(codecs.BOM_UTF16_LE) or data.startswith(codecs.BOM_UTF16_BE):
        try:
            return data.decode("utf-16"), "utf-16"
        except UnicodeDecodeError:
            pass
    n = len(data)
    if n >= 4 and data.count(b"\x00") >= n // 4:
        # UTF-16 sin BOM: los bytes nulos caen casi todos en posiciones pares (BE) o impares (LE)
        odd = data[1::2].count(b"\x00")
        even = data[0::2].count(b"\x00")
        enc = "utf-16-le" if odd > even * 3 else "utf-16-be" if even > odd * 3 else None
        if enc:
            try:
                return data.decode(enc), enc
            except UnicodeDecodeError:
                pass
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1252"), "cp1252"
    except UnicodeDecodeError:
        return data.decode("latin-1"), "latin-1"


def read(path):
    """(texto, codificación) de un archivo."""
    return decode(Path(path).read_bytes())


def read_text(path):
    return read(path)[0]


def es_utf8(enc):
    return enc in ("utf-8", "utf-8-sig")


def nombre(enc):
    return NOMBRES.get(enc, enc)


def problemas(data: bytes, text=None, enc=None):
    """Lista de problemas de codificación de un archivo de texto (vacía si está bien)."""
    if text is None:
        text, enc = decode(data)
    out = []
    if not es_utf8(enc):
        out.append(f"está guardado en {nombre(enc)}, no en UTF-8 (típico de Set-Content/Out-File de PowerShell): "
                   "los acentos y la ñ se verán mal y algunas herramientas lo leen como basura")
    if "\x00" in text:
        out.append("contiene caracteres nulos (\\0): el archivo está dañado o mezcla UTF-16 con UTF-8")
    if MOJIBAKE.search(text):
        m = MOJIBAKE.search(text)
        out.append(f"tiene acentos dañados (mojibake, ej. «{m.group(0)}»): el texto se guardó dos veces con codificaciones distintas")
    return out


def reparar(path):
    """Convierte un archivo de texto a UTF-8 (sin BOM) sin perder nada. Devuelve la codificación anterior o None."""
    p = Path(path)
    data = p.read_bytes()
    text, enc = decode(data)
    if es_utf8(enc) and "\x00" not in text:
        return None
    p.write_bytes(text.replace("\x00", "").encode("utf-8"))
    return enc
