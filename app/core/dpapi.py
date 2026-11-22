"""
core/dpapi.py - Windows' per-user encryption (DPAPI), through ctypes.

`protect()` seals bytes so that only the SAME Windows user on the SAME machine
can `unprotect()` them: the key is derived from the user's logon secret and
never leaves Windows. There is nothing for the app to store, and no extra
dependency - crypt32 ships with every Windows.

What it buys: a copied, zipped, synced or backed-up data folder no longer
carries a usable secret. What it does NOT buy: protection from other programs
running as the same user - they can ask Windows to unseal it exactly as this
module does.

Off Windows both functions return None ("unavailable"); callers keep their
plain-file behaviour there.
"""

from __future__ import annotations

import sys

#: Mixed into the key so a blob sealed here is not unsealed by a generic
#: "decrypt any DPAPI blob" call that does not know it. Not a secret.
_ENTROPY = b"WarframeToolbox/dpapi/1"

_UI_FORBIDDEN = 0x1          # CRYPTPROTECT_UI_FORBIDDEN: never show a prompt


def available() -> bool:
    return sys.platform == "win32"


def _call(fn_name: str, data: bytes) -> bytes | None:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(raw: bytes) -> Blob:
        buf = ctypes.create_string_buffer(raw, len(raw))
        return Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    fn = getattr(crypt32, fn_name)
    # Both functions share this shape; the 2nd argument is a description
    # string for Protect and a pointer-to-pointer for Unprotect - NULL in
    # both cases here, so a void pointer serves either.
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p,
                   ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    src, salt, out = blob(data), blob(_ENTROPY), Blob()
    if not fn(ctypes.byref(src), None, ctypes.byref(salt), None, None,
              _UI_FORBIDDEN, ctypes.byref(out)):
        return None
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def protect(data: bytes) -> bytes | None:
    """Seal `data` for this Windows user. None when unavailable or refused."""
    if not available():
        return None
    try:
        return _call("CryptProtectData", data)
    except Exception:                                       # noqa: BLE001
        return None


def unprotect(sealed: bytes) -> bytes | None:
    """Unseal bytes from protect(). None when they were sealed by another
    user or machine, are corrupt, or DPAPI is unavailable."""
    if not available():
        return None
    try:
        return _call("CryptUnprotectData", sealed)
    except Exception:                                       # noqa: BLE001
        return None
