"""Sync notes into the local SQLite store (+ optional markdown mirror).

Incremental: a note is re-fetched only when its ``updated_at`` changed. The
markdown body comes from the note record itself (``notes_markdown``); the
transcript is an extra per-note call, so it can be skipped for speed.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from pathlib import Path

from . import db
from .client import GranolaClient
from .notes import get_transcript, list_notes, transcript_to_markdown

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _slug(title: str | None, uuid: str) -> str:
    base = _SAFE.sub("-", (title or "untitled").strip()).strip("-").lower() or "untitled"
    return f"{base[:60]}-{uuid[:8]}.md"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sync(
    client: GranolaClient,
    db_path: str | Path,
    *,
    limit: int = 200,
    with_transcript: bool = True,
    out_dir: str | Path | None = None,
    force: bool = False,
) -> dict:
    """Pull up to ``limit`` recent notes into SQLite. Returns a summary dict."""
    con = db.connect(db_path)
    seen = {} if force else db.existing_updated_at(con)
    docs = list_notes(client, limit=limit)

    written, skipped, errors = 0, 0, 0
    out = Path(out_dir) if out_dir else None
    if out:
        out.mkdir(parents=True, exist_ok=True)

    for d in docs:
        uuid = d.get("id")
        if not uuid or d.get("deleted_at"):
            continue
        updated = d.get("updated_at") or ""
        if not force and seen.get(uuid) == updated:
            skipped += 1
            continue
        try:
            transcript = ""
            if with_transcript:
                transcript = transcript_to_markdown(get_transcript(client, uuid))
            rec = {
                "uuid": uuid,
                "title": d.get("title"),
                "created_at": d.get("created_at"),
                "updated_at": updated,
                "workspace_id": d.get("workspace_id"),
                "markdown": d.get("notes_markdown") or d.get("notes_plain") or "",
                "transcript": transcript,
                "synced_at": _now_iso(),
            }
            db.upsert_note(con, rec)
            if out:
                _write_markdown(out, rec)
            written += 1
        except Exception:  # noqa: BLE001 - count and continue
            errors += 1
        time.sleep(0)  # cooperative; keep simple/no rate limiter for now

    con.commit()
    total = db.count(con)
    con.close()
    return {"written": written, "skipped": skipped, "errors": errors,
            "total_in_db": total, "db": str(db_path),
            "out_dir": str(out) if out else None}


def _write_markdown(out: Path, rec: dict) -> None:
    fm = (
        f"---\ntitle: {rec.get('title') or ''}\nid: {rec['uuid']}\n"
        f"created_at: {rec.get('created_at') or ''}\nupdated_at: {rec.get('updated_at') or ''}\n---\n\n"
    )
    parts = [fm, f"# {rec.get('title') or 'Untitled'}\n", rec.get("markdown") or ""]
    if rec.get("transcript"):
        parts += ["\n\n## Transcript\n", rec["transcript"]]
    (out / _slug(rec.get("title"), rec["uuid"])).write_text(
        "\n".join(parts), encoding="utf-8"
    )
