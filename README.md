# granola

One CLI for [Granola](https://granola.ai) that **does it all** on Windows — using
Granola's own on-disk session, no API key, no password prompt:

- **Decrypt** the on-disk credential chain (DPAPI → DEK → `stored-accounts.json.enc`),
  auto-**refresh** the token (single-use rotation, with safe write-back).
- **Read** notes: list, full record, metadata, transcript, AI panels.
- **Share / edit**: add & remove collaborators, change roles, share a whole folder,
  partial-edit, delete.
- **Call** any of ~392 internal endpoints directly.
- **Sync + search**: pull notes into local SQLite and run full-text (FTS5) search.

> Unofficial. Uses the internal `api.granola.ai` surface the desktop app uses; it can
> change without notice. Windows-only for the credential decrypt (the API layer is
> portable once you have a token).

## Install

```powershell
uv tool install .          # or: pipx install .
granola info
```

Requires Python ≥ 3.10. Only dependency is `httpx`.

## Usage

```text
# engine
granola info                         # token status (no secrets)
granola token                        # print a valid access token
granola routes [filter]              # endpoint name -> URL map
granola call <endpoint> --body '{"limit":5}'
granola export creds.json --refresh  # SECRET dump

# read
granola notes --limit 20             # recent notes
granola get <id>                     # full ~50-field record (--json for all)
granola meta <id>                    # creator / attendees / conferencing
granola transcript <id>              # transcript as markdown
granola panels <id>                  # AI summary panels

# share / access
granola who <id>                                     # who has access (+ user_ids)
granola share <id> --email a@b.com --name "A B"      # add collaborator
granola unshare <id> --email a@b.com                 # revoke (no email sent)
granola role <id> --user <user_id> --role viewer     # change role
granola share-folder NeuroSense --email a@b.com --name "A B"   # cascade to all notes

# edit
granola update <id> --title "New title"
granola delete <id> --yes            # PERMANENT hard delete

# local sync + search (FTS5)
granola sync --limit 200 --out notes        # -> ~/.granola/notes.db (+ markdown in ./notes)
granola search "epilepsy AND seizure"       # full-text over synced notes
```

Roles: `owner` · `collaborator` · `viewer`.

## Verified API gotchas (baked into the typed verbs)

These cost real debugging time and are why the typed verbs exist — so you don't hit them:

- **`share`** → `add-users-to-document` wants `names` as an **`{email: name}` object map**,
  not an array (an array makes the server `500`).
- **`update`** → `update-document` keys the note as **`id`**, not `document_id`
  (sending `document_id` returns `400 "Missing document ID"`).
- **`get`** → the full single-note record comes from `get-documents-batch`
  (`{document_ids: [...]}`), not a singular `get-document`.

Full request/response shapes: see `docs/granola-api.md` in the companion
[credential-decrypt research repo](https://github.com/).

## Search scope

Keyword/full-text search ships here (stdlib SQLite **FTS5**, zero extra deps).
**Semantic search and the TUI are intentionally out of scope** — for those, use
[harperreed/muesli](https://github.com/harperreed/muesli) (Rust, read/search-focused),
which this tool complements rather than replaces. `granola` owns the **write**
surface (sharing/editing) that muesli deliberately doesn't have.

## Layout

```
granola/
  config, crypto, _http, store, auth, routes, client, export   # ported engine (decrypt+refresh+call)
  notes.py      read ops (list/get/meta/transcript/panels)
  sharing.py    collaborators (who/share/unshare/role/share-folder)
  editing.py    update-document / hard-delete
  db.py         SQLite schema + FTS5
  sync.py       notes (+transcripts) -> SQLite (+ markdown mirror)
  search.py     FTS5 keyword search
  cli.py        the `granola` command
```

## License

MIT.
