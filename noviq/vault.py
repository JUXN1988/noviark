# -*- coding: utf-8 -*-
"""Bóveda de API keys cifrada.

Windows: cifrado DPAPI (el mismo que usa Windows para contraseñas guardadas). Solo tu usuario de
Windows en esta PC puede descifrarlo: si copian el archivo a otra PC o a otro usuario, no sirve.
Otros sistemas: ofuscado + permisos 600 (solo tu usuario puede leerlo).
"""
import base64
import getpass
import hashlib
import json
import os
import platform
import threading

from .config import DATA_DIR, IS_WINDOWS

VAULT = DATA_DIR / "claves.vault"
_ENTROPY = b"NVIDIA-Chat-v2-boveda"  # NO cambiar: descifra las claves ya guardadas
_lock = threading.Lock()
_cache = None

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _mk(data: bytes):
        buf = ctypes.create_string_buffer(data, len(data))
        return _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    def _dpapi(data: bytes, protect: bool) -> bytes:
        crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
        inb, _b1 = _mk(data)
        ent, _b2 = _mk(_ENTROPY)
        out = _BLOB()
        if protect:
            ok = crypt32.CryptProtectData(ctypes.byref(inb), "Noviq", ctypes.byref(ent), None, None, 0x01,
                                          ctypes.byref(out))
        else:
            ok = crypt32.CryptUnprotectData(ctypes.byref(inb), None, ctypes.byref(ent), None, None, 0x01,
                                            ctypes.byref(out))
        if not ok:
            raise OSError("DPAPI falló (código %d)" % kernel32.GetLastError())
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            kernel32.LocalFree(out.pbData)


def _obf_key():
    return hashlib.sha256(f"{getpass.getuser()}|{platform.node()}|".encode() + _ENTROPY).digest()


def _xor(data: bytes) -> bytes:
    k = _obf_key()
    return bytes(b ^ k[i % len(k)] for i, b in enumerate(data))


def _encrypt(data: bytes) -> str:
    if IS_WINDOWS:
        try:
            return "DPAPI:" + base64.b64encode(_dpapi(data, True)).decode()
        except Exception as e:  # respaldo si DPAPI no está disponible
            print("[bóveda] DPAPI no disponible, uso ofuscación:", e)
    return "OBF:" + base64.b64encode(_xor(data)).decode()


def _decrypt(text: str) -> bytes:
    kind, _, b64 = text.partition(":")
    raw = base64.b64decode(b64)
    if kind == "DPAPI":
        return _dpapi(raw, False)
    return _xor(raw)


def load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    data = {}
    if VAULT.exists():
        try:
            data = json.loads(_decrypt(VAULT.read_text(encoding="utf-8").strip()).decode("utf-8"))
        except Exception as e:
            print("[bóveda] no se pudo descifrar las claves:", e)
            data = {}
    _cache = data
    return data


def save(data: dict):
    global _cache
    with _lock:
        _cache = {k: [x for x in v if x] for k, v in data.items()}
        tmp = VAULT.with_suffix(".tmp")
        tmp.write_text(_encrypt(json.dumps(_cache).encode("utf-8")), encoding="utf-8")
        tmp.replace(VAULT)
        if not IS_WINDOWS:
            os.chmod(VAULT, 0o600)


def get_keys(pid) -> list:
    return list(load().get(pid, []))


def set_keys(pid, keys):
    d = dict(load())
    d[pid] = [k.strip() for k in keys if k and k.strip()]
    save(d)


def mask(k):
    return k[:9] + "…" + k[-6:] if len(k) > 20 else (k[:4] + "…" + k[-3:] if len(k) > 10 else "•" * len(k))
