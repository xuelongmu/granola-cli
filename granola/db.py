"""Local SQLite store + FTS5 full-text index for synced notes.

Zero extra dependencies — stdlib ``sqlite3`` with the FTS5 module (compiled into
CPython's bundled SQLite). Semantic search/TUI are intentionally out of scope
(use muesli for those); this is the cheap keyword tier.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    uuid         TEXT PRIMARY KEY,
    title        TEXT,
    created_at   TEXT,
    updated_at   TEXT,
    workspace_id TEXT,
    markdown     TEXT,
    transcript   TEXT,
    synced_at    TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    uuid UNINDEXED,
    title,
    body,
    tokenize = 'porter unicode61'
);
"""


def fts5_available() -> bool:
    try:
        con = sqlite3.connect(":memory:")
        con.execute("CREATE VIRTUAL TABLE t USING fts5(x);")
        con.close()
        return True
    except sqlite3.OperationalError:
        return False


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def upsert_note(con: sqlite3.Connection, rec: dict) -> None:
    """Insert/replace a note row and refresh its FTS entry."""
    con.execute(
        """INSERT INTO notes (uuid,title,created_at,updated_at,workspace_id,markdown,transcript,synced_at)
           VALUES (:uuid,:title,:created_at,:updated_at,:workspace_id,:markdown,:transcript,:synced_at)
           ON CONFLICT(uuid) DO UPDATE SET
             title=excluded.title, created_at=excluded.created_at, updated_at=excluded.updated_at,
             workspace_id=excluded.workspace_id, markdown=excluded.markdown,
             transcript=excluded.transcript, synced_at=excluded.synced_at""",
        rec,
    )
    con.execute("DELETE FROM notes_fts WHERE uuid = ?", (rec["uuid"],))
    body = "\n".join(p for p in (rec.get("markdown"), rec.get("transcript")) if p)
    con.execute(
        "INSERT INTO notes_fts (uuid,title,body) VALUES (?,?,?)",
        (rec["uuid"], rec.get("title") or "", body),
    )


def existing_updated_at(con: sqlite3.Connection) -> dict[str, str]:
    """Map uuid -> stored updated_at, for incremental sync."""
    return {r["uuid"]: r["updated_at"] for r in con.execute("SELECT uuid, updated_at FROM notes")}


def count(con: sqlite3.Connection) -> int:
    return con.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
