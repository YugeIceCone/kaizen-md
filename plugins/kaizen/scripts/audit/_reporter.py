#!/usr/bin/env python3
"""kaizen audit — finding aggregator + report renderer.

Takes N findings (each conforming to `audit-finding.schema.json`) and
emits one `audit-report.schema.json`-conforming aggregate. Computes:

  - run_id (auto: audit-YYYYMMDD-HHMMSS UTC)
  - verdict (green / leaks / violated — based on P0/P1 counts)
  - counts.{p0,p1,p2,p3,applied,trailed,reported_only}
  - recommended_next_step

Both schemas live at `skills/audit/domain/schemas/`. The reporter
validates input findings AND output report at the boundary (when
`jsonschema` is available; degrades gracefully like the workflow + karpathy
+ etu loaders).

## CLI

    python3 _reporter.py aggregate --findings findings.json
        [--scope 'src/foo/'] [--out report.json]

  findings.json: JSON array of audit-finding records (any source).
  Reads stdin if --findings not given. Writes to --out or stdout.

## Library use

    from _reporter import aggregate
    report = aggregate(findings_list, scope_target='src/foo/')
"""
from __future__ import annotations

import argparse
import datetime as _dt
import importlib.util
import json
import sys
import uuid
from pathlib import Path

# Domain yaml stays at skills/audit/domain/; only the .py adapter migrated.
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
_DOMAIN_DIR = _PLUGIN_ROOT / "skills" / "audit" / "domain"
_FINDING_SCHEMA = _DOMAIN_DIR / "schemas" / "audit-finding.schema.json"
_REPORT_SCHEMA = _DOMAIN_DIR / "schemas" / "audit-report.schema.json"

try:
    from jsonschema import Draft202012Validator, ValidationError  # type: ignore
    from referencing import Registry, Resource  # type: ignore
    from referencing.jsonschema import DRAFT202012  # type: ignore
    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False

def _local_registry() -> "Registry":
    """Build a referencing Registry that resolves the audit schemas locally,
    so the `$ref: audit-finding.schema.json` in audit-report doesn't trigger
    a network fetch."""
    reg = Registry()
    for sp in (_FINDING_SCHEMA, _REPORT_SCHEMA):
        body = json.loads(sp.read_text())
        resource = Resource.from_contents(body, default_specification=DRAFT202012)
        reg = reg.with_resource(body["$id"], resource)
        # Also register the bare filename so relative $refs resolve.
        reg = reg.with_resource(sp.name, resource)
    return reg

def _validate(instance, schema_path: Path, source: str) -> None:
    if not _HAS_JSONSCHEMA:
        return
    schema = json.loads(schema_path.read_text())
    validator = Draft202012Validator(schema, registry=_local_registry())
    errors = sorted(validator.iter_errors(instance), key=lambda e: e.path)
    if errors:
        e = errors[0]
        sys.stderr.write(
            f"kaizen audit reporter: {source} fails schema:\n"
            f"  {e.message}\n  path: {list(e.absolute_path)}\n"
        )
        sys.exit(2)

def _run_id(now: _dt.datetime | None = None) -> str:
    now = now or _dt.datetime.now(_dt.timezone.utc)
    return now.strftime("audit-%Y%m%d-%H%M%S")

def _verdict(findings: list[dict]) -> str:
    sevs = {f["severity"] for f in findings}
    if "P0" in sevs:
        return "violated"
    if "P1" in sevs:
        return "leaks"
    return "green"

def _counts(findings: list[dict]) -> dict[str, int]:
    out = {"p0": 0, "p1": 0, "p2": 0, "p3": 0,
           "applied": 0, "trailed": 0, "reported_only": 0}
    for f in findings:
        sev = f["severity"].lower()  # P0 → p0
        out[sev] = out.get(sev, 0) + 1
        disp = f.get("disposition", "reported-only").replace("-", "_")
        if disp in out:
            out[disp] += 1
    return out

def _recommended(verdict: str, counts: dict[str, int]) -> str:
    if verdict == "violated" or verdict == "leaks":
        return "plan-execute"
    if counts["p2"] + counts["p3"] == 0:
        return "ship-as-is"
    return "ship-as-is"  # no P0/P1; minor smells only

def aggregate(
    findings: list[dict],
    scope_target: str = "whole-repo",
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    now: _dt.datetime | None = None,
) -> dict:
    """Validate findings, build the aggregate report record, validate it,
    return as dict."""
    for i, f in enumerate(findings):
        _validate(f, _FINDING_SCHEMA, source=f"findings[{i}]")

    sorted_findings = sorted(
        findings, key=lambda f: ("P0", "P1", "P2", "P3").index(f["severity"])
    )

    report = {
        "run_id": _run_id(now),
        "scope": {"target": scope_target},
        "verdict": _verdict(findings),
        "findings": sorted_findings,
        "counts": _counts(findings),
        "completed_at": (now or _dt.datetime.now(_dt.timezone.utc)).isoformat(),
    }
    if include_globs:
        report["scope"]["include_globs"] = include_globs
    if exclude_globs:
        report["scope"]["exclude_globs"] = exclude_globs
    report["recommended_next_step"] = _recommended(report["verdict"], report["counts"])

    _validate(report, _REPORT_SCHEMA, source="output report")
    return report

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="audit-reporter")
    sub = parser.add_subparsers(dest="cmd", required=True)
    agg = sub.add_parser("aggregate", help="aggregate findings into a report")
    agg.add_argument("--findings", type=Path, help="JSON file with array of findings; stdin if omitted")
    agg.add_argument("--scope", default="whole-repo")
    agg.add_argument("--out", type=Path, help="write JSON report to this path; stdout if omitted")
    args = parser.parse_args(argv)

    if args.cmd != "aggregate":
        parser.print_help()
        return 2

    if args.findings:
        findings = json.loads(args.findings.read_text())
    else:
        raw = sys.stdin.read()
        findings = json.loads(raw) if raw.strip() else []

    report = aggregate(findings, scope_target=args.scope)
    out_text = json.dumps(report, indent=2)
    if args.out:
        args.out.write_text(out_text + "\n")
        sys.stderr.write(f"wrote {args.out}\n")
    else:
        print(out_text)
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
