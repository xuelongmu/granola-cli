"""Read/write Granola's encrypted credential store (the DPAPI -> DEK -> .enc chain)."""
from __future__ import annotations

import base64
import json
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Config
from .crypto import (
    aes_128_cbc_safestorage_decrypt,
    aes_gcm_decrypt,
    aes_gcm_encrypt,
    dpapi_unprotect,
    keychain_password,
)


@dataclass
class Store:
    dek: bytes
    outer: dict
    accounts: list
    enc_path: Path
    kind: str = "windows"   # "windows" | "macos" — controls cred-file structure


def get_dek(cfg: Config) -> bytes:
    """``storage.dek`` -> 32-byte DEK.

    Windows: Local State (DPAPI) -> Chromium key -> AES-256-GCM unwrap.
    macOS:   Keychain password -> PBKDF2 -> AES-128-CBC (safeStorage) unwrap.
    """
    dek_blob = (cfg.granola_dir / "storage.dek").read_bytes()
    if dek_blob[:3] != b"v10":
        raise ValueError("Unexpected storage.dek prefix.")

    if sys.platform == "darwin":
        dek_b64 = aes_128_cbc_safestorage_decrypt(dek_blob, keychain_password()).decode("utf-8")
    else:
        state = json.loads((cfg.granola_dir / "Local State").read_text(encoding="utf-8"))
        blob = base64.b64decode(state["os_crypt"]["encrypted_key"])
        if blob[:5] != b"DPAPI":
            raise ValueError("Unexpected os_crypt key prefix.")
        chrome_key = dpapi_unprotect(blob[5:])
        dek_b64 = aes_gcm_decrypt(dek_blob, chrome_key, prefix_len=3).decode("utf-8")

    dek = base64.b64decode(dek_b64)
    if len(dek) != 32:
        raise ValueError(f"Unexpected DEK length: {len(dek)}")
    return dek


def read_store(cfg: Config, dek: bytes | None = None) -> Store:
    """Decrypt the cred file into a normalized Store (``accounts[0]["tokens"]`` is
    the token JSON string on both platforms).

    Windows: ``stored-accounts.json.enc`` -> ``outer.accounts[].tokens``
    macOS:   ``supabase.json.enc``        -> ``outer.workos_tokens``
    """
    dek = dek or get_dek(cfg)
    if sys.platform == "darwin":
        enc_path = cfg.granola_dir / "supabase.json.enc"
        outer = json.loads(aes_gcm_decrypt(enc_path.read_bytes(), dek).decode("utf-8"))
        tokens = outer.get("workos_tokens")
        if not tokens:
            raise ValueError("supabase.json.enc has no 'workos_tokens'.")
        accounts = [{"email": outer.get("email"), "tokens": tokens}]
        return Store(dek=dek, outer=outer, accounts=accounts, enc_path=enc_path, kind="macos")

    enc_path = cfg.granola_dir / "stored-accounts.json.enc"
    outer = json.loads(aes_gcm_decrypt(enc_path.read_bytes(), dek).decode("utf-8"))
    accounts = json.loads(outer["accounts"])
    if not isinstance(accounts, list):
        accounts = [accounts]
    return Store(dek=dek, outer=outer, accounts=accounts, enc_path=enc_path, kind="windows")


def compact(obj: Any) -> str:
    """Compact JSON matching the app's JSON.stringify (no spaces, UTF-8)."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def save_store(store: Store) -> Path:
    """Re-encrypt and write the cred file, preserving its structure. Guarded:
    verify-before-write, verify-after-write, timestamped backup, auto-rollback.
    Returns the backup path.

    Windows writes back ``outer.accounts`` (nested JSON string); macOS writes back
    ``outer.workos_tokens``.
    """
    if store.kind == "macos":
        store.outer["workos_tokens"] = store.accounts[0]["tokens"]
    else:
        store.outer["accounts"] = compact(store.accounts)
    plain = compact(store.outer)

    blob = aes_gcm_encrypt(plain.encode("utf-8"), store.dek)
    if aes_gcm_decrypt(blob, store.dek).decode("utf-8") != plain:
        raise RuntimeError("Re-encryption round-trip verification failed; aborting.")
    json.loads(plain)  # must be valid JSON

    stamp = int(time.time() * 1000)
    backup = store.enc_path.with_name(store.enc_path.name + f".bak-{stamp}")
    shutil.copy2(store.enc_path, backup)
    try:
        store.enc_path.write_bytes(blob)
        json.loads(aes_gcm_decrypt(store.enc_path.read_bytes(), store.dek).decode("utf-8"))
    except Exception:
        shutil.copy2(backup, store.enc_path)  # rollback
        raise
    return backup
