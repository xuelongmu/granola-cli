"""Edit / delete a single note.

⚠️ update-document keys the note as ``id`` (NOT ``document_id``) — sending
``document_id`` returns 400 "Missing document ID". It is a partial PATCH: send
only the fields you want to change.
"""
from __future__ import annotations

from .client import GranolaClient
from .notes import workspace_id


def _ws_headers(client: GranolaClient) -> dict | None:
    ws = workspace_id(client)
    return {"X-Granola-Workspace-Id": ws} if ws else None


def update_note(client: GranolaClient, doc_id: str, **fields) -> dict:
    """Partial PATCH. Accepts e.g. title, notes, notes_plain, notes_markdown, overview.

    Returns { id, ydoc_state, ydoc_resolution }.
    """
    if not fields:
        raise ValueError("update_note: nothing to change (pass at least one field).")
    body = {"id": doc_id, **fields}  # keyed by `id`, not `document_id`
    return client.invoke("update-document", body=body,
                         additional_headers=_ws_headers(client))


def set_title(client: GranolaClient, doc_id: str, title: str) -> dict:
    return update_note(client, doc_id, title=title)


def delete_note(client: GranolaClient, doc_id: str) -> dict:
    """⚠️ PERMANENT hard delete (no soft-delete/undo via this endpoint)."""
    return client.invoke("hard-delete-document", body={"document_id": doc_id},
                         additional_headers=_ws_headers(client))
