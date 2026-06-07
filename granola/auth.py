"""Token status, refresh (redirect-safe, with write-back), and access-token retrieval."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone

from ._http import base_headers, granola_running, request
from .config import Config
from .store import compact, read_store, save_store


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


def refresh_account_token(cfg: Config, account: dict) -> bool:
    """Refresh one account's tokens in place. Returns True on success."""
    tok = json.loads(account["tokens"])
    if not tok.get("refresh_token"):
        raise ValueError(f"Account {account.get('email')} has no refresh_token.")

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
        raise RuntimeError(
            f"Refresh rejected (401{': ' + kind if kind else ''}). "
            "Refresh token revoked - sign in via the Granola app."
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"Refresh failed: HTTP {resp.status_code}. {resp.text[:300]}")

    data = resp.json()
    if not data.get("access_token"):
        raise RuntimeError("Refresh OK but no access_token in response.")

    tok["access_token"] = data["access_token"]
    tok["expires_in"] = data["expires_in"]
    for key in ("refresh_token", "token_type", "session_id", "sign_in_method"):
        if data.get(key):
            tok[key] = data[key]
    tok["obtained_at"] = _now_ms()

    account["tokens"] = compact(tok)
    account["savedAt"] = tok["obtained_at"]
    return True


def get_access_token(cfg: Config, email: str | None = None, no_refresh: bool = False,
                     force: bool = False, passthru: bool = False):
    """Return a valid access token, auto-refreshing + writing back if expiring."""
    store = read_store(cfg)
    acct = select_account(store, email)
    tok = json.loads(acct["tokens"])

    if not no_refresh and (force or token_is_expiring(tok, cfg.refresh_skew_ms)):
        if granola_running():
            print(
                "warning: Granola desktop app is running; refresh tokens rotate "
                "(single-use). Quit Granola or use a separate session to avoid logout.",
                file=sys.stderr,
            )
        if refresh_account_token(cfg, acct):
            save_store(store)
            tok = json.loads(acct["tokens"])

    return tok if passthru else tok["access_token"]


def token_info(cfg: Config, include_secrets: bool = False) -> list[dict]:
    store = read_store(cfg)
    out = []
    for acct in store.accounts:
        tok = json.loads(acct["tokens"])
        obt_ms = int(tok["obtained_at"])
        obtained = datetime.fromtimestamp(obt_ms / 1000, tz=timezone.utc)
        expiry = datetime.fromtimestamp(
            (obt_ms + int(tok["expires_in"]) * 1000) / 1000, tz=timezone.utc
        )
        now = datetime.now(timezone.utc)
        info = {
            "email": acct.get("email"),
            "userId": acct.get("userId"),
            "token_type": tok.get("token_type"),
            "sign_in_method": tok.get("sign_in_method"),
            "obtained_at_utc": obtained.isoformat(),
            "expiry_utc": expiry.isoformat(),
            "expired": now > expiry,
            "expiring_soon": token_is_expiring(tok, cfg.refresh_skew_ms),
            "minutes_left": round((expiry - now).total_seconds() / 60, 1),
        }
        if include_secrets:
            info["access_token"] = tok.get("access_token")
            info["refresh_token"] = tok.get("refresh_token")
        out.append(info)
    return out
