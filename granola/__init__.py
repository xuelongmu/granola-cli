"""Granola — decrypt on-disk credentials, auto-refresh, and drive the documented internal API.

Quick start::

    from granola import GranolaClient, notes, sharing
    client = GranolaClient()
    me = client.invoke("get-user-info")
    recent = notes.list_notes(client, limit=10)
    sharing.add_collaborator(client, "<doc-id>", "person@example.com", name="Person")
"""
from __future__ import annotations

from . import editing, notes, sharing
from .auth import get_access_token, refresh_account_token, token_info, token_is_expiring
from .client import GranolaClient
from .config import Config
from .export import export_credentials
from .routes import load_routes, resolve_endpoint
from .store import get_dek, read_store, save_store

__version__ = "0.1.0"
__all__ = [
    "Config",
    "GranolaClient",
    "get_access_token",
    "token_info",
    "token_is_expiring",
    "refresh_account_token",
    "load_routes",
    "resolve_endpoint",
    "read_store",
    "save_store",
    "get_dek",
    "export_credentials",
    "notes",
    "sharing",
    "editing",
]
