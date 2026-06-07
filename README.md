# granola

One CLI for [Granola](https://granola.ai) on **Windows & macOS** — using Granola's own
on-disk session, no API key, no password prompt. It covers two things:

1. **Credentials** — decrypt the on-disk chain (Windows DPAPI / macOS Keychain → DEK →
   cred file), auto-**refresh** the token (single-use rotation, with safe write-back),
   print/export it.
2. **The documented internal API** for a note — read, share, edit — plus a generic
   `call` for any of the ~392 internal endpoints.

> Unofficial. Uses the internal `api.granola.ai` surface the desktop app uses; it can
> change without notice. Credential decrypt works on **Windows** (DPAPI) and **macOS**
> (Keychain); the API layer is portable once you have a token.

## Install

```powershell
uv tool install .          # or: pipx install .
granola info
```

Requires Python ≥ 3.10. Dependencies: `httpx`, `cryptography`.

## Usage

```text
# credentials / engine
granola info                         # token status (no secrets)
granola token                        # print a valid access token
granola export creds.json --refresh  # SECRET dump of decrypted credentials
granola routes [filter]              # endpoint name -> URL map
granola call <endpoint> --body '{"limit":5}'   # any endpoint, raw

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
granola folder-who NeuroSense                         # who has folder-level access
granola share-folder NeuroSense --email a@b.com       # folder ACL (existing users; inherited access)
granola share-folder NeuroSense --email a@b.com --per-note   # invite + direct access on each note
granola unshare-folder NeuroSense --email a@b.com     # revoke folder-level access

# edit
granola update <id> --title "New title"
granola delete <id> --yes            # PERMANENT hard delete
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

Full request/response shapes are documented in `docs/granola-api.md` in the companion
credential-decrypt research repo.

## Platforms

| | Windows | macOS |
|---|---|---|
| Data dir | `%APPDATA%\Granola` | `~/Library/Application Support/Granola` |
| Key source | `Local State` → **DPAPI** (CurrentUser) | login **Keychain** item `Granola Safe Storage` / `Granola Key` |
| `storage.dek` unwrap | AES-256-GCM (Chromium key) | AES-128-CBC (PBKDF2 `saltysalt`/1003 — Electron safeStorage) |
| Cred file | `stored-accounts.json.enc` (`accounts[].tokens`) | `supabase.json.enc` (`workos_tokens`) |
| Final decrypt | AES-256-GCM(DEK) | AES-256-GCM(DEK) |

The decrypt must run as the logged-in user (DPAPI / Keychain are user-scoped). On macOS
the **first** run may show a Keychain access prompt for the `Granola Safe Storage` item —
allow it. The macOS crypto is verified against
[harperreed/muesli](https://github.com/harperreed/muesli)'s known-good vectors
(`tests/test_macos_crypto.py`).

The macOS path is not just theoretical: `granola --no-refresh info`,
`granola --no-refresh token`, and a live `granola --no-refresh notes --limit 1`
smoke test have been verified against a local Granola profile on macOS.

## Layout

```
granola/
  config, crypto, _http, store, auth, routes, client, export   # engine: decrypt + refresh + call
  notes.py      read ops (list/get/meta/transcript/panels)
  sharing.py    collaborators (who/share/unshare/role/share-folder)
  editing.py    update-document / hard-delete
  cli.py        the `granola` command
```

## License

MIT.
