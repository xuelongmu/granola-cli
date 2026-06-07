"""Token sources and precedence resolution.

A *source* answers one question — "give me a valid bearer token" — and knows how
to refresh + persist if it can. There are three:

* ``DesktopStoreSource`` — the local Granola desktop credential store (the
  Keychain/DPAPI chain). Refresh writes back into the encrypted store.
* ``SessionFileSource`` — a portable JSON file. This is the headless path:
  refresh writes back to the file under a lock with an atomic, owner-only rename.
* ``StaticTokenSource`` — a bare bearer token (CI / one-off). Cannot refresh.

``resolve_source`` picks one from flags + environment. A refreshable session
always wins over a static token (a static token silently goes stale), and we
warn when both are present so the choice is never invisible.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from ._http import granola_running
from .auth import (
    RefreshRevoked,
    format_token_status,
    refresh_exchange,
    select_account,
    token_is_expiring,
)
from .config import Config
from .store import compact, read_store, save_store

SCHEMA_VERSION = 1

DESKTOP_REVOKED_HELP = (
    "Refresh token revoked — sign in again via the Granola desktop app."
)
SESSION_REVOKED_HELP = (
    "This session's refresh token is dead (rotated away or revoked).\n"
    "Re-bootstrap on your macOS/Windows machine:\n"
    "  1. Sign in to the Granola desktop app.\n"
    "  2. Run:  granola auth export <PATH>\n"
    "  3. Sign OUT of the desktop app so this session owns the refresh token "
    "(otherwise the app and this session fight over the single-use token).\n"
    "Then copy <PATH> back to this machine."
)


# --- the source interface + implementations -----------------------------------

class TokenSource:
    refreshable = False

    def access_token(self, force: bool = False) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    def status(self, include_secrets: bool = False) -> list[dict]:  # pragma: no cover
        raise NotImplementedError


class StaticTokenSource(TokenSource):
    """A bare bearer token (--access-token / GRANOLA_ACCESS_TOKEN). Never refreshes."""
    refreshable = False

    def __init__(self, token: str):
        self._token = token

    def access_token(self, force: bool = False) -> str:
        if force:
            raise RuntimeError(
                "A static access token cannot be refreshed. Use a session file "
                "(--session / GRANOLA_SESSION) for refreshable auth."
            )
        return self._token

    def status(self, include_secrets: bool = False) -> list[dict]:
        info = {"source": "static", "refreshable": False}
        if include_secrets:
            info["access_token"] = self._token
        return [info]


class DesktopStoreSource(TokenSource):
    """The local Granola desktop credential store (Keychain/DPAPI → DEK → cred file)."""
    refreshable = True

    def __init__(self, cfg: Config, email: str | None = None, no_refresh: bool = False):
        self.cfg = cfg
        self.email = email
        self.no_refresh = no_refresh

    def access_token(self, force: bool = False) -> str:
        store = read_store(self.cfg)
        acct = select_account(store, self.email)
        tok = json.loads(acct["tokens"])
        if force or (not self.no_refresh and token_is_expiring(tok, self.cfg.refresh_skew_ms)):
            if granola_running():
                print(
                    "warning: Granola desktop app is running; refresh tokens rotate "
                    "(single-use). Quit Granola or use an exported session to avoid logout.",
                    file=sys.stderr,
                )
            try:
                new = refresh_exchange(self.cfg, tok)
            except RefreshRevoked as exc:
                raise RefreshRevoked(DESKTOP_REVOKED_HELP) from exc
            acct["tokens"] = compact(new)
            acct["savedAt"] = new["obtained_at"]
            save_store(store)
            tok = new
        return tok["access_token"]

    def status(self, include_secrets: bool = False) -> list[dict]:
        store = read_store(self.cfg)
        out = []
        for acct in store.accounts:
            tok = json.loads(acct["tokens"])
            info = {
                "source": "desktop",
                "refreshable": bool(tok.get("refresh_token")),
                "email": acct.get("email"),
                "userId": acct.get("userId"),
            }
            info.update(format_token_status(tok, self.cfg.refresh_skew_ms, include_secrets))
            out.append(info)
        return out


class SessionFileSource(TokenSource):
    """A portable, refreshable session JSON file — the headless / CI path.

    Refresh is concurrency-safe: lock a sidecar file, *re-read* (a peer worker or
    the desktop app may have rotated already), refresh only if still expiring, and
    write back atomically with owner-only permissions.
    """
    refreshable = True

    def __init__(self, cfg: Config, path, no_refresh: bool = False):
        self.cfg = cfg
        self.path = Path(path)
        self.no_refresh = no_refresh

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"Session file not found: {self.path}") from exc
        if "access_token" not in data:
            raise ValueError(f"{self.path} is not a valid session file (no access_token).")
        return data

    def _wants_refresh(self, data: dict, force: bool) -> bool:
        return force or (not self.no_refresh and token_is_expiring(data, self.cfg.refresh_skew_ms))

    def access_token(self, force: bool = False) -> str:
        data = self._read()
        if not self._wants_refresh(data, force):
            return data["access_token"]
        with _FileLock(self.path):
            data = self._read()  # re-read under lock; a peer may have just rotated
            if not self._wants_refresh(data, force):
                return data["access_token"]
            try:
                new = refresh_exchange(self.cfg, data)
            except RefreshRevoked as exc:
                raise RefreshRevoked(SESSION_REVOKED_HELP) from exc
            merged = {**data, **new}
            _write_session(self.path, merged)
            return merged["access_token"]

    def status(self, include_secrets: bool = False) -> list[dict]:
        data = self._read()
        info = {
            "source": "session",
            "path": str(self.path),
            "refreshable": bool(data.get("refresh_token")) and not self.no_refresh,
            "email": data.get("email"),
            "userId": data.get("userId"),
        }
        info.update(format_token_status(data, self.cfg.refresh_skew_ms, include_secrets))
        return [info]


# --- session-file plumbing -----------------------------------------------------

class _FileLock:
    """Cross-platform exclusive lock held on a sidecar ``<name>.lock`` file.

    Locking the sidecar (not the session file itself) keeps the atomic rename of
    the real file unobstructed. fcntl on POSIX (the headless target), msvcrt on
    Windows.
    """

    def __init__(self, target: Path):
        self.lock_path = Path(target).with_name(Path(target).name + ".lock")
        self._fh = None

    def __enter__(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.lock_path, "a+")
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(self._fh.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        try:
            if sys.platform == "win32":
                import msvcrt
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()


def _write_session(path, data: dict) -> Path:
    """Atomically write a session file, owner-only from byte zero.

    ``tempfile.mkstemp`` creates the temp at mode 0600 on POSIX *before* any
    secret is written, then ``os.replace`` swaps it in atomically — no window
    where the token sits at umask perms. On Windows there is no 0600; the file
    inherits the directory ACL (documented limitation).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)  # atomic within the same directory
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def create_session_file(cfg: Config, path, *, email: str | None = None,
                        include_refresh_token: bool = True, refresh: bool = True) -> Path:
    """Write a minimal refreshable session file from the desktop credential store.

    This is the only place the desktop secrets leave the encrypted store, and it
    writes the *minimum* needed to use + refresh the session — not a full dump.
    """
    store = read_store(cfg)
    acct = select_account(store, email)
    tok = json.loads(acct["tokens"])

    if refresh and token_is_expiring(tok, cfg.refresh_skew_ms):
        if granola_running():
            print(
                "warning: Granola desktop app is running; this export rotates the "
                "single-use refresh token. Sign OUT of the desktop app after exporting "
                "so the session owns the token.",
                file=sys.stderr,
            )
        new = refresh_exchange(cfg, tok)
        acct["tokens"] = compact(new)
        acct["savedAt"] = new["obtained_at"]
        save_store(store)
        tok = new

    session = {
        "schema_version": SCHEMA_VERSION,
        "access_token": tok["access_token"],
        "token_type": tok.get("token_type", "Bearer"),
        "expires_in": tok["expires_in"],   # expiry = obtained_at(ms) + expires_in(s)
        "obtained_at": tok["obtained_at"],
        "sign_in_method": tok.get("sign_in_method"),
        "email": acct.get("email"),
        "userId": acct.get("userId"),
    }
    if tok.get("session_id"):
        session["session_id"] = tok["session_id"]
    if include_refresh_token and tok.get("refresh_token"):
        session["refresh_token"] = tok["refresh_token"]
    return _write_session(path, session)


# --- precedence ----------------------------------------------------------------

def resolve_source(cfg: Config, *, email: str | None = None, session: str | None = None,
                   access_token: str | None = None, no_refresh: bool = False) -> TokenSource:
    """Resolve the active token source from flags + environment.

    Precedence: a refreshable session (``--session`` / ``GRANOLA_SESSION``) beats a
    static token (``--access-token`` / ``GRANOLA_ACCESS_TOKEN``); within each kind a
    flag beats its env var; the desktop store is the fallback. When a static token
    and a session are *both* present we prefer the session and warn, so a stray
    ``GRANOLA_ACCESS_TOKEN`` can't silently shadow a session and go stale.
    """
    static = access_token or os.environ.get("GRANOLA_ACCESS_TOKEN")
    sess = session or os.environ.get("GRANOLA_SESSION")

    if static and sess:
        print(
            "warning: both a static access token and a refreshable session are set; "
            "preferring the session (the static access token is ignored).",
            file=sys.stderr,
        )
        static = None

    if sess:
        if email:
            raise SystemExit(
                "--email selects a desktop account and can't be combined with a session file."
            )
        return SessionFileSource(cfg, sess, no_refresh=no_refresh)
    if static:
        if email:
            raise SystemExit(
                "--email selects a desktop account and can't be combined with --access-token."
            )
        return StaticTokenSource(static)
    return DesktopStoreSource(cfg, email=email, no_refresh=no_refresh)
