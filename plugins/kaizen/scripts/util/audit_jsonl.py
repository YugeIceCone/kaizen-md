"""kaizen audit regen-jsonl — backfill .jsonl siblings for older audit reports.

Walks <repo>/.kaizen/workflow/audits/*.md and writes a paired *.jsonl
sibling for each .md that doesn't have one. One JSON record per finding
(severity / text / report / scope / total). Idempotent — already-paired
reports are left alone unless --force is passed.

Pairs the audit reports with the same `jq`-able convention as
progress.md / progress.jsonl (see pref-jsonl-indexed-deliverables).

# consolidated-cli-parent: audit
The wrapper requirement transfers to bin/kaizen-audit which dispatches
`kaizen-audit regen-jsonl` to this script.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

def _audits_dir(repo: Path) -> Path:
    return repo / ".kaizen" / "workflow" / "audits"

def _parse_report(text: str) -> dict:
    """Re-export of audit_mcp.parse_report so this script doesn't
    have to add fastmcp to its import path."""
    here = Path(__file__).resolve().parent
    sys.path.insert(0, str(here.parent / "mcp"))
    from audit_mcp import parse_report
    return parse_report(text)

def _render_jsonl(parsed: dict, report_name: str) -> str:
    """One JSON line per finding — context fields (report / scope /
    total) replicated on every row so jq slices don't have to join."""
    rows = []
    for f in parsed["findings"]:
        rows.append(json.dumps({
            "report":   report_name,
            "scope":    parsed["scope"],
            "total":    parsed["total"],
            "severity": f["severity"],
            "text":     f["text"],
        }, ensure_ascii=False))
    return "\n".join(rows) + ("\n" if rows else "")

def _regen_one(md: Path, *, force: bool, dry_run: bool) -> str:
    """Return one of 'paired' / 'wrote' / 'skipped' / 'dry-run'."""
    jsonl = md.with_suffix(".jsonl")
    if jsonl.exists() and not force:
        return "paired"
    parsed = _parse_report(md.read_text(encoding="utf-8"))
    blob = _render_jsonl(parsed, md.name)
    if not blob:
        # Report has no findings at all — skip rather than write empty.
        return "skipped"
    if dry_run:
        return "dry-run"
    tmp = jsonl.with_suffix(".jsonl.tmp")
    tmp.write_text(blob, encoding="utf-8")
    tmp.replace(jsonl)
    return "wrote"

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-audit regen-jsonl",
        description=__doc__.splitlines()[0],
    )
    p.add_argument("--repo", default=".",
                    help="repo root (default: cwd)")
    p.add_argument("--force", action="store_true",
                    help="re-write even if .jsonl already exists")
    p.add_argument("--dry-run", action="store_true",
                    help="report what would be written, write nothing")
    p.add_argument("--json", action="store_true",
                    help="machine-readable summary on stdout")
    args = p.parse_args(argv)

    repo = Path(args.repo).resolve()
    ad = _audits_dir(repo)
    if not ad.is_dir():
        sys.stderr.write(f"audit_jsonl: no audits dir at {ad}\n")
        return 1

    summary = {"paired": 0, "wrote": 0, "skipped": 0, "dry-run": 0}
    details: list[dict] = []
    for md in sorted(ad.glob("*.md")):
        status = _regen_one(md, force=args.force, dry_run=args.dry_run)
        summary[status] += 1
        details.append({"file": md.name, "status": status})

    if args.json:
        sys.stdout.write(json.dumps(
            {"summary": summary, "details": details},
            ensure_ascii=False,
        ) + "\n")
    else:
        msg = ", ".join(f"{k}={v}" for k, v in summary.items() if v)
        sys.stdout.write(
            f"audit_jsonl: {msg or 'nothing to do'} "
            f"({len(details)} report(s))\n"
        )
    return 0

if __name__ == "__main__":
    sys.exit(main())
