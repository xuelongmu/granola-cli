"""High-level Granola API client."""
from __future__ import annotations

from ._http import base_headers, request
from .auth import get_access_token
from .config import Config
from .routes import resolve_endpoint


class GranolaClient:
    """Call Granola API endpoints with an auto-refreshed bearer token.

    >>> c = GranolaClient()
    >>> c.invoke("get-user-info")
    >>> c.invoke("get-documents", body={"limit": 10})
    """

    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or Config()

    def access_token(self, **kwargs) -> str:
        return get_access_token(self.cfg, **kwargs)

    def resolve(self, endpoint: str) -> str:
        return resolve_endpoint(endpoint, self.cfg)

    def invoke(self, endpoint: str, body=None, method: str = "POST", email: str | None = None,
               no_refresh: bool = False, additional_headers: dict | None = None,
               raw: bool = False):
        token = get_access_token(self.cfg, email=email, no_refresh=no_refresh)
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
