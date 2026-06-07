"""HTTP helpers: base headers + redirect-safe request via httpx."""
from __future__ import annotations

import subprocess
import sys

import httpx


def base_headers(cfg, access_token: str | None = None, additional: dict | None = None) -> dict:
    headers = {
        "X-Client-Version": cfg.client_version,
        "X-Granola-Platform": cfg.platform,
        "Accept": "application/json",
        "User-Agent": f"Granola/{cfg.client_version}",
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    if additional:
        headers.update(additional)
    return headers


def request(method: str, url: str, *, json_body=None, headers: dict | None = None,
            timeout: float = 60.0) -> httpx.Response:
    # follow_redirects=True keeps the POST body across 307/308 (httpx, unlike the
    # old PowerShell Invoke-RestMethod, does this correctly).
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        return client.request(method.upper(), url, json=json_body, headers=headers)


def granola_running() -> bool:
    """Best-effort check whether the desktop app is running (Windows/macOS)."""
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Granola.exe", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            return "Granola.exe" in out.stdout
        if sys.platform == "darwin":
            out = subprocess.run(
                ["/usr/bin/pgrep", "-x", "Granola"],
                capture_output=True, text=True, timeout=5,
            )
            return out.returncode == 0 and bool(out.stdout.strip())
    except Exception:
        return False
    return False
