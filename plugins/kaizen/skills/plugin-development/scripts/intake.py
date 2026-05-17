#!/usr/bin/env python3
"""kaizen intake — print the right skills-to-load bundle for a given
plugin-development work-type.

Data-driven: reads `domain/intake-checklist.yaml` from the same skill.
Substring + trigger-phrase match (first-match-wins).

## Usage

  python3 intake.py             # full table (all work-types + always-load)
  python3 intake.py new-cli     # bundle for the new-cli work-type
  python3 intake.py "bug fix"   # resolves via triggers → bug-fix bundle
  python3 intake.py --json X    # machine-readable

## Output shape

  text:  human-readable bullet list (●=always, ○=work-type-specific)
  json:  {"work_type": "<id>", "skills": [...always + work-type...]}

Skill-private (lives under `skills/plugin-development/scripts/`).
Consumed by the `/kaizen:plugin-development intake` slash verb.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


_SCRIPT_DIR = Path(__file__).resolve().parent
_CHECKLIST = _SCRIPT_DIR.parent / "domain" / "intake-checklist.yaml"


def _load_yaml(path: Path) -> dict:
    try:
        import yaml
    except ImportError:
        sys.stderr.write("[intake] PyYAML required\n")
        sys.exit(2)
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _find_work_type(target: str, work_types: list[dict]) -> dict | None:
    """First-match-wins: id exact → id substring → trigger substring."""
    t = target.strip().lower()
    if not t:
        return None
    for wt in work_types:
        if wt["id"] == t:
            return wt
    for wt in work_types:
        if t in wt["id"] or wt["id"] in t:
            return wt
    for wt in work_types:
        for trigger in wt.get("triggers", []):
            if trigger in t or t in trigger:
                return wt
    # Fallback bucket
    for wt in work_types:
        if wt["id"] == "generic-plugin-work":
            return wt
    return None


def _print_table(data: dict) -> None:
    always = data.get("always", [])
    types = data.get("work_types", [])
    print("=== plugin-development intake checklist ===\n")
    print("ALWAYS load (every task):")
    for s in always:
        print(f"  ● {s}")
    print(f"\nPer work-type ({len(types)} types):")
    for wt in types:
        triggers = wt.get("triggers", [])
        trig_str = (", ".join(repr(t) for t in triggers)
                    if triggers else "(fallback)")
        print(f"  • {wt['id']:<22}  triggers: {trig_str}")
    print("\nRun: kaizen-plugin-development intake <work-type-or-trigger>")


def _print_bundle(wt: dict, always: list[str]) -> None:
    print(f"\n[{wt['id']}] skills to load:")
    for s in always:
        print(f"  ● {s}    (always — every plugin-dev task)")
    for s in wt.get("skills", []):
        print(f"  ○ {s}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-intake",
        description="Print the skills-to-load bundle for a plugin-dev task.",
    )
    p.add_argument("work_type", nargs="?", default="",
                    help="work-type id or trigger phrase; empty → full table")
    p.add_argument("--json", action="store_true",
                    help="emit machine-readable JSON instead of bullets")
    args = p.parse_args(argv)

    data = _load_yaml(_CHECKLIST)
    always = data.get("always", [])
    types = data.get("work_types", [])

    if not args.work_type:
        if args.json:
            print(json.dumps({"always": always,
                                "work_types": [{"id": wt["id"],
                                                "triggers": wt.get("triggers", []),
                                                "skills": wt.get("skills", [])}
                                                 for wt in types]}, indent=2))
        else:
            _print_table(data)
        return 0

    wt = _find_work_type(args.work_type, types)
    if wt is None:
        sys.stderr.write(f"[intake] no work-type match for: {args.work_type!r}\n")
        return 1

    if args.json:
        print(json.dumps({"work_type": wt["id"],
                            "skills": always + wt.get("skills", [])}, indent=2))
    else:
        _print_bundle(wt, always)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
