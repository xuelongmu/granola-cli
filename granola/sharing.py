"""Collaborator / access operations for a note (and folder cascade).

⚠️ Verified-shape gotchas baked in here:
  - add-users-to-document wants ``names`` as an ``{email: name}`` OBJECT MAP
    (an array makes the server 500).
  - the doc is keyed by ``document_id`` here (but by ``id`` in update-document).
  - role is the string "OWNER" | "COLLABORATOR" | "VIEWER".
"""
from __future__ import annotations

from .client import GranolaClient
from .notes import workspace_id

ROLES = {
    "owner": "OWNER",
    "collaborator": "COLLABORATOR",
    "collab": "COLLABORATOR",
    "viewer": "VIEWER",
    "view": "VIEWER",
}


def normalize_role(role: str) -> str:
    key = (role or "").strip().lower()
    if key in ROLES:
        return ROLES[key]
    upper = (role or "").strip().upper()
    if upper in ("OWNER", "COLLABORATOR", "VIEWER"):
        return upper
    raise ValueError(f"Unknown role '{role}' (use owner|collaborator|viewer).")


def _ws_headers(client: GranolaClient) -> dict | None:
    ws = workspace_id(client)
    return {"X-Granola-Workspace-Id": ws} if ws else None


def list_collaborators(client: GranolaClient, doc_id: str) -> list[dict]:
    """Who can see this note: [{ user_id, email, name, avatar, role }]."""
    resp = client.invoke("get-users-with-access", body={"document_id": doc_id})
    return resp.get("users", []) if isinstance(resp, dict) else []


def add_collaborator(
    client: GranolaClient,
    doc_id: str,
    email: str,
    name: str | None = None,
    role: str = "COLLABORATOR",
    source: str = "attendee_dropdown",
) -> dict:
    """Add one collaborator. Returns {success, added_emails, failed_emails}."""
    body = {
        "document_id": doc_id,
        "emails": [email],
        "names": {email: name or email},  # MAP keyed by email, not an array
        "role": normalize_role(role),
        "source": source,
    }
    return client.invoke("add-users-to-document", body=body,
                         additional_headers=_ws_headers(client))


def add_collaborators(
    client: GranolaClient,
    doc_id: str,
    recipients: dict[str, str],
    role: str = "COLLABORATOR",
    source: str = "attendee_dropdown",
) -> dict:
    """Add many at once. ``recipients`` is an {email: name} map."""
    body = {
        "document_id": doc_id,
        "emails": list(recipients.keys()),
        "names": {e: (n or e) for e, n in recipients.items()},
        "role": normalize_role(role),
        "source": source,
    }
    return client.invoke("add-users-to-document", body=body,
                         additional_headers=_ws_headers(client))


def remove_collaborator(
    client: GranolaClient,
    doc_id: str,
    email: str,
    cleanup_list_ids: list[str] | None = None,
) -> dict:
    """Revoke access. Returns {success, removed_emails}. Sends no email."""
    body: dict = {"document_id": doc_id, "emails": [email]}
    if cleanup_list_ids:
        body["cleanup_document_list_ids"] = cleanup_list_ids
    return client.invoke("remove-users-from-document", body=body,
                         additional_headers=_ws_headers(client))


def set_role(client: GranolaClient, doc_id: str, user_id: str, role: str) -> dict:
    """Change an existing collaborator's role. Keyed by user_id (not email)."""
    body = {"document_id": doc_id, "user_id": user_id, "role": normalize_role(role)}
    return client.invoke("update-document-user", body=body,
                         additional_headers=_ws_headers(client))


# --- folder / list level sharing (note the inconsistent id field names per endpoint) ---

def list_folder_collaborators(client: GranolaClient, folder: str) -> list[dict]:
    """Who has access to a folder. Keyed by ``list_id`` (yes, different name)."""
    fid = _resolve_folder(client, folder)["id"]
    resp = client.invoke("get-users-with-access-to-list", body={"list_id": fid},
                         additional_headers=_ws_headers(client))
    return resp.get("users", []) if isinstance(resp, dict) else []


def share_folder(
    client: GranolaClient,
    folder: str,
    email: str,
    name: str | None = None,
    role: str = "COLLABORATOR",
    per_note: bool = False,
    skip_existing: bool = True,
) -> dict:
    """Share a folder with one person. ``folder`` may be an id or a title.

    Two modes:
      * default (one call) — ``add-users-to-document-list-v2``: grants *inherited*
        access to every note in the folder, but only adds **existing Granola
        users** (unknown emails come back in ``emails_not_found``).
      * ``per_note=True`` — loops the verified ``add-users-to-document`` path,
        which *invites* new emails too and grants direct (non-inherited) access.
    """
    lst = _resolve_folder(client, folder)
    fid = lst["id"]
    if not per_note:
        res = client.invoke(
            "add-users-to-document-list-v2",
            body={"document_list_id": fid, "emails": [email], "role": normalize_role(role)},
            additional_headers=_ws_headers(client),
        )
        res = dict(res) if isinstance(res, dict) else {"raw": res}
        res["mode"] = "folder"
        res["folder_id"] = fid
        return res

    doc_ids = [d["id"] for d in (lst.get("documents") or []) if not d.get("deleted_at")]
    added, skipped, failed = [], [], []
    for doc_id in doc_ids:
        try:
            if skip_existing and any(
                u.get("email") == email for u in list_collaborators(client, doc_id)
            ):
                skipped.append(doc_id)
                continue
            r = add_collaborator(client, doc_id, email, name=name, role=role)
            (added if r.get("success") else failed).append(doc_id)
        except Exception as exc:  # noqa: BLE001 - report, keep going
            failed.append({"document_id": doc_id, "error": str(exc)})
    return {"mode": "per-note", "folder_id": fid, "total": len(doc_ids),
            "added": added, "skipped": skipped, "failed": failed}


def unshare_folder(client: GranolaClient, folder: str, email: str) -> dict:
    """Revoke a person's folder-level access. Returns {success, removed_emails}."""
    fid = _resolve_folder(client, folder)["id"]
    return client.invoke(
        "remove-users-from-document-list-v2",
        body={"document_list_id": fid, "emails": [email]},
        additional_headers=_ws_headers(client),
    )


def _resolve_folder(client: GranolaClient, folder: str) -> dict:
    """Find a folder (list) dict by id or title, via /v2/get-document-lists."""
    resp = client.invoke("get-document-lists-v2", body={})
    lists = resp.get("lists", []) if isinstance(resp, dict) else []
    for lst in lists:
        if lst.get("id") == folder or (lst.get("title") or "").lower() == folder.lower():
            return lst
    raise ValueError(f"No folder matching '{folder}'.")
