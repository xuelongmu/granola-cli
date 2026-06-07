"""Endpoint-name -> URL resolution.

Order of resolution: in-memory cache -> cfg.routes_path -> bundled package data
-> CWD/granola-api-routes.json -> parse app.asar (and that result is cached).
"""
from __future__ import annotations

import json
import re
import sys
from importlib import resources
from pathlib import Path

from .config import Config

_ROUTE_RE = re.compile(
    r'"([a-zA-Z0-9\-]+)":`(https://[a-zA-Z0-9.\-]*api\.granola\.ai/v1/[a-zA-Z0-9\-/]+)`'
)
_cache: dict | None = None


def _bundled() -> dict | None:
    try:
        res = resources.files("granola").joinpath("granola-api-routes.json")
        with resources.as_file(res) as path:
            if path.exists():
                return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _parse_asar(cfg: Config) -> dict:
    asar = cfg.app_root / "resources" / "app.asar"
    text = asar.read_bytes().decode("latin-1")
    return {m.group(1): m.group(2) for m in _ROUTE_RE.finditer(text)}


def load_routes(cfg: Config | None = None, refresh: bool = False) -> dict:
    global _cache
    if _cache is not None and not refresh:
        return _cache
    cfg = cfg or Config()
    if not refresh:
        if cfg.routes_path and Path(cfg.routes_path).exists():
            _cache = json.loads(Path(cfg.routes_path).read_text(encoding="utf-8"))
            return _cache
        bundled = _bundled()
        if bundled:
            _cache = bundled
            return _cache
        cwd = Path.cwd() / "granola-api-routes.json"
        if cwd.exists():
            _cache = json.loads(cwd.read_text(encoding="utf-8"))
            return _cache
    _cache = _parse_asar(cfg)
    return _cache


def resolve_endpoint(endpoint: str, cfg: Config | None = None) -> str:
    if endpoint.startswith(("http://", "https://")):
        return endpoint
    routes = load_routes(cfg)
    if endpoint in routes:
        return routes[endpoint]
    print(
        f"warning: endpoint '{endpoint}' not in route map; "
        f"assuming https://api.granola.ai/v1/{endpoint}",
        file=sys.stderr,
    )
    return f"https://api.granola.ai/v1/{endpoint}"
