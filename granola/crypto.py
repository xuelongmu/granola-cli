"""Windows DPAPI unseal + AES-256-GCM (clean, via the `cryptography` lib).

DPAPI uses a tiny ctypes shim against crypt32.dll so the only third-party
dependency is `cryptography` (no pywin32). DPAPI is inherently Windows + same
Windows user (CurrentUser scope); everything above the access token is portable.
"""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def dpapi_unprotect(blob: bytes) -> bytes:
    """Decrypt a Windows DPAPI blob under the CurrentUser scope."""
    if sys.platform != "win32":
        raise RuntimeError("DPAPI decryption is only available on Windows.")

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_byte))]

    buf_in = ctypes.create_string_buffer(bytes(blob), len(blob))
    blob_in = DATA_BLOB(len(blob), ctypes.cast(buf_in, ctypes.POINTER(ctypes.c_byte)))
    blob_out = DATA_BLOB()

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def aes_gcm_decrypt(blob: bytes, key: bytes, prefix_len: int = 0, iv_len: int = 12) -> bytes:
    """Decrypt a `[prefix?] + IV(12) + ciphertext + tag(16)` blob.

    `cryptography` expects the GCM tag appended to the ciphertext, which is
    exactly Granola's on-disk layout after the IV.
    """
    nonce = blob[prefix_len:prefix_len + iv_len]
    ct_and_tag = blob[prefix_len + iv_len:]
    return AESGCM(key).decrypt(nonce, ct_and_tag, None)


def aes_gcm_encrypt(plaintext: bytes, key: bytes, iv_len: int = 12) -> bytes:
    """Produce `IV(12) + ciphertext + tag(16)`, matching Granola's `.enc` layout."""
    nonce = os.urandom(iv_len)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, None)
