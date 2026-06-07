"""Full-text keyword search over the synced SQLite store (FTS5)."""
from __future__ import annotations

import sqlite3
from pathlib import Path


def search(db_path: str | Path, query: str, limit: int = 20) -> list[dict]:
    """Return ranked matches: [{ uuid, title, snippet, updated_at }].

    Uses FTS5 ``MATCH`` + ``rank``. The query supports FTS5 syntax
    (``epilepsy AND seizure``, ``"exact phrase"``, ``risk*``).
    """
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"No synced store at {path} — run `granola sync` first.")
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """
            SELECT f.uuid AS uuid,
                   f.title AS title,
                   snippet(notes_fts, 2, '[', ']', ' … ', 12) AS snippet,
                   n.updated_at AS updated_at
            FROM notes_fts f
            JOIN notes n ON n.uuid = f.uuid
            WHERE notes_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        raise ValueError(f"Bad FTS5 query {query!r}: {exc}") from exc
    finally:
        con.close()
    return [dict(r) for r in rows]
