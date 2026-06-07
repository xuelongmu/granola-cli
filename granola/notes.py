"""Typed read operations for a single note (and listing).

Thin, verified wrappers over the internal API. Shapes confirmed live against
app v7.303.0 — see the Granola API reference for details.
"""
from __future__ import annotations

from .client import GranolaClient


def list_notes(client: GranolaClient, limit: int = 20) -> list[dict]:
    """Recent notes (full Document records). Uses /v2/get-documents."""
    resp = client.invoke("get-documents-v2", body={"limit": limit})
    if isinstance(resp, dict):
        return resp.get("docs") or resp.get("documents") or []
    return []


def get_note(client: GranolaClient, doc_id: str) -> dict | None:
    """The full ~50-field record for one note (the real 'get one note').

    Keyed by ``document_ids`` (plural) — get-documents-batch.
    """
    resp = client.invoke("get-documents-batch", body={"document_ids": [doc_id]})
    docs = resp.get("docs") if isinstance(resp, dict) else None
    return docs[0] if docs else None


def get_metadata(client: GranolaClient, doc_id: str) -> dict:
    """Creator / attendees / conferencing / url."""
    return client.invoke("get-document-metadata", body={"document_id": doc_id})


def get_transcript(client: GranolaClient, doc_id: str) -> list[dict]:
    """Transcript as an ordered list of segments."""
    resp = client.invoke("get-document-transcript", body={"document_id": doc_id})
    return resp if isinstance(resp, list) else []


def get_panels(client: GranolaClient, doc_id: str) -> list[dict]:
    """AI summary panels (ProseMirror content + generated lines)."""
    resp = client.invoke("get-document-panels", body={"document_id": doc_id})
    if isinstance(resp, list):
        return resp
    return [resp] if resp else []


def check_access(client: GranolaClient, doc_id: str) -> dict:
    """{ requiresLogin, hasAccess, role, workspace_id } for the current user."""
    return client.invoke("check-document-access", body={"document_id": doc_id})


def workspace_id(client: GranolaClient) -> str | None:
    """The user's active workspace id, fetched once and cached on the client.

    Writes attach this as ``X-Granola-Workspace-Id`` to mirror the desktop app.
    """
    ws = getattr(client, "_ws_id_cache", "unset")
    if ws == "unset":
        try:
            ws = (client.invoke("get-user-info").get("workspace_ids") or [None])[0]
        except Exception:
            ws = None
        client._ws_id_cache = ws
    return ws


def transcript_to_markdown(segments: list[dict]) -> str:
    """Render transcript segments to readable markdown."""
    lines: list[str] = []
    last_speaker = None
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        speaker = seg.get("detected_speaker_name") or seg.get("source") or ""
        if speaker and speaker != last_speaker:
            lines.append(f"\n**{speaker}**")
            last_speaker = speaker
        lines.append(text)
    return "\n".join(lines).strip() + "\n"
