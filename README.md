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
granola share <id> --email teammate@example.com --name "Teammate"  # add collaborator
granola unshare <id> --email teammate@example.com                  # revoke (no email sent)
granola role <id> --user <user_id> --role viewer     # change role
granola folder-who "Team Notes"                       # who has folder-level access
granola share-folder "Team Notes" --email teammate@example.com       # folder ACL (existing users; inherited access)
granola share-folder "Team Notes" --email teammate@example.com --per-note   # invite + direct access on each note
granola unshare-folder "Team Notes" --email teammate@example.com     # revoke folder-level access

# edit
granola update <id> --title "New title"
granola delete <id> --yes            # PERMANENT hard delete
```

Roles: `owner` · `collaborator` · `viewer`.

See [`docs/api-gotchas.md`](docs/api-gotchas.md) for endpoint quirks baked into the
typed verbs.

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
