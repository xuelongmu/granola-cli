"""High-level Granola API client."""
from __future__ import annotations

from ._http import base_headers, request
from .config import Config
from .routes import resolve_endpoint
from .sources import DesktopStoreSource, TokenSource


class GranolaClient:
    """Call Granola API endpoints with a bearer token from a ``TokenSource``.

    The source (desktop store, session file, or static token) is resolved once and
    handles its own refresh + write-back, so call sites stay auth-agnostic.

    >>> c = GranolaClient()                       # defaults to the desktop store
    >>> c.invoke("get-user-info")
    >>> c.invoke("get-documents", body={"limit": 10})
    """

    def __init__(self, cfg: Config | None = None, source: TokenSource | None = None):
        self.cfg = cfg or Config()
        self.source = source or DesktopStoreSource(self.cfg)

    def access_token(self, force: bool = False) -> str:
        return self.source.access_token(force=force)

    def resolve(self, endpoint: str) -> str:
        return resolve_endpoint(endpoint, self.cfg)

    def invoke(self, endpoint: str, body=None, method: str = "POST",
               additional_headers: dict | None = None, raw: bool = False):
        token = self.source.access_token()
        url = self.resolve(endpoint)
        headers = base_headers(self.cfg, token, additional_headers)
        resp = request(method, url, json_body=body, headers=headers, timeout=self.cfg.timeout)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Granola API '{endpoint}' returned HTTP {resp.status_code}. {resp.text[:500]}"
            )
        if raw:
            return resp.text
        try:
            return resp.json()
        except Exception:
            return resp.text
