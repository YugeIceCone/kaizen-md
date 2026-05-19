#!/usr/bin/env python3
"""kaizen memory-ledger — catalog + status + flow over the memory
& continuity-flow surfaces declared in
skills/memory-ledger/domain/memory-surfaces.yaml.

Read-only observability. Owners (brain, backlog, handoff, gold, dxm,
trace, inbox, chatlog) keep their existing CLIs — this surface
catalogs WHERE memory lives + audits scope discipline.

Verbs:
  catalog [--json]   List every declared surface with name / scope / path /
                     auto-load + counts summary.
  status  [--json]   Sample each surface on disk: exists, size, mtime.
                     Missing-when-declared → warn finding.
  flow    [--json]   Walk the continuity_flow phases (session_start →
                     between_sessions). Useful for orientation.

Bypass: KAIZEN_MEMORY_LEDGER_DISABLE=1 — every verb is a silent no-op.

Per BK-024 scope discipline: surfaces declare project | global.
Future iron-law candidate (ML-005) walks this manifest to block
scope-mismatched writes.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PLUGIN_ROOT = _SCRIPT_DIR.parent.parent
_MANIFEST = _PLUGIN_ROOT / "skills" / "memory-ledger" / "domain" / "memory-surfaces.yaml"


def _load_manifest() -> dict:
    try:
        import yaml
    except ImportError:
        sys.stderr.write(
            "kaizen-memory-ledger: pyyaml missing — pip install pyyaml\n")
        sys.exit(1)
    if not _MANIFEST.is_file():
        sys.stderr.write(f"kaizen-memory-ledger: manifest missing at {_MANIFEST}\n")
        sys.exit(1)
    return yaml.safe_load(_MANIFEST.read_text(encoding="utf-8")) or {}


def _repo_root() -> Path:
    """Resolve repo root for path expansion of `<repo>` placeholders."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=2, check=False,
        )
        if r.returncode == 0 and r.stdout.strip():
            return Path(r.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.cwd().resolve()


def _repo_slug() -> str:
    return str(_repo_root()).replace("/", "-")


def _expand_path(p: str) -> Path:
    """Expand placeholders + ~ in a manifest path. Returns the
    resolved Path; existence not asserted (caller's job)."""
    s = (p
         .replace("<repo>", str(_repo_root()))
         .replace("<repo-slug>", _repo_slug()))
    return Path(s).expanduser()


# ─── Verbs ──────────────────────────────────────────────────────────


def cmd_catalog(args) -> int:
    m = _load_manifest()
    surfaces = m.get("surfaces") or []
    out_surfaces: list[dict] = []
    by_scope = {"project": 0, "global": 0}
    by_owner: dict[str, int] = {}
    auto_load_count = 0
    for s in surfaces:
        out_surfaces.append({
            "id":             s["id"],
            "name":           s.get("name", s["id"]),
            "owner_feature":  s["owner_feature"],
            "scope":          s["scope"],
            "path":           s["path"],
            "auto_load":      bool(s.get("auto_load", False)),
            "auto_load_via":  s.get("auto_load_via", ""),
            "role":           s.get("role", ""),
            "refresh":        s.get("refresh", ""),
        })
        by_scope[s["scope"]] = by_scope.get(s["scope"], 0) + 1
        by_owner[s["owner_feature"]] = by_owner.get(s["owner_feature"], 0) + 1
        if s.get("auto_load"):
            auto_load_count += 1
    envelope = {
        "surfaces": out_surfaces,
        "counts": {
            "total":     len(out_surfaces),
            "auto_load": auto_load_count,
            "by_scope":  by_scope,
            "by_owner":  by_owner,
        },
    }
    if args.json:
        print(json.dumps(envelope, indent=2))
        return 0
    print(f"\n[kaizen-memory-ledger catalog] {len(out_surfaces)} surfaces  "
          f"(project={by_scope['project']} global={by_scope['global']} "
          f"auto_load={auto_load_count})")
    for s in out_surfaces:
        badge = "★" if s["auto_load"] else " "
        print(f"  {badge} {s['id']:24s} {s['scope']:7s} {s['owner_feature']:14s} {s['path']}")
    return 0


def cmd_status(args) -> int:
    m = _load_manifest()
    surfaces = m.get("surfaces") or []
    findings: list[dict] = []
    present = missing = 0
    for s in surfaces:
        path = _expand_path(s["path"])
        # Glob / template patterns can't be stat'd literally — fall back
        # to checking the closest existing ancestor. `<session>` /
        # `<date>` are template placeholders the manifest uses for
        # per-session / per-date scope.
        templated = ("*" in s["path"] or "{" in s["path"]
                     or "<session>" in s["path"] or "<date>" in s["path"])
        target = path
        if templated:
            # Walk up until we find an existing ancestor (or root)
            target = path.parent
            while not target.exists() and target != target.parent:
                target = target.parent
        exists = target.exists()
        if exists:
            present += 1
            findings.append({
                "id":       s["id"],
                "path":     str(path),
                "exists":   True,
                "severity": "info",
            })
        else:
            missing += 1
            findings.append({
                "id":       s["id"],
                "path":     str(path),
                "exists":   False,
                "severity": "warn",
                "detail":   "declared in manifest but not present on disk",
            })
    envelope = {
        "summary":  {"present": present, "missing": missing,
                     "total": len(surfaces)},
        "findings": findings,
    }
    if args.json:
        print(json.dumps(envelope, indent=2))
        return 0
    print(f"\n[kaizen-memory-ledger status] present={present}  missing={missing}  "
          f"total={len(surfaces)}")
    for f in findings:
        mark = "✓" if f["exists"] else "✗"
        print(f"  {mark} {f['id']:24s} {f['path']}")
        if not f["exists"]:
            print(f"      {f.get('detail', '')}")
    # Missing surfaces are findings, not failures. Caller decides via
    # envelope.summary.missing — rc=0 keeps the verb composable with
    # `set -e` scripts.
    return 0


def cmd_flow(args) -> int:
    m = _load_manifest()
    phases = m.get("continuity_flow") or []
    envelope = {"phases": phases}
    if args.json:
        print(json.dumps(envelope, indent=2))
        return 0
    print("\n[kaizen-memory-ledger flow]")
    for p in phases:
        print(f"\n  ── {p['phase']} ──")
        print(f"  {p.get('description','')}")
        surfaces = p.get("surfaces") or []
        if surfaces:
            print(f"  surfaces: {', '.join(surfaces)}")
        verbs = p.get("verbs") or []
        if verbs:
            print(f"  verbs:    {' | '.join(verbs)}")
    return 0


# ─── CLI ────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    if os.environ.get("KAIZEN_MEMORY_LEDGER_DISABLE") == "1":
        return 0

    p = argparse.ArgumentParser(
        prog="kaizen-memory-ledger",
        description="Catalog + status + flow over memory & continuity surfaces.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_catalog = sub.add_parser("catalog", help="list every declared surface")
    p_catalog.add_argument("--json", action="store_true")
    p_catalog.set_defaults(func=cmd_catalog)

    p_status = sub.add_parser("status", help="sample each surface on disk")
    p_status.add_argument("--json", action="store_true")
    p_status.set_defaults(func=cmd_status)

    p_flow = sub.add_parser("flow", help="walk the continuity-of-session phases")
    p_flow.add_argument("--json", action="store_true")
    p_flow.set_defaults(func=cmd_flow)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
