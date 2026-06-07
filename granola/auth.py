"""Token primitives: the refresh HTTP exchange, expiry math, account selection,
and status formatting.

These are deliberately persistence-free. *Where* a refreshed token gets written
back (the encrypted desktop store vs. a portable session file) lives in
``sources.py`` — this module only knows how to talk to the refresh endpoint and
how to reason about a token dict.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from ._http import base_headers, request
from .config import Config


class RefreshRevoked(RuntimeError):
    """The refresh token was rejected (revoked or already rotated away).

    Carries a source-specific, human-readable recovery message — the desktop and
    session sources re-raise it with the right re-auth instructions.
    """


def _now_ms() -> int:
    return int(time.time() * 1000)


def token_is_expiring(token: dict, skew_ms: int) -> bool:
    expiry_ms = int(token["obtained_at"]) + int(token["expires_in"]) * 1000
    return (expiry_ms - _now_ms()) < skew_ms


def select_account(store, email: str | None = None):
    if email:
        for acct in store.accounts:
            if acct.get("email") == email:
                return acct
        raise ValueError(f"No stored account with email '{email}'.")
    return store.accounts[0]


def refresh_exchange(cfg: Config, tok: dict) -> dict:
    """POST the refresh token and return a *new* token dict. Pure — no write-back.

    Raises ``RefreshRevoked`` on 401 (revoked/rotated) and ``RuntimeError`` on any
    other non-2xx. The returned dict is a copy of ``tok`` with the rotated fields
    applied, so callers decide where to persist it.
    """
    if not tok.get("refresh_token"):
        raise ValueError("No refresh_token available to refresh.")

    headers = base_headers(cfg, tok["access_token"])
    resp = request("POST", cfg.refresh_url,
                   json_body={"refresh_token": tok["refresh_token"]},
                   headers=headers, timeout=cfg.timeout)

    if resp.status_code == 401:
        kind = None
        try:
            kind = resp.json().get("error")
        except Exception:
            pass
        raise RefreshRevoked(f"Refresh rejected (401{': ' + kind if kind else ''}).")
    if resp.status_code >= 400:
        raise RuntimeError(f"Refresh failed: HTTP {resp.status_code}. {resp.text[:300]}")

    data = resp.json()
    if not data.get("access_token"):
        raise RuntimeError("Refresh OK but no access_token in response.")

    new = dict(tok)
    new["access_token"] = data["access_token"]
    new["expires_in"] = data.get("expires_in", tok.get("expires_in"))
    for key in ("refresh_token", "token_type", "session_id", "sign_in_method"):
        if data.get(key):
            new[key] = data[key]
    new["obtained_at"] = _now_ms()
    return new


def format_token_status(tok: dict, skew_ms: int, include_secrets: bool = False) -> dict:
    """A no-secrets status view of one token dict (secrets gated behind the flag)."""
    obt_ms = int(tok["obtained_at"])
    obtained = datetime.fromtimestamp(obt_ms / 1000, tz=timezone.utc)
    expiry = datetime.fromtimestamp(
        (obt_ms + int(tok["expires_in"]) * 1000) / 1000, tz=timezone.utc
    )
    now = datetime.now(timezone.utc)
    info = {
        "token_type": tok.get("token_type"),
        "sign_in_method": tok.get("sign_in_method"),
        "obtained_at_utc": obtained.isoformat(),
        "expiry_utc": expiry.isoformat(),
        "expired": now > expiry,
        "expiring_soon": token_is_expiring(tok, skew_ms),
        "minutes_left": round((expiry - now).total_seconds() / 60, 1),
    }
    if include_secrets:
        info["access_token"] = tok.get("access_token")
        info["refresh_token"] = tok.get("refresh_token")
    return info
