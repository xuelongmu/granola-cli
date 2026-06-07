"""Token-source + session-file tests — no network, no keystore.

The refresh endpoint is stubbed by monkeypatching ``granola.auth.request`` to
return a constructed ``httpx.Response``; the desktop store is stubbed by
monkeypatching ``read_store``/``save_store``. That lets us exercise refresh,
write-back, 0600 perms, locking re-read, and precedence as pure logic.

Run: `uv run pytest tests/test_sources.py`  (or `python -m pytest`).
"""
from __future__ import annotations

import json
import os
import stat
import sys
import time

import httpx
import pytest

from granola import auth, sources
from granola.auth import RefreshRevoked, refresh_exchange, token_is_expiring
from granola.config import Config
from granola.sources import (
    DesktopStoreSource,
    SessionFileSource,
    StaticTokenSource,
    create_session_file,
    resolve_source,
)
from granola.store import Store


def _now_ms() -> int:
    return int(time.time() * 1000)


def make_tok(fresh: bool = True, **over) -> dict:
    tok = {
        "access_token": "old.jwt",
        "refresh_token": "r1",
        "token_type": "Bearer",
        "expires_in": 3600,
        "obtained_at": _now_ms() if fresh else _now_ms() - 7200_000,  # 2h ago -> expired
        "sign_in_method": "CrossAppAuth",
        "session_id": "sess-1",
    }
    tok.update(over)
    return tok


def stub_refresh(monkeypatch, *, status=200, payload=None):
    """Point granola.auth.request at a canned httpx.Response."""
    payload = payload if payload is not None else {
        "access_token": "new.jwt", "expires_in": 3600, "refresh_token": "r2",
    }
    def fake_request(method, url, *, json_body=None, headers=None, timeout=60.0):
        return httpx.Response(status, json=payload)
    monkeypatch.setattr(auth, "request", fake_request)


def forbid_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network should not be called")
    monkeypatch.setattr(auth, "request", boom)


# --- refresh_exchange ----------------------------------------------------------

def test_refresh_exchange_rotates_tokens(monkeypatch):
    stub_refresh(monkeypatch)
    before = make_tok()
    new = refresh_exchange(Config(), before)
    assert new["access_token"] == "new.jwt"
    assert new["refresh_token"] == "r2"               # rotated
    assert new["obtained_at"] >= before["obtained_at"]
    assert before["access_token"] == "old.jwt"        # input not mutated


def test_refresh_exchange_keeps_old_refresh_when_not_returned(monkeypatch):
    stub_refresh(monkeypatch, payload={"access_token": "new.jwt", "expires_in": 3600})
    new = refresh_exchange(Config(), make_tok())
    assert new["refresh_token"] == "r1"               # server didn't rotate -> keep


def test_refresh_exchange_401_raises_revoked(monkeypatch):
    stub_refresh(monkeypatch, status=401, payload={"error": "invalid_grant"})
    with pytest.raises(RefreshRevoked):
        refresh_exchange(Config(), make_tok())


# --- StaticTokenSource ---------------------------------------------------------

def test_static_source_returns_and_cannot_refresh():
    s = StaticTokenSource("bearer-xyz")
    assert s.access_token() == "bearer-xyz"
    with pytest.raises(RuntimeError):
        s.access_token(force=True)
    assert s.status()[0] == {"source": "static", "refreshable": False}
    assert s.status(include_secrets=True)[0]["access_token"] == "bearer-xyz"


# --- SessionFileSource ---------------------------------------------------------

def write_session(path, tok):
    path.write_text(json.dumps({"schema_version": 1, **tok}), encoding="utf-8")


def test_session_fresh_token_no_refresh(tmp_path, monkeypatch):
    forbid_network(monkeypatch)
    p = tmp_path / "session.json"
    write_session(p, make_tok(fresh=True))
    src = SessionFileSource(Config(), p)
    assert src.access_token() == "old.jwt"            # fresh -> no network


def test_session_expiring_refreshes_and_writes_back(tmp_path, monkeypatch):
    stub_refresh(monkeypatch)
    p = tmp_path / "session.json"
    write_session(p, make_tok(fresh=False))
    src = SessionFileSource(Config(), p)
    assert src.access_token() == "new.jwt"
    on_disk = json.loads(p.read_text())
    assert on_disk["access_token"] == "new.jwt"       # persisted
    assert on_disk["refresh_token"] == "r2"           # rotation persisted
    assert on_disk["schema_version"] == 1             # existing keys preserved by merge


def test_session_no_refresh_flag_returns_stale(tmp_path, monkeypatch):
    forbid_network(monkeypatch)
    p = tmp_path / "session.json"
    write_session(p, make_tok(fresh=False))
    src = SessionFileSource(Config(), p, no_refresh=True)
    assert src.access_token() == "old.jwt"            # stale but no refresh attempted


def test_session_force_refresh_overrides_no_refresh(tmp_path, monkeypatch):
    stub_refresh(monkeypatch)
    p = tmp_path / "session.json"
    write_session(p, make_tok(fresh=True))
    src = SessionFileSource(Config(), p, no_refresh=True)
    assert src.access_token(force=True) == "new.jwt"  # explicit refresh wins


def test_session_revoked_gives_headless_help(tmp_path, monkeypatch):
    stub_refresh(monkeypatch, status=401, payload={"error": "invalid_grant"})
    p = tmp_path / "session.json"
    write_session(p, make_tok(fresh=False))
    src = SessionFileSource(Config(), p)
    with pytest.raises(RefreshRevoked) as ei:
        src.access_token()
    assert "auth export" in str(ei.value)             # re-bootstrap guidance


def test_session_missing_file_errors(tmp_path):
    src = SessionFileSource(Config(), tmp_path / "nope.json")
    with pytest.raises(FileNotFoundError):
        src.access_token()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX perms only")
def test_session_written_0600(tmp_path, monkeypatch):
    stub_refresh(monkeypatch)
    p = tmp_path / "session.json"
    write_session(p, make_tok(fresh=False))
    os.chmod(p, 0o644)                                 # start world-readable
    SessionFileSource(Config(), p).access_token()      # triggers atomic rewrite
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600


def test_session_status_no_secrets(tmp_path):
    p = tmp_path / "session.json"
    write_session(p, make_tok(fresh=True, email="a@b.co", userId="u1"))
    info = SessionFileSource(Config(), p).status()[0]
    assert info["source"] == "session" and info["email"] == "a@b.co"
    assert "access_token" not in info and "refresh_token" not in info
    assert info["refreshable"] is True


# --- DesktopStoreSource (store stubbed) ----------------------------------------

def fake_store(tok):
    acct = {"email": "a@b.co", "userId": "u1", "tokens": json.dumps(tok)}
    return Store(dek=b"", outer={}, accounts=[acct], enc_path=tmp_enc(), kind="macos")


def tmp_enc():
    import pathlib
    return pathlib.Path("/tmp/granola-test.enc")


def test_desktop_refreshes_and_saves(monkeypatch):
    stub_refresh(monkeypatch)
    monkeypatch.setattr(sources, "granola_running", lambda: False)
    store = fake_store(make_tok(fresh=False))
    saved = []
    monkeypatch.setattr(sources, "read_store", lambda cfg: store)
    monkeypatch.setattr(sources, "save_store", lambda s: saved.append(s))
    tok = DesktopStoreSource(Config()).access_token()
    assert tok == "new.jwt"
    assert saved == [store]                            # wrote back
    assert json.loads(store.accounts[0]["tokens"])["access_token"] == "new.jwt"


def test_desktop_fresh_token_no_save(monkeypatch):
    forbid_network(monkeypatch)
    monkeypatch.setattr(sources, "granola_running", lambda: False)
    store = fake_store(make_tok(fresh=True))
    monkeypatch.setattr(sources, "read_store", lambda cfg: store)
    monkeypatch.setattr(sources, "save_store",
                        lambda s: (_ for _ in ()).throw(AssertionError("should not save")))
    assert DesktopStoreSource(Config()).access_token() == "old.jwt"


# --- create_session_file -------------------------------------------------------

def test_create_session_file_shape_and_perms(tmp_path, monkeypatch):
    forbid_network(monkeypatch)                        # token is fresh -> no refresh
    monkeypatch.setattr(sources, "granola_running", lambda: False)
    store = fake_store(make_tok(fresh=True))
    monkeypatch.setattr(sources, "read_store", lambda cfg: store)
    out = create_session_file(Config(), tmp_path / "s.json")
    data = json.loads(out.read_text())
    assert data["schema_version"] == 1
    assert data["access_token"] == "old.jwt"
    assert data["refresh_token"] == "r1"
    assert data["email"] == "a@b.co" and data["userId"] == "u1"
    assert data["session_id"] == "sess-1"
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(out).st_mode) == 0o600


def test_create_session_file_bearer_only(tmp_path, monkeypatch):
    forbid_network(monkeypatch)
    monkeypatch.setattr(sources, "granola_running", lambda: False)
    monkeypatch.setattr(sources, "read_store", lambda cfg: fake_store(make_tok(fresh=True)))
    out = create_session_file(Config(), tmp_path / "s.json", include_refresh_token=False)
    data = json.loads(out.read_text())
    assert "refresh_token" not in data                 # opt-out honored
    assert data["access_token"] == "old.jwt"


# --- resolve_source precedence -------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("GRANOLA_SESSION", raising=False)
    monkeypatch.delenv("GRANOLA_ACCESS_TOKEN", raising=False)


def test_resolve_default_is_desktop():
    assert isinstance(resolve_source(Config()), DesktopStoreSource)


def test_resolve_session_flag():
    s = resolve_source(Config(), session="/tmp/s.json")
    assert isinstance(s, SessionFileSource)


def test_resolve_static_flag():
    assert isinstance(resolve_source(Config(), access_token="t"), StaticTokenSource)


def test_resolve_session_env(monkeypatch):
    monkeypatch.setenv("GRANOLA_SESSION", "/tmp/s.json")
    assert isinstance(resolve_source(Config()), SessionFileSource)


def test_resolve_prefers_session_over_static_and_warns(monkeypatch, capsys):
    monkeypatch.setenv("GRANOLA_ACCESS_TOKEN", "t")
    monkeypatch.setenv("GRANOLA_SESSION", "/tmp/s.json")
    s = resolve_source(Config())
    assert isinstance(s, SessionFileSource)            # refreshable wins
    assert "preferring the session" in capsys.readouterr().err


def test_resolve_flag_beats_env_within_kind(monkeypatch):
    monkeypatch.setenv("GRANOLA_SESSION", "/tmp/env.json")
    s = resolve_source(Config(), session="/tmp/flag.json")
    assert isinstance(s, SessionFileSource) and str(s.path) == "/tmp/flag.json"


def test_resolve_email_with_session_errors():
    with pytest.raises(SystemExit):
        resolve_source(Config(), email="a@b.co", session="/tmp/s.json")


def test_resolve_email_with_static_errors():
    with pytest.raises(SystemExit):
        resolve_source(Config(), email="a@b.co", access_token="t")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
