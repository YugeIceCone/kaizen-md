"""kaizen-progress — atomic-append CLI for .kaizen/workflow/progress.md.

Replaces the Read-then-Edit dance that costs ~2 tool calls + ~2KB of
context per row. Atomic O_APPEND, never reads the existing file.

Subcommands:
  append   — write one canonical row (from CLI flags or --stdin JSON)

Iron-laws:
  - append-only — NEVER reads the existing file (verified by test:
    file-size delta on a seeded 100KB log is < 200 bytes)
  - schema-validates the payload BEFORE writing (date / kind / loc /
    summary); invalid input exits 1 + writes nothing
  - creates the file with the canonical 4-column header if absent
  - row format: `| YYYY-MM-DD | <kind> | <loc> | <summary> |`

Schema at schemas/workflow/schemas/architecture-log-row.schema.json
is the source of truth; this module mirrors its rules in stdlib regex
checks (no jsonschema dep — keeps the gate's pre-commit footprint tiny).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_VALID_KINDS = frozenset({
    "feat", "fix", "refactor", "chore", "docs", "test", "perf",
})
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LOC_RE = re.compile(r"^[+\-~][\d~]+(\s+[+\-][\d~]+)?$")

_HEADER = (
    "# Architecture Log\n"
    "\n"
    "| Date | Kind | ΔLOC | Summary |\n"
    "|------|------|------|---------|\n"
)

def _validate(payload: dict) -> str | None:
    """Return error message string on invalid payload, else None."""
    if not isinstance(payload, dict):
        return f"payload must be a dict, got {type(payload).__name__}"
    for k in ("date", "kind", "loc", "summary"):
        if k not in payload:
            return f"missing required field: {k}"
    if not isinstance(payload["date"], str) or not _DATE_RE.match(payload["date"]):
        return f"invalid date {payload['date']!r}; expected YYYY-MM-DD"
    if payload["kind"] not in _VALID_KINDS:
        return (f"invalid kind {payload['kind']!r}; expected one of "
                 f"{sorted(_VALID_KINDS)}")
    if not isinstance(payload["loc"], str) or not _LOC_RE.match(payload["loc"]):
        return f"invalid loc {payload['loc']!r}; expected `+N`, `-N`, `+N -M`, or `+~N`"
    summary = payload["summary"]
    if not isinstance(summary, str) or not summary.strip():
        return "summary must be a non-empty string"
    if ": " in summary:
        return (f"summary must not contain `: ` (colon-space) — trips "
                f"YAML / table parsers. Use ` — ` or `;` instead.")
    return None

def _render_row(payload: dict) -> str:
    return (f"| {payload['date']} | {payload['kind']} | "
             f"{payload['loc']} | {payload['summary']} |")

def _atomic_append(path: Path, row: str) -> None:
    """Append `row` (one line) to `path`. Creates the file with the
    canonical 4-column header if absent. NEVER reads existing — preserves
    the append-only-sink iron-law (delta cost is constant).

    Delegates to the shared _atomic.atomic_append_line helper (DRY).
    """
    _here = Path(__file__).resolve().parent
    sys.path.insert(0, str(_here.parent / "io"))
    from _atomic import atomic_append_line
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        # Header bootstrap is a one-shot write (not append-with-content);
        # use raw write — atomic_append_line is for per-row appends.
        path.write_text(_HEADER, encoding="utf-8")
    atomic_append_line(path, row)

# Row parser — the .md and .jsonl form must round-trip cleanly.
# `| YYYY-MM-DD | <kind> | <loc> | <summary> |` → {"date","scope","delta","summary"}.
# Field names diverge between the two surfaces (kind/loc in .md, scope/delta in
# .jsonl) for back-compat with the pre-existing progress.jsonl shape.
_ROW_RE = re.compile(
    r"^\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(.+?)\s*\|\s*$"
)

def _parse_md_rows(text: str) -> list[dict]:
    rows: list[dict] = []
    for line in text.splitlines():
        m = _ROW_RE.match(line)
        if not m:
            continue
        rows.append({
            "date":    m.group(1),
            "scope":   m.group(2),
            "delta":   m.group(3),
            "summary": m.group(4),
        })
    return rows

def _render_jsonl(rows: list[dict]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)

def _cmd_regen(args: argparse.Namespace) -> int:
    md_path = Path(args.file)
    if not md_path.is_file():
        sys.stderr.write(f"progress_log: file not found: {md_path}\n")
        return 1
    rows = _parse_md_rows(md_path.read_text(encoding="utf-8"))
    new_blob = _render_jsonl(rows)
    jsonl_path = md_path.with_suffix(".jsonl")
    existing = jsonl_path.read_bytes() if jsonl_path.exists() else b""
    if existing == new_blob.encode("utf-8"):
        sys.stdout.write(f"progress_log: in sync ({len(rows)} rows)\n")
        return 0
    if args.dry_run:
        sys.stderr.write(
            f"progress_log: drift — {len(rows)} rows in {md_path.name} vs "
            f"{len(existing.splitlines())} in {jsonl_path.name} (re-run without --dry-run to fix)\n"
        )
        return 0
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: write to a sibling temp + rename (avoids torn writes if
    # the regen is interrupted mid-flight).
    tmp = jsonl_path.with_suffix(".jsonl.tmp")
    tmp.write_text(new_blob, encoding="utf-8")
    tmp.replace(jsonl_path)
    sys.stdout.write(
        f"progress_log: regen → {jsonl_path.name} ({len(rows)} rows)\n")
    return 0

def _cmd_append(args: argparse.Namespace) -> int:
    if args.stdin:
        try:
            payload = json.loads(sys.stdin.read())
        except json.JSONDecodeError as e:
            sys.stderr.write(f"progress_log: invalid JSON on stdin: {e}\n")
            return 1
    else:
        payload = {
            "date":    args.date,
            "kind":    args.kind,
            "loc":     args.loc,
            "summary": args.summary,
        }
    err = _validate(payload)
    if err:
        sys.stderr.write(f"progress_log: {err}\n")
        return 1
    row = _render_row(payload)
    try:
        _atomic_append(Path(args.file), row)
    except OSError as e:
        sys.stderr.write(f"progress_log: write failed: {e}\n")
        return 1
    return 0

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-progress",
        description="Atomic-append CLI for .kaizen/workflow/progress.md.",
    )
    sub = p.add_subparsers(dest="command")

    pa = sub.add_parser("append", help="append one row to the architecture log")
    pa.add_argument("--file", required=True, help="path to progress.md")
    pa.add_argument("--date",    help="YYYY-MM-DD")
    pa.add_argument("--kind",    help=f"one of {sorted(_VALID_KINDS)}")
    pa.add_argument("--loc",     help="net LOC delta: `+N` / `-N` / `+N -M` / `+~N`")
    pa.add_argument("--summary", help="one-line summary (no `: ` colon-space)")
    pa.add_argument("--stdin", action="store_true",
                     help="read JSON payload from stdin instead of CLI flags")
    pa.set_defaults(fn=_cmd_append)

    pr = sub.add_parser(
        "regen",
        help="parse progress.md and rewrite the sibling progress.jsonl in place",
    )
    pr.add_argument("--file", required=True, help="path to progress.md")
    pr.add_argument("--dry-run", action="store_true",
                     help="report drift between .md and .jsonl without writing")
    pr.set_defaults(fn=_cmd_regen)

    args = p.parse_args(argv)
    if not getattr(args, "fn", None):
        p.print_help()
        return 2
    return args.fn(args)

if __name__ == "__main__":
    sys.exit(main())
