"""Windows DPAPI protection for the BIN service token. Only this Windows account can read it back."""

from __future__ import annotations

import base64
import sys

_ENTROPY = b"CardStripeExaminer.binToken"
_PROTECTED_KEY = "binTokenProtected"
_PLAIN_KEY = "binToken"


class ProtectionUnavailable(RuntimeError):
    pass


def available() -> bool:
    return sys.platform == "win32"


def _blob_api():
    if not available():
        raise ProtectionUnavailable("Windows data protection is not available on this system.")
    import ctypes
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    return ctypes, DataBlob, crypt32, kernel32


def _blob(ctypes, DataBlob, data: bytes):
    buffer = ctypes.create_string_buffer(data, len(data))
    return DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def protect(text: str) -> str:
    ctypes, DataBlob, crypt32, kernel32 = _blob_api()
    source, _keep = _blob(ctypes, DataBlob, text.encode("utf-8"))
    entropy, _keep_entropy = _blob(ctypes, DataBlob, _ENTROPY)
    result = DataBlob()
    if not crypt32.CryptProtectData(
        ctypes.byref(source), "CardStripeExaminer", ctypes.byref(entropy), None, None, 0x01, ctypes.byref(result)
    ):
        raise ProtectionUnavailable("Windows could not protect the token.")
    try:
        data = ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(result.pbData)
    return base64.b64encode(data).decode("ascii")


def unprotect(encoded: str) -> str:
    ctypes, DataBlob, crypt32, kernel32 = _blob_api()
    source, _keep = _blob(ctypes, DataBlob, base64.b64decode(encoded))
    entropy, _keep_entropy = _blob(ctypes, DataBlob, _ENTROPY)
    result = DataBlob()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source), None, ctypes.byref(entropy), None, None, 0x01, ctypes.byref(result)
    ):
        raise ProtectionUnavailable("Windows could not read the protected token.")
    try:
        data = ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(result.pbData)
    return data.decode("utf-8")


def load_token(settings, protector=None) -> str:
    """Read the token. A token saved in plain text by an earlier version is protected and the plain copy removed."""
    protect_text, unprotect_text, can_protect = protector or (protect, unprotect, available())
    stored = str(settings.value(_PROTECTED_KEY, "") or "")
    if stored:
        try:
            return unprotect_text(stored)
        except Exception:
            return ""
    plain = str(settings.value(_PLAIN_KEY, "") or "")
    if plain and can_protect:
        try:
            settings.setValue(_PROTECTED_KEY, protect_text(plain))
            settings.remove(_PLAIN_KEY)
        except Exception:
            pass
    return plain


def save_token(settings, token: str, protector=None) -> bool:
    """Store the token protected. Returns False when it can only be kept until the program closes."""
    protect_text, _unprotect_text, can_protect = protector or (protect, unprotect, available())
    settings.remove(_PLAIN_KEY)
    if not token:
        settings.remove(_PROTECTED_KEY)
        return True
    if not can_protect:
        settings.remove(_PROTECTED_KEY)
        return False
    try:
        settings.setValue(_PROTECTED_KEY, protect_text(token))
    except Exception:
        settings.remove(_PROTECTED_KEY)
        return False
    return True
