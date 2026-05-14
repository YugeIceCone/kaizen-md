"""kaizen handoff — CLI over the in-plugin handoff store.

The handoff skill's `create` flow writes a YAML file (the system of
record); this CLI indexes it into a SQLite store and answers
`latest` / `list` queries for the `resume` flow. Core logic lives in
``_handoff.py`` — this module is argparse + the ``_cmd_*`` handlers.

## Subcommands

::

   kaizen-handoff save --session SID --file PATH [--status STATUS]
       Index a handoff YAML into the store. Upserts on the file path —
       re-saving the same file (e.g. after Step 4 sets the outcome)
       updates the row, never duplicates.
   kaizen-handoff latest [--json]
       The most recent handoff — what `resume` with no args reads.
   kaizen-handoff list [--limit N] [--session SID] [--json]
       Recent handoffs, metadata only (no YAML content).
   kaizen-handoff path
       Print the store DB + handoffs-dir + domain-config paths.

Bare invocation (no subcommand) defaults to ``latest``. Exit 0 on
success — including "no handoffs", which is informational, not an
error. Non-zero only on bad arguments or an unreadable --file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

import _handoff as _core  # noqa: E402


def _cmd_save(args) -> int:
    fp = Path(args.file).expanduser()
    if not fp.is_file():
        print(json.dumps({"error": f"file not found: {fp}"}))
        return 1
    content = fp.read_text(encoding="utf-8")
    rid = _core.save_handoff(
        args.session, content, str(fp.resolve()), status=args.status
    )
    result = {
        "id": rid,
        "session_id": args.session,
        "file_path": str(fp.resolve()),
        "status": args.status,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"[kaizen-handoff] indexed #{rid} — {args.session} "
              f"({args.status})\n  {fp.resolve()}")
    return 0


def _cmd_latest(args) -> int:
    rows = _core.latest_handoffs(1)
    if args.json:
        print(json.dumps({"handoff": rows[0] if rows else None}, indent=2))
        return 0
    if not rows:
        print("[kaizen-handoff] no handoffs in the store yet.")
        return 0
    h = rows[0]
    print(f"[kaizen-handoff] latest — #{h['id']} {h['session_id']} "
          f"({h['status']}) @ {h['created_at']}")
    print(f"  file: {h['file_path']}")
    return 0


def _cmd_list(args) -> int:
    rows = _core.list_handoffs(limit=args.limit, session_id=args.session)
    if args.json:
        print(json.dumps({"handoffs": rows}, indent=2))
        return 0
    if not rows:
        print("[kaizen-handoff] no handoffs in the store yet.")
        return 0
    scope = f" for session {args.session}" if args.session else ""
    print(f"[kaizen-handoff] {len(rows)} handoff(s){scope}:")
    for h in rows:
        print(f"  #{h['id']:>4}  {h['created_at']}  {h['status']:<8} "
              f"{h['session_id']}")
        print(f"        {h['file_path']}")
    return 0


def _cmd_path(args) -> int:
    print(json.dumps({
        "db": str(_core.handoff_db_path()),
        "yaml_dir": str(_core.handoffs_dir()),
        "domain": str(_core.DOMAIN_DIR / "handoff.yaml"),
    }, indent=2))
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-handoff",
        description="CLI over the in-plugin handoff store — index + "
                    "query session handoff documents.",
    )
    # required=False so a bare invocation defaults to `latest` (the
    # resume hot path). `latest` takes no positional args, so the
    # slash command can pass bare $ARGUMENTS safely.
    sub = p.add_subparsers(dest="cmd", required=False)

    s_save = sub.add_parser("save", help="index a handoff YAML into the store")
    s_save.add_argument("--session", required=True, help="session/project name")
    s_save.add_argument("--file", required=True, help="path to the handoff YAML")
    s_save.add_argument("--status", choices=list(_core.VALID_STATUS),
                        default="partial")
    s_save.add_argument("--json", action="store_true")
    s_save.set_defaults(func=_cmd_save)

    s_latest = sub.add_parser("latest", help="the most recent handoff")
    s_latest.add_argument("--json", action="store_true")
    s_latest.set_defaults(func=_cmd_latest)

    s_list = sub.add_parser("list", help="recent handoffs (metadata only)")
    s_list.add_argument("--limit", type=int, default=20)
    s_list.add_argument("--session", help="filter by session/project")
    s_list.add_argument("--json", action="store_true")
    s_list.set_defaults(func=_cmd_list)

    s_path = sub.add_parser("path", help="print store + yaml-dir paths")
    s_path.set_defaults(func=_cmd_path)

    args = p.parse_args(argv)
    if args.cmd is None:
        return _cmd_latest(argparse.Namespace(json=False))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
