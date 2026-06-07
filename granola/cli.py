"""`granola` — one CLI for the documented Granola API: credentials + notes + sharing + editing.

Auth:     auth status | auth token | auth refresh | auth export
Engine:   routes | call
Read:     notes | get | meta | transcript | panels
Share:    who | share | unshare | role | share-folder | folder-who | unshare-folder
Edit:     update | delete

Global auth options (before the command) select the token source:
  --email EMAIL        pick an account from the local desktop credentials
  --session PATH       use a refreshable session file
  --access-token TOK   use this bearer token directly (no refresh)
  --no-refresh         never auto-refresh
Environment: GRANOLA_SESSION, GRANOLA_ACCESS_TOKEN.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import editing, notes, sharing
from .client import GranolaClient
from .config import Config
from .routes import load_routes
from .sources import create_session_file, resolve_source

DEFAULT_SESSION_PATH = Path.home() / ".config" / "granola" / "session.json"


def _print(obj) -> None:
    print(obj if isinstance(obj, str) else json.dumps(obj, indent=2, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="granola", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--email", help="Select a specific stored desktop account.")
    p.add_argument("--session", help="Use a refreshable session JSON file.")
    p.add_argument("--access-token", help="Use this bearer token directly (no refresh).")
    p.add_argument("--no-refresh", action="store_true", help="Never auto-refresh the token.")
    sub = p.add_subparsers(dest="cmd", required=True)

    # --- auth ---
    pa = sub.add_parser("auth", help="Token / session management.")
    asub = pa.add_subparsers(dest="auth_cmd", required=True)
    pas = asub.add_parser("status", help="Token/account status (no secrets by default).")
    pas.add_argument("--include-secrets", action="store_true")
    asub.add_parser("token", help="Print the current valid bearer token.")
    asub.add_parser("refresh", help="Force-refresh the selected source.")
    pae = asub.add_parser("export", help="Write a refreshable session file from desktop creds.")
    pae.add_argument("path", nargs="?", default=None,
                     help=f"Destination (default: {DEFAULT_SESSION_PATH}).")
    pae.add_argument("--no-refresh-token", action="store_true",
                     help="Bearer-only session (cannot refresh; for short-lived/CI use).")

    # --- engine ---
    pr = sub.add_parser("routes", help="List endpoint routes (optional filter).")
    pr.add_argument("filter", nargs="?", default="")
    pc = sub.add_parser("call", help="Call any endpoint by name or URL.")
    pc.add_argument("endpoint")
    pc.add_argument("--body", help='JSON body, e.g. \'{"limit":5}\'.')
    pc.add_argument("--method", default="POST")
    pc.add_argument("--raw", action="store_true")

    # --- read ---
    pn = sub.add_parser("notes", help="List recent notes.")
    pn.add_argument("--limit", type=int, default=20)
    pn.add_argument("--json", action="store_true")
    pg = sub.add_parser("get", help="Full record for one note.")
    pg.add_argument("id")
    pg.add_argument("--json", action="store_true")
    pm = sub.add_parser("meta", help="Creator/attendees/conferencing for a note.")
    pm.add_argument("id")
    pt = sub.add_parser("transcript", help="Transcript as markdown.")
    pt.add_argument("id")
    pp = sub.add_parser("panels", help="AI summary panels for a note.")
    pp.add_argument("id")
    pp.add_argument("--json", action="store_true")

    # --- share ---
    pw = sub.add_parser("who", help="Who has access to a note.")
    pw.add_argument("id")
    ps = sub.add_parser("share", help="Add a collaborator to a note.")
    ps.add_argument("id")
    ps.add_argument("--email", required=True)
    ps.add_argument("--name")
    ps.add_argument("--role", default="collaborator")
    pu = sub.add_parser("unshare", help="Remove a collaborator from a note.")
    pu.add_argument("id")
    pu.add_argument("--email", required=True)
    pu.add_argument("--cleanup-list", action="append", default=[],
                    help="Also strip inherited access from this folder id (repeatable).")
    prole = sub.add_parser("role", help="Change a collaborator's role.")
    prole.add_argument("id")
    prole.add_argument("--user", required=True, help="user_id (from `who`).")
    prole.add_argument("--role", required=True)
    pf = sub.add_parser("share-folder", help="Share a folder with someone (folder-level access).")
    pf.add_argument("folder", help='Folder id or name (e.g. "Team Notes").')
    pf.add_argument("--email", required=True)
    pf.add_argument("--name")
    pf.add_argument("--role", default="collaborator")
    pf.add_argument("--per-note", action="store_true",
                    help="Add to each note directly (invites non-Granola emails; vs one-call folder ACL).")
    pf.add_argument("--include-existing", action="store_true",
                    help="(per-note) Re-add even where the person already has access.")
    pfw = sub.add_parser("folder-who", help="Who has access to a folder.")
    pfw.add_argument("folder")
    puf = sub.add_parser("unshare-folder", help="Revoke a person's folder-level access.")
    puf.add_argument("folder")
    puf.add_argument("--email", required=True)

    # --- edit ---
    pup = sub.add_parser("update", help="Partial-edit a note (title/markdown).")
    pup.add_argument("id")
    pup.add_argument("--title")
    pup.add_argument("--markdown")
    pd = sub.add_parser("delete", help="PERMANENTLY hard-delete a note.")
    pd.add_argument("id")
    pd.add_argument("--yes", action="store_true", help="Required: confirm.")
    return p


def main(argv=None) -> int:  # noqa: C901 - flat dispatch is clearer than abstraction here
    try:  # Windows console defaults to cp1252; note content is UTF-8 (emoji, smart quotes)
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = build_parser().parse_args(argv)
    cfg = Config()
    c = args.cmd

    # auth export reads the desktop store directly; it doesn't use the resolved source.
    if c == "auth" and args.auth_cmd == "export":
        if args.session or args.access_token:
            print("auth export reads the desktop credential store; "
                  "don't pass --session/--access-token.", file=sys.stderr)
            return 2
        dest = args.path or str(DEFAULT_SESSION_PATH)
        out = create_session_file(cfg, dest, email=args.email,
                                  include_refresh_token=not args.no_refresh_token)
        mode = "owner-only" if sys.platform == "win32" else "0600"
        kind = "bearer-only" if args.no_refresh_token else "refreshable"
        print(f"Wrote {kind} session file: {out} (mode {mode})", file=sys.stderr)
        print(out)
        return 0

    source = resolve_source(cfg, email=args.email, session=args.session,
                            access_token=args.access_token, no_refresh=args.no_refresh)
    client = GranolaClient(cfg, source=source)

    # auth
    if c == "auth":
        if args.auth_cmd == "status":
            _print(source.status(include_secrets=args.include_secrets))
        elif args.auth_cmd == "token":
            print(source.access_token())
        elif args.auth_cmd == "refresh":
            source.access_token(force=True)
            _print(source.status(include_secrets=False))

    # engine
    elif c == "routes":
        for name in sorted(load_routes(cfg)):
            if args.filter in name:
                print(f"{name:40} {load_routes(cfg)[name]}")
    elif c == "call":
        body = json.loads(args.body) if args.body else None
        _print(client.invoke(args.endpoint, body=body, method=args.method, raw=args.raw))

    # read
    elif c == "notes":
        docs = notes.list_notes(client, limit=args.limit)
        if args.json:
            _print(docs)
        else:
            for d in docs:
                print(f"{d.get('id')}  {d.get('updated_at','')[:19]:19}  {d.get('title') or '(untitled)'}")
            print(f"{len(docs)} notes", file=sys.stderr)
    elif c == "get":
        rec = notes.get_note(client, args.id)
        if not rec:
            print("note not found", file=sys.stderr)
            return 1
        if args.json:
            _print(rec)
        else:
            for k in ("id", "title", "created_at", "updated_at", "workspace_id",
                      "public", "visibility", "document_user_role", "is_shared_direct"):
                print(f"{k:20} {rec.get(k)}")
    elif c == "meta":
        _print(notes.get_metadata(client, args.id))
    elif c == "transcript":
        print(notes.transcript_to_markdown(notes.get_transcript(client, args.id)))
    elif c == "panels":
        _print(notes.get_panels(client, args.id))

    # share
    elif c == "who":
        for u in sharing.list_collaborators(client, args.id):
            print(f"{u.get('role',''):13} {u.get('email',''):35} {u.get('user_id','')}")
    elif c == "share":
        _print(sharing.add_collaborator(client, args.id, args.email, name=args.name, role=args.role))
    elif c == "unshare":
        _print(sharing.remove_collaborator(client, args.id, args.email,
                                           cleanup_list_ids=args.cleanup_list or None))
    elif c == "role":
        _print(sharing.set_role(client, args.id, args.user, args.role))
    elif c == "share-folder":
        _print(sharing.share_folder(client, args.folder, args.email, name=args.name,
                                    role=args.role, per_note=args.per_note,
                                    skip_existing=not args.include_existing))
    elif c == "folder-who":
        for u in sharing.list_folder_collaborators(client, args.folder):
            print(f"{u.get('role',''):13} {u.get('email',''):35} {u.get('access_source','')}")
    elif c == "unshare-folder":
        _print(sharing.unshare_folder(client, args.folder, args.email))

    # edit
    elif c == "update":
        fields = {k: v for k, v in (("title", args.title), ("notes_markdown", args.markdown)) if v is not None}
        if not fields:
            print("nothing to update (pass --title and/or --markdown)", file=sys.stderr)
            return 2
        _print(editing.update_note(client, args.id, **fields))
    elif c == "delete":
        if not args.yes:
            print("refusing to hard-delete without --yes (this is permanent)", file=sys.stderr)
            return 2
        _print(editing.delete_note(client, args.id))

    return 0


if __name__ == "__main__":
    sys.exit(main())
