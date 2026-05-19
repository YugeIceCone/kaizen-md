#!/usr/bin/env python3
"""kaizen-frontmatter — SKILL.md frontmatter conformance audit.

Two checks per SKILL.md:
  1. `name:` field MUST match the parent dir basename
     (skills/foo/SKILL.md → name: foo). Drift here means
     skill-suggest can't route the skill correctly.
  2. `description:` field SHOULD contain >= 3 quoted trigger phrases
     ("...", '...') so skill-suggest's router has hooks to match
     against user prompts. Descriptions with <3 quoted phrases are
     near-invisible to the router.

Stdlib-only regex. Subcommands: report / gaps. Mirrors the existing
axis pattern (token-bloat / coverage / schema-coverage / name-quality).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


_SCRIPT_DIR = Path(__file__).resolve().parent


def _plugin_root() -> Path:
    return _SCRIPT_DIR.parents[1]


_FM_RE   = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
_NAME_RE = re.compile(r"^name:\s*(\S+)\s*$", re.MULTILINE)
_DESC_RE = re.compile(r"^description:\s*(.+?)$", re.MULTILINE)
# Trigger phrase = anything wrapped in double or single quotes
_QUOTED_RE = re.compile(r"\"[^\"\n]{2,}\"|'[^'\n]{2,}'")

# Minimum quoted trigger phrases — fewer than this is "weak routing"
_MIN_TRIGGERS = 3


def audit_skill(skill_dir: Path) -> dict:
    """Per-skill audit. Returns {skill, name_match, name_field,
    trigger_count, gaps:[...], conformant: bool}."""
    md = skill_dir / "SKILL.md"
    out = {
        "skill":         skill_dir.name,
        "path":          str(md),
        "name_field":    "",
        "name_match":    False,
        "trigger_count": 0,
        "gaps":          [],
        "conformant":    False,
    }
    if not md.is_file():
        return out
    try:
        text = md.read_text(encoding="utf-8")
    except OSError:
        return out
    fm = _FM_RE.match(text)
    if not fm:
        out["gaps"].append("no-frontmatter")
        return out
    nm = _NAME_RE.search(fm.group(1))
    if not nm:
        out["gaps"].append("no-name-field")
    else:
        out["name_field"] = nm.group(1)
        out["name_match"] = (nm.group(1) == skill_dir.name)
        if not out["name_match"]:
            out["gaps"].append(
                f"name-mismatch: name={nm.group(1)!r} dir={skill_dir.name!r}")
    dm = _DESC_RE.search(fm.group(1))
    if dm:
        out["trigger_count"] = len(_QUOTED_RE.findall(dm.group(1)))
        if out["trigger_count"] < _MIN_TRIGGERS:
            out["gaps"].append(
                f"weak-routing: {out['trigger_count']} quoted "
                f"phrase(s) (<{_MIN_TRIGGERS})")
    else:
        out["gaps"].append("no-description-field")
    out["conformant"] = (out["name_match"]
                          and out["trigger_count"] >= _MIN_TRIGGERS)
    return out


def all_audits(root: Path | None = None) -> list[dict]:
    root = root or _plugin_root()
    skills = root / "skills"
    if not skills.is_dir():
        return []
    out = []
    for p in sorted(skills.iterdir()):
        if not p.is_dir():
            continue
        if not (p / "SKILL.md").is_file():
            continue
        out.append(audit_skill(p))
    return out


def _print_text(reports: list[dict]) -> None:
    conformant = [r for r in reports if r["conformant"]]
    with_gaps = [r for r in reports if r["gaps"]]
    print(f"frontmatter: {len(reports)} skill(s) — "
          f"{len(conformant)} conformant, {len(with_gaps)} with gaps")
    for r in reports:
        if r["conformant"]:
            continue
        print(f"  △ {r['skill']:30s} triggers={r['trigger_count']}  "
              f"name={'✓' if r['name_match'] else '✗'}")
        for g in r["gaps"]:
            print(f"      ⚠ {g}")


def _cmd_report(args) -> int:
    reports = all_audits()
    if args.json:
        print(json.dumps(reports, indent=2))
    else:
        _print_text(reports)
    return 0


def _cmd_gaps(args) -> int:
    reports = [r for r in all_audits() if r["gaps"]]
    if args.json:
        print(json.dumps(reports, indent=2))
    else:
        _print_text(reports)
    return 1 if reports else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-frontmatter",
        description="SKILL.md frontmatter audit: name matches dir + trigger-phrase count",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("report", help="full audit")
    pr.add_argument("--json", action="store_true")
    pr.set_defaults(func=_cmd_report)

    pg = sub.add_parser("gaps", help="only skills with gaps (exit 1 if any)")
    pg.add_argument("--json", action="store_true")
    pg.set_defaults(func=_cmd_gaps)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
