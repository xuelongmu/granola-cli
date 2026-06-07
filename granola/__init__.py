"""Granola — decrypt on-disk credentials, auto-refresh, and drive the documented internal API.

Quick start::

    from granola import GranolaClient, notes, sharing
    client = GranolaClient()
    me = client.invoke("get-user-info")
    recent = notes.list_notes(client, limit=10)
    sharing.add_collaborator(client, "<doc-id>", "person@example.com", name="Person")

Headless / portable auth::

    from granola import GranolaClient, SessionFileSource, Config
    cfg = Config()
    client = GranolaClient(cfg, source=SessionFileSource(cfg, "session.json"))
"""
from __future__ import annotations

from . import editing, notes, sharing
from .auth import (
    RefreshRevoked,
    format_token_status,
    refresh_exchange,
    token_is_expiring,
)
from .client import GranolaClient
from .config import Config
from .routes import load_routes, resolve_endpoint
from .sources import (
    DesktopStoreSource,
    SessionFileSource,
    StaticTokenSource,
    TokenSource,
    create_session_file,
    resolve_source,
)
from .store import get_dek, read_store, save_store

__version__ = "0.1.0"
__all__ = [
    "Config",
    "GranolaClient",
    "TokenSource",
    "DesktopStoreSource",
    "SessionFileSource",
    "StaticTokenSource",
    "resolve_source",
    "create_session_file",
    "refresh_exchange",
    "format_token_status",
    "token_is_expiring",
    "RefreshRevoked",
    "load_routes",
    "resolve_endpoint",
    "read_store",
    "save_store",
    "get_dek",
    "notes",
    "sharing",
    "editing",
]
