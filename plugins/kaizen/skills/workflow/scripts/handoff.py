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
   kaizen-handoff bridge --file PATH [--apply]
       Extract a handoff's durable learnings (decisions / findings /
       worked / failed) as brain capture-candidates. Lists them for
       review by default; --apply captures every one into brain.
   kaizen-handoff path
       Print the store DB + handoffs-dir + domain-config paths.

Bare invocation (no subcommand) defaults to ``latest``. Exit 0 on
success — including "no handoffs", which is informational, not an
error. Non-zero only on bad arguments or an unreadable --file.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

import _handoff as _core  # noqa: E402
import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-handoff", tool_version="1.0.0")


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
        _emit(result, verdict="green")
    else:
        print(f"[kaizen-handoff] indexed #{rid} — {args.session} "
              f"({args.status})\n  {fp.resolve()}")
    return 0


def _cmd_latest(args) -> int:
    rows = _core.latest_handoffs(1)
    if args.json:
        _emit({"handoff": rows[0] if rows else None})
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
        _emit({"handoffs": rows}, counts={"handoffs": len(rows)})
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


def _cmd_bridge(args) -> int:
    fp = Path(args.file).expanduser()
    if not fp.is_file():
        print(json.dumps({"error": f"file not found: {fp}"}))
        return 1
    candidates = _core.extract_brain_candidates(fp.read_text(encoding="utf-8"))

    if args.apply:
        # Onion-clean: handoff is a CLI *consumer* of brain — cross the
        # process boundary, no `_brain` import.
        brain_py = (_core.PLUGIN_ROOT / "skills" / "workflow"
                    / "scripts" / "brain.py")
        rows = []
        for c in candidates:
            try:
                r = subprocess.run(
                    ["python3", str(brain_py), "capture", c["text"]],
                    capture_output=True, text=True, timeout=30,
                )
                captured = r.returncode == 0
            except (subprocess.SubprocessError, OSError):
                captured = False
            rows.append({**c, "captured": captured})
        result = {"applied": rows, "count": len(rows)}
    else:
        result = {"candidates": candidates, "count": len(candidates)}

    if args.json:
        _emit(result, counts={"candidates": result.get("count", 0)})
        return 0
    if not candidates:
        print("[kaizen-handoff bridge] no durable learnings — "
              "decisions / findings / worked / failed are all empty.")
        return 0
    verb = "captured into brain" if args.apply else "brain capture-candidate(s)"
    rows = result.get("applied") or result.get("candidates")
    print(f"\n[kaizen-handoff bridge] {len(rows)} {verb}:")
    for c in rows:
        mark = ""
        if args.apply:
            mark = " ✓" if c.get("captured") else " ✗(failed)"
        print(f"  [{c['section']}]{mark} {c['text'][:100]}")
    if not args.apply:
        print("\n  Review these — capture the genuinely durable ones via")
        print("  `brain.py capture \"<text>\"`, or re-run with --apply for all.")
    return 0


def _cmd_path(args) -> int:
    _emit({
        "db": str(_core.handoff_db_path()),
        "yaml_dir": str(_core.handoffs_dir()),
        "domain": str(_core.DOMAIN_DIR / "handoff.yaml"),
    })
    return 0


def _cmd_auto_finalize(args) -> int:
    """Agent-assigned Step 4 of the handoff create flow — no AskUserQuestion.

    Rewrites the YAML frontmatter status/outcome (+ optional justification
    and assigned_by audit fields) and re-indexes into the DB store. Used
    by:
      - Subagent contexts (no AskUserQuestion available)
      - KAIZEN_HANDOFF_AGENT=1 mode (explicit signal that an agent is
        finalizing the handoff)
      - The interactive default per current handoff skill — Claude
        self-assesses against the rubric in SKILL.md Step 4 before
        the YAML lands
    """
    fp = Path(args.file).expanduser()
    if not fp.is_file():
        msg = f"file not found: {fp}"
        if args.json:
            _emit({"error": msg}, verdict="red")
        else:
            print(f"[kaizen-handoff auto-finalize] {msg}", file=sys.stderr)
        return 1

    if args.outcome not in _core.VALID_OUTCOME:
        msg = (
            f"invalid --outcome {args.outcome!r} "
            f"(expected one of: {', '.join(_core.VALID_OUTCOME)})"
        )
        print(f"[kaizen-handoff auto-finalize] {msg}", file=sys.stderr)
        return 2

    if args.status not in _core.VALID_STATUS:
        msg = (
            f"invalid --status {args.status!r} "
            f"(expected one of: {', '.join(_core.VALID_STATUS)})"
        )
        print(f"[kaizen-handoff auto-finalize] {msg}", file=sys.stderr)
        return 2

    if args.assigned_by not in _core.VALID_ASSIGNED_BY:
        msg = (
            f"invalid --assigned-by {args.assigned_by!r} "
            f"(expected one of: {', '.join(_core.VALID_ASSIGNED_BY)})"
        )
        print(f"[kaizen-handoff auto-finalize] {msg}", file=sys.stderr)
        return 2

    updates: dict[str, str] = {
        "status": args.status,
        "outcome": args.outcome,
        "outcome_assigned_by": args.assigned_by,
    }
    if args.justification:
        updates["outcome_justification"] = args.justification

    original = fp.read_text(encoding="utf-8")
    try:
        rewritten = _core.update_frontmatter(original, updates)
    except ValueError as exc:
        msg = f"frontmatter rewrite failed: {exc}"
        if args.json:
            _emit({"error": msg}, verdict="red")
        else:
            print(f"[kaizen-handoff auto-finalize] {msg}", file=sys.stderr)
        return 1

    # Atomic write: tempfile in same dir → rename.
    tmp = fp.with_suffix(fp.suffix + ".auto-finalize.tmp")
    tmp.write_text(rewritten, encoding="utf-8")
    tmp.replace(fp)

    # Re-index. Session name = parent dir name (matches the skill's
    # "session-name groups handoffs into one folder" convention).
    session_id = args.session or fp.parent.name
    rid = _core.save_handoff(
        session_id, rewritten, str(fp.resolve()), status=args.status,
    )

    result = {
        "id": rid,
        "session_id": session_id,
        "file_path": str(fp.resolve()),
        "status": args.status,
        "outcome": args.outcome,
        "outcome_assigned_by": args.assigned_by,
        "outcome_justification": args.justification,
    }
    if args.json:
        verdict = "green" if args.outcome == "SUCCEEDED" else "yellow"
        _emit(result, verdict=verdict)
    else:
        print(
            f"[kaizen-handoff auto-finalize] indexed #{rid} — "
            f"{session_id} (status={args.status}, outcome={args.outcome}, "
            f"by={args.assigned_by})\n  {fp.resolve()}"
        )
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

    s_bridge = sub.add_parser(
        "bridge",
        help="extract a handoff's durable learnings as brain "
             "capture-candidates")
    s_bridge.add_argument("--file", required=True,
                          help="path to the handoff YAML")
    s_bridge.add_argument("--apply", action="store_true",
                          help="capture every candidate into brain "
                               "(default: just list them for review)")
    s_bridge.add_argument("--json", action="store_true")
    s_bridge.set_defaults(func=_cmd_bridge)

    s_path = sub.add_parser("path", help="print store + yaml-dir paths")
    s_path.set_defaults(func=_cmd_path)

    s_auto = sub.add_parser(
        "auto-finalize",
        help="agent-assigned Step 4 — rewrite frontmatter outcome + status, "
             "re-index, no AskUserQuestion",
    )
    s_auto.add_argument("--file", required=True, help="path to the handoff YAML")
    s_auto.add_argument(
        "--outcome", required=True, choices=list(_core.VALID_OUTCOME),
        help="agent-assigned outcome bucket — see SKILL.md rubric",
    )
    s_auto.add_argument(
        "--status", default="complete", choices=list(_core.VALID_STATUS),
        help="work-lifecycle state (default: complete)",
    )
    s_auto.add_argument(
        "--assigned-by", default="agent", choices=list(_core.VALID_ASSIGNED_BY),
        help="audit field — who picked the outcome (default: agent)",
    )
    s_auto.add_argument(
        "--justification", default=None,
        help="one-line rationale for the outcome bucket "
             "(no `: ` colon-space inside — see SKILL.md)",
    )
    s_auto.add_argument(
        "--session", default=None,
        help="session/project name (default: parent-dir of --file)",
    )
    s_auto.add_argument("--json", action="store_true")
    s_auto.set_defaults(func=_cmd_auto_finalize)

    args = p.parse_args(argv)
    if args.cmd is None:
        return _cmd_latest(argparse.Namespace(json=False))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
