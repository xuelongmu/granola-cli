"""Configuration for the Granola API engine."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _default_granola_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Granola"
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Granola"


def _default_app_root() -> Path:
    if sys.platform == "darwin":
        return Path("/Applications/Granola.app/Contents")
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "Programs" / "@granolaelectron"


@dataclass
class Config:
    """Resolves paths and constants for one Granola profile.

    For a *headless second session* (Option B), point ``granola_dir`` at the
    second OS user's ``%APPDATA%\\Granola`` (the process must run as that user so
    DPAPI CurrentUser can unseal the key).
    """

    granola_dir: Path = field(default_factory=_default_granola_dir)
    app_root: Path = field(default_factory=_default_app_root)
    client_version: str = "7.303.0"          # app.asar package.json version
    # X-Granola-Platform (darwin -> macOS, win32 -> Windows)
    platform: str = field(
        default_factory=lambda: "macOS" if sys.platform == "darwin" else "Windows")
    refresh_url: str = "https://api.granola.ai/v1/refresh-access-token"
    refresh_skew_ms: int = 120_000           # app refreshes when <2 min to expiry
    timeout: float = 60.0
    routes_path: Path | None = None

    def __post_init__(self) -> None:
        self.granola_dir = Path(self.granola_dir)
        self.app_root = Path(self.app_root)
        if self.routes_path is not None:
            self.routes_path = Path(self.routes_path)
