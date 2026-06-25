# granola-cli

[![PyPI](https://img.shields.io/pypi/v/granola-cli)](https://pypi.org/project/granola-cli/)

One CLI for [Granola](https://granola.ai) on **Windows & macOS** — using Granola's own
on-disk session, no API key, no password prompt. It covers two things:

1. **Credentials** — decrypt the on-disk chain (Windows DPAPI / macOS Keychain → DEK →
   cred file), auto-**refresh** the token (single-use rotation, with safe write-back),
   print it, or export a portable **session file** for headless/Linux use.
2. **The documented internal API** for a note — read, share, edit — plus a generic
   `call` for any of the ~392 internal endpoints.

> Unofficial. Uses the internal `api.granola.ai` surface the desktop app uses; it can
> change without notice. Credential decrypt works on **Windows** (DPAPI) and **macOS**
> (Keychain); the API layer is portable once you have a token.

## Install

```bash
pip install granola-cli         # or: uv tool install granola-cli / pipx install granola-cli
granola auth status
```

Requires Python ≥ 3.10. Dependencies: `httpx`, `cryptography`.

To install from a checkout instead (development): `uv tool install .` (or `pipx install .`).

## Usage

```text
# auth / engine
granola auth status                  # token status (no secrets; --include-secrets to show)
granola auth token                   # print a valid access token
granola auth refresh                 # force-refresh the selected source
granola auth export session.json     # write a portable, refreshable session file (0600)
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

## Headless / portable sessions

Credential decrypt needs the Keychain (macOS) or DPAPI (Windows), so it only runs on
the machine you signed in on. To drive the API from a headless Linux box or CI, export
a **session file** once and carry it over:

```bash
# On your macOS/Windows machine (where Granola is signed in):
granola auth export ~/session.json     # minimal, refreshable, written 0600

# Sign OUT of the Granola desktop app, so only this session holds the refresh token.
# (Desktop + session sharing one single-use refresh token will fight and log each
#  other out on rotation.)

# On the headless box:
export GRANOLA_SESSION=~/session.json
granola notes --limit 20               # refreshes + writes back to the file in place
```

Every command takes global auth options (before the command) that pick the token source:

```text
--email EMAIL          select an account from local desktop credentials
--session PATH         use a refreshable session file
--access-token TOKEN   use this bearer token directly (no refresh)
--no-refresh           never auto-refresh
```

Environment equivalents: `GRANOLA_SESSION`, `GRANOLA_ACCESS_TOKEN`.

**Precedence:** a refreshable session (`--session` / `GRANOLA_SESSION`) beats a static
token (`--access-token` / `GRANOLA_ACCESS_TOKEN`); a flag beats its env var; the desktop
store is the fallback. If both a static token and a session are set, the session wins and
the CLI warns — a static token can't refresh and would silently go stale.

Use `--access-token` (or `granola auth export --no-refresh-token`) for short-lived CI where
you don't want a long-lived rotating secret on the box.

If a session's refresh token ever dies (the desktop rotated it, or it was revoked), you
can't re-bootstrap headlessly — re-run `granola auth export` on your macOS/Windows machine
and copy the file over.

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
  config, crypto, _http, store        # engine: decrypt the on-disk cred chain
  auth.py       token primitives: refresh exchange, expiry, status (persistence-free)
  sources.py    token sources (desktop / session-file / static) + precedence
  routes, client                      # endpoint resolution + API client
  notes.py      read ops (list/get/meta/transcript/panels)
  sharing.py    collaborators (who/share/unshare/role/share-folder)
  editing.py    update-document / hard-delete
  cli.py        the `granola` command
```

## License

MIT.
