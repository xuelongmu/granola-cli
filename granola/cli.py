"""`granola` — one CLI for the documented Granola API: credentials + notes + sharing + editing.

Engine:   info | token | routes | call | export
Read:     notes | get | meta | transcript | panels
Share:    who | share | unshare | role | share-folder | folder-who | unshare-folder
Edit:     update | delete
"""
from __future__ import annotations

import argparse
import json
import sys

from . import editing, notes, sharing
from .auth import get_access_token, token_info
from .client import GranolaClient
from .config import Config
from .export import export_credentials
from .routes import load_routes


def _print(obj) -> None:
    print(obj if isinstance(obj, str) else json.dumps(obj, indent=2, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="granola", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--email", help="Select a specific stored account.")
    p.add_argument("--no-refresh", action="store_true", help="Never auto-refresh the token.")
    sub = p.add_subparsers(dest="cmd", required=True)

    # --- engine ---
    pi = sub.add_parser("info", help="Token status (no secrets by default).")
    pi.add_argument("--include-secrets", action="store_true")
    sub.add_parser("token", help="Print a valid access token.")
    pr = sub.add_parser("routes", help="List endpoint routes (optional filter).")
    pr.add_argument("filter", nargs="?", default="")
    pc = sub.add_parser("call", help="Call any endpoint by name or URL.")
    pc.add_argument("endpoint")
    pc.add_argument("--body", help='JSON body, e.g. \'{"limit":5}\'.')
    pc.add_argument("--method", default="POST")
    pc.add_argument("--raw", action="store_true")
    pe = sub.add_parser("export", help="Dump decrypted credentials to a file (SECRET).")
    pe.add_argument("path")
    pe.add_argument("--refresh", action="store_true")

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
    ps.add_argument("id"); ps.add_argument("--email", required=True)
    ps.add_argument("--name"); ps.add_argument("--role", default="collaborator")
    pu = sub.add_parser("unshare", help="Remove a collaborator from a note.")
    pu.add_argument("id"); pu.add_argument("--email", required=True)
    pu.add_argument("--cleanup-list", action="append", default=[],
                    help="Also strip inherited access from this folder id (repeatable).")
    prole = sub.add_parser("role", help="Change a collaborator's role.")
    prole.add_argument("id"); prole.add_argument("--user", required=True, help="user_id (from `who`).")
    prole.add_argument("--role", required=True)
    pf = sub.add_parser("share-folder", help="Share a folder with someone (folder-level access).")
    pf.add_argument("folder", help="Folder id or name (e.g. NeuroSense).")
    pf.add_argument("--email", required=True); pf.add_argument("--name")
    pf.add_argument("--role", default="collaborator")
    pf.add_argument("--per-note", action="store_true",
                    help="Add to each note directly (invites non-Granola emails; vs one-call folder ACL).")
    pf.add_argument("--include-existing", action="store_true",
                    help="(per-note) Re-add even where the person already has access.")
    pfw = sub.add_parser("folder-who", help="Who has access to a folder.")
    pfw.add_argument("folder")
    puf = sub.add_parser("unshare-folder", help="Revoke a person's folder-level access.")
    puf.add_argument("folder"); puf.add_argument("--email", required=True)

    # --- edit ---
    pup = sub.add_parser("update", help="Partial-edit a note (title/markdown).")
    pup.add_argument("id"); pup.add_argument("--title"); pup.add_argument("--markdown")
    pd = sub.add_parser("delete", help="PERMANENTLY hard-delete a note.")
    pd.add_argument("id"); pd.add_argument("--yes", action="store_true", help="Required: confirm.")
    return p


def main(argv=None) -> int:  # noqa: C901 - flat dispatch is clearer than abstraction here
    try:  # Windows console defaults to cp1252; note content is UTF-8 (emoji, smart quotes)
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = build_parser().parse_args(argv)
    cfg = Config()
    client = GranolaClient(cfg)
    c = args.cmd

    # engine
    if c == "info":
        _print(token_info(cfg, include_secrets=args.include_secrets))
    elif c == "token":
        print(get_access_token(cfg, email=args.email, no_refresh=args.no_refresh))
    elif c == "routes":
        for name in sorted(load_routes(cfg)):
            if args.filter in name:
                print(f"{name:40} {load_routes(cfg)[name]}")
    elif c == "call":
        body = json.loads(args.body) if args.body else None
        _print(client.invoke(args.endpoint, body=body, method=args.method,
                             email=args.email, no_refresh=args.no_refresh, raw=args.raw))
    elif c == "export":
        print(export_credentials(cfg, args.path, refresh=args.refresh))

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
            print("note not found", file=sys.stderr); return 1
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
            print("nothing to update (pass --title and/or --markdown)", file=sys.stderr); return 2
        _print(editing.update_note(client, args.id, **fields))
    elif c == "delete":
        if not args.yes:
            print("refusing to hard-delete without --yes (this is permanent)", file=sys.stderr); return 2
        _print(editing.delete_note(client, args.id))

    return 0


if __name__ == "__main__":
    sys.exit(main())
