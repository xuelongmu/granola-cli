"""Dump decrypted credentials (nested JSON expanded) to a file. SECRET output."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .auth import refresh_account_token, token_is_expiring
from .config import Config
from .store import read_store, save_store


def export_credentials(cfg: Config, path: str, refresh: bool = False) -> str:
    store = read_store(cfg)
    if refresh:
        changed = False
        for acct in store.accounts:
            tok = json.loads(acct["tokens"])
            if token_is_expiring(tok, cfg.refresh_skew_ms):
                refresh_account_token(cfg, acct)
                changed = True
        if changed:
            save_store(store)

    accounts_out = []
    for acct in store.accounts:
        tok = json.loads(acct["tokens"])
        try:
            user_info = json.loads(acct["userInfo"])
        except Exception:
            user_info = acct.get("userInfo")
        obt_ms = int(tok["obtained_at"])
        obtained = datetime.fromtimestamp(obt_ms / 1000, tz=timezone.utc)
        expiry = datetime.fromtimestamp(
            (obt_ms + int(tok["expires_in"]) * 1000) / 1000, tz=timezone.utc
        )
        accounts_out.append({
            "userId": acct.get("userId"),
            "email": acct.get("email"),
            "tokens": tok,
            "obtained_at_utc": obtained.isoformat(),
            "expiry_utc": expiry.isoformat(),
            "userInfo": user_info,
        })

    dump = {
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": str(store.enc_path),
        "note": "Decrypted Granola credentials. SECRET - do not commit or share.",
        "accounts": accounts_out,
    }
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dump, indent=2, ensure_ascii=False), encoding="utf-8")
    return f"Wrote {out} ({out.stat().st_size} bytes)"
