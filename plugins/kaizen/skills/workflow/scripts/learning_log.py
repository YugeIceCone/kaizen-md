"""kaizen-learn — append-only learning + evolution log.

Captures structured problem/solution pairs encountered during the tool
loop. Three starter categories — wasteful_tokens / roundtrips /
anti_patterns — each carrying a reusable pattern + optional savings
estimate + trigger keywords for later pattern matching.

Subcommands:
  append   — write one entry (CLI flags or --stdin JSON)
  list     — query the log (filter by category; --json)

Iron-laws:
  - append-only — NEVER reads the existing log (proven by size-delta
    test on a 50KB seeded log)
  - schema-validates BEFORE write; invalid payload exits 1
  - JSONL — one entry per line, diff-friendly + grep-friendly
  - id assigned per-entry as random short-hex (8 chars; uniqueness via
    secrets.token_hex)

Sink: <KAIZEN_LEARNING_DIR>/log.jsonl
      default ~/.claude/.kaizen/learning/log.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

_VALID_CATEGORIES = frozenset({
    "wasteful_tokens", "roundtrips", "anti_patterns",
})


def _detect_branch() -> str | None:
    """Resolve current git branch via cwd. None when not in a repo."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            branch = r.stdout.strip()
            return branch or None
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _learning_dir() -> Path:
    # DRY — delegates to shared _paths.env_overridable_dir helper.
    from _paths import env_overridable_dir
    return env_overridable_dir("KAIZEN_LEARNING_DIR", "learning")


def _log_path() -> Path:
    return _learning_dir() / "log.jsonl"


def _validate(payload: dict) -> str | None:
    """Return error string on invalid payload, else None."""
    if not isinstance(payload, dict):
        return f"payload must be a dict, got {type(payload).__name__}"
    for k in ("category", "problem", "solution", "pattern"):
        if k not in payload:
            return f"missing required field: {k}"
    if payload["category"] not in _VALID_CATEGORIES:
        return (f"invalid category {payload['category']!r}; expected one of "
                 f"{sorted(_VALID_CATEGORIES)}")
    for field in ("problem", "solution", "pattern"):
        v = payload[field]
        if not isinstance(v, str) or not v.strip():
            return f"{field} must be a non-empty string"
    # Optional fields with shape constraints
    keywords = payload.get("trigger_keywords", [])
    if not isinstance(keywords, list):
        return "trigger_keywords must be a list"
    commits = payload.get("source_commits", [])
    if not isinstance(commits, list):
        return "source_commits must be a list"
    return None


def _build_entry(payload: dict) -> dict:
    """Add ts + id + promotion_status defaults; preserve operator fields."""
    entry = {
        "id": secrets.token_hex(4),
        "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "promotion_status": "pending",
    }
    entry.update(payload)
    return entry


def _atomic_append(path: Path, entry: dict) -> None:
    # DRY — delegates to the shared _atomic.atomic_append_line helper
    # (also enforces append-only-sink iron-law).
    from _atomic import atomic_append_line
    atomic_append_line(path, json.dumps(entry))


def _cmd_append(args: argparse.Namespace) -> int:
    if args.stdin:
        try:
            payload = json.loads(sys.stdin.read())
        except json.JSONDecodeError as e:
            sys.stderr.write(f"learning_log: invalid JSON on stdin: {e}\n")
            return 1
    else:
        payload = {
            "category": args.category,
            "problem":  args.problem,
            "solution": args.solution,
            "pattern":  args.pattern,
        }
        if args.savings_estimate:
            payload["savings_estimate"] = args.savings_estimate
        if args.trigger_keyword:
            payload["trigger_keywords"] = list(args.trigger_keyword)
        if args.source_sid:
            payload["source_sid"] = args.source_sid
        if args.source_commit:
            payload["source_commits"] = list(args.source_commit)
        if args.reference:
            payload["references"] = list(args.reference)
        # Branch capture: explicit --branch wins; else auto-detect from cwd.
        if args.branch:
            payload["branch"] = args.branch
        else:
            detected = _detect_branch()
            if detected:
                payload["branch"] = detected
    err = _validate(payload)
    if err:
        sys.stderr.write(f"learning_log: {err}\n")
        return 1
    entry = _build_entry(payload)
    try:
        _atomic_append(_log_path(), entry)
    except OSError as e:
        sys.stderr.write(f"learning_log: write failed: {e}\n")
        return 1
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    p = _log_path()
    if not p.is_file():
        if args.json:
            print("[]")
        return 0
    entries: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if args.category:
        entries = [e for e in entries if e.get("category") == args.category]
    if args.branch:
        entries = [e for e in entries if e.get("branch") == args.branch]
    if args.json:
        print(json.dumps(entries, indent=2))
    else:
        for e in entries:
            print(f"[{e.get('ts', '?')}] {e.get('category', '?')}/"
                   f"{e.get('id', '?')}: {e.get('problem', '')}")
            print(f"  → {e.get('solution', '')}")
            print(f"  pattern: {e.get('pattern', '')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-learn",
        description="Append-only learning + evolution log.",
    )
    sub = p.add_subparsers(dest="command")

    pa = sub.add_parser("append", help="append one learning entry")
    # No argparse `choices=` — let _validate handle the rejection so the
    # exit code is consistent (1 for schema violation) across both CLI and
    # --stdin paths.
    pa.add_argument("--category",
                     help=f"entry category — one of {sorted(_VALID_CATEGORIES)}")
    pa.add_argument("--problem", help="one-line problem statement")
    pa.add_argument("--solution", help="one-line solution")
    pa.add_argument("--pattern",  help="reusable rule extracted from the solution")
    pa.add_argument("--savings-estimate", default=None,
                     help="optional savings note (e.g. '87% read cost' or '2 calls → 1')")
    pa.add_argument("--trigger-keyword", action="append", default=[],
                     help="keyword that should fire this learning (repeatable)")
    pa.add_argument("--source-sid", default=None,
                     help="originating Claude Code session UUID")
    pa.add_argument("--source-commit", action="append", default=[],
                     help="short SHA of commit(s) that landed the solution (repeatable)")
    pa.add_argument("--reference", action="append", default=[],
                     help="path:line reference to code (repeatable)")
    pa.add_argument("--branch", default=None,
                     help="override the auto-detected git branch (default: "
                          "current branch via git rev-parse on cwd)")
    pa.add_argument("--stdin", action="store_true",
                     help="read JSON payload from stdin instead of CLI flags")
    pa.set_defaults(fn=_cmd_append)

    pl = sub.add_parser("list", help="show entries")
    pl.add_argument("--category", choices=sorted(_VALID_CATEGORIES),
                     default=None, help="filter by category")
    pl.add_argument("--branch", default=None,
                     help="filter by git branch (entries whose `branch` field matches)")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(fn=_cmd_list)

    args = p.parse_args(argv)
    if not getattr(args, "fn", None):
        p.print_help()
        return 2
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
