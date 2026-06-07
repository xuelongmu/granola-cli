"""Windows DPAPI unseal + AES-256-GCM (clean, via the `cryptography` lib).

DPAPI uses a tiny ctypes shim against crypt32.dll so the only third-party
dependency is `cryptography` (no pywin32). DPAPI is inherently Windows + same
Windows user (CurrentUser scope); everything above the access token is portable.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import subprocess
import sys
from ctypes import wintypes

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
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


# --- macOS safeStorage (Keychain-backed) ---------------------------------------
# On macOS, Granola's `storage.dek` is wrapped with Electron/Chromium safeStorage
# (AES-128-CBC, key derived from a Keychain password) instead of Windows DPAPI.
# Scheme + behavior verified against harperreed/muesli's session_decrypt.rs.

KEYCHAIN_SERVICE = "Granola Safe Storage"
KEYCHAIN_ACCOUNT = "Granola Key"
_SAFE_STORAGE_SALT = b"saltysalt"
_SAFE_STORAGE_ITERATIONS = 1003
_SAFE_STORAGE_KEY_LEN = 16
_SAFE_STORAGE_IV = b" " * 16


def keychain_password(service: str = KEYCHAIN_SERVICE, account: str = KEYCHAIN_ACCOUNT) -> str:
    """Read Granola's safeStorage key from the macOS login Keychain.

    Shells out to ``/usr/bin/security`` (no extra deps). The first call may trigger
    a Keychain access prompt unless this binary is already trusted for the item.
    """
    if sys.platform != "darwin":
        raise RuntimeError("Keychain access is only available on macOS.")
    try:
        out = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", service, "-a", account, "-w"],
            capture_output=True, text=True, timeout=20,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("`security` tool not found (macOS only).") from exc
    if out.returncode != 0:
        raise RuntimeError(
            f"Keychain item '{service}'/'{account}' not found or access denied: "
            f"{out.stderr.strip() or out.returncode}"
        )
    return out.stdout.strip("\n")


def aes_128_cbc_safestorage_decrypt(blob: bytes, password: str, prefix: bytes = b"v10") -> bytes:
    """Decrypt an Electron/Chromium safeStorage ``v10`` blob (macOS/Linux scheme).

    Key = PBKDF2-HMAC-SHA1(password, "saltysalt", 1003, 16 bytes); AES-128-CBC with a
    16-space IV and PKCS#7 padding. Used for ``storage.dek`` on macOS.
    """
    if blob[: len(prefix)] != prefix:
        raise ValueError(f"safeStorage blob missing {prefix!r} prefix.")
    ciphertext = blob[len(prefix):]
    key = hashlib.pbkdf2_hmac(
        "sha1", password.encode("utf-8"), _SAFE_STORAGE_SALT,
        _SAFE_STORAGE_ITERATIONS, dklen=_SAFE_STORAGE_KEY_LEN,
    )
    dec = Cipher(algorithms.AES(key), modes.CBC(_SAFE_STORAGE_IV)).decryptor()
    padded = dec.update(ciphertext) + dec.finalize()
    pad = padded[-1] if padded else 0
    if not 1 <= pad <= 16 or pad > len(padded):
        raise ValueError("Bad PKCS#7 padding (wrong Keychain password?).")
    return padded[:-pad]
