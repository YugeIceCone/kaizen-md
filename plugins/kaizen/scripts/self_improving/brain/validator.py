#!/usr/bin/env python3
"""kaizen brain validator — schema-validate Notes + cross-link health.

## Usage

    python3 validator.py validate          # validate all Notes against schema
    python3 validator.py links             # check [[Notes/name]] cross-links
    python3 validator.py all               # everything (default for CI)
    python3 validator.py belief-stats      # confidence / sources / freshness distribution

## Exits

  0 — all green
  1 — schema validation failed
  2 — cross-link broken
  3 — file system issue (no brain etc)
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# Resolve brain root via the kaizen SSOT (v1.38.0+).
# Post-migration: this file lives at scripts/self_improving/brain/validator.py.
SCRIPT_DIR = Path(__file__).resolve().parent
_PLUGIN_ROOT = SCRIPT_DIR.parents[2]
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts" / "io"))
import _paths  # noqa: E402

BRAIN = _paths.BRAIN_DIR
SCHEMA = _PLUGIN_ROOT / "skills" / "brain" / "domain" / "schemas" / "note.schema.json"

try:
    import yaml
except ImportError:
    sys.stderr.write("[brain-validator] pyyaml required\n")
    sys.exit(3)

try:
    from jsonschema import validate as _validate, ValidationError
    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False


def _coerce_dates(d):
    """Recursively convert datetime.date / datetime.datetime to ISO strings.

    PyYAML auto-parses `created: 2026-05-10` into a date object, but JSON
    Schema expects strings. Coerce at read-time so downstream validation
    sees the string form."""
    import datetime as _dt
    if isinstance(d, dict):
        return {k: _coerce_dates(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_coerce_dates(v) for v in d]
    if isinstance(d, (_dt.date, _dt.datetime)):
        return d.isoformat()
    return d


def _read_frontmatter(path: Path) -> dict | None:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return None
    return _coerce_dates(yaml.safe_load(m.group(1)) or {})


def cmd_validate() -> int:
    if not BRAIN.exists():
        print(f"OK: brain not present at {BRAIN} — skipping")
        return 0
    if not _HAS_JSONSCHEMA:
        print("WARN: jsonschema not installed — skipping schema validation")
        return 0
    schema = json.loads(SCHEMA.read_text())
    errors = 0
    notes = list((BRAIN / "Notes").glob("*.md"))
    for n in notes:
        fm = _read_frontmatter(n)
        if fm is None:
            print(f"[skip] no frontmatter: {n.name}")
            continue
        try:
            _validate(fm, schema)
        except ValidationError as e:
            print(f"[FAIL] {n.name}: {e.message}")
            errors += 1
    if errors:
        print(f"validate: {errors} error(s) across {len(notes)} notes")
        return 1
    print(f"OK: {len(notes)} notes validated against schema")
    return 0


def cmd_links() -> int:
    if not BRAIN.exists():
        print("OK: brain not present")
        return 0
    # Find every [[name]] reference in Persona.md + all Notes
    files = [BRAIN / "Persona.md"] + list((BRAIN / "Notes").glob("*.md"))
    files = [f for f in files if f.exists()]
    refs: list[tuple[Path, str]] = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        for m in re.finditer(r"\[\[([A-Za-z0-9/_\-\.]+)\]\]", text):
            refs.append((f, m.group(1)))

    broken = []
    for src, ref in refs:
        # Try common resolutions
        name = ref.removesuffix(".md")
        # Bare "name" → Notes/name.md
        candidates = [
            BRAIN / "Notes" / f"{name}.md",
            BRAIN / f"{name}.md",
            BRAIN / ref,
        ]
        # "Journal/2026-05-10" form
        if "/" in name:
            candidates.append(BRAIN / f"{name}.md")
        if not any(c.exists() for c in candidates):
            broken.append((src.name, ref))

    if broken:
        print(f"links: {len(broken)} broken")
        for src, ref in broken[:20]:
            print(f"  [BROKEN] {src} → [[{ref}]]")
        return 2
    print(f"OK: {len(refs)} cross-references all resolve")
    return 0


def cmd_belief_stats() -> int:
    if not BRAIN.exists():
        print("brain not present")
        return 0
    notes = list((BRAIN / "Notes").glob("pref-*.md"))
    if not notes:
        print("no pref-*.md notes found")
        return 0

    by_freshness: dict[str, int] = {}
    by_sources: dict[int, int] = {}
    confidences: list[float] = []

    for n in notes:
        fm = _read_frontmatter(n) or {}
        f = fm.get("freshness", "unknown")
        by_freshness[f] = by_freshness.get(f, 0) + 1
        s = int(fm.get("sources_count", 0))
        by_sources[s] = by_sources.get(s, 0) + 1
        if isinstance(fm.get("confidence"), (int, float)):
            confidences.append(float(fm["confidence"]))

    print(f"pref-*.md notes: {len(notes)}")
    print(f"freshness: {dict(sorted(by_freshness.items()))}")
    print(f"sources_count distribution: {dict(sorted(by_sources.items()))}")
    if confidences:
        avg = sum(confidences) / len(confidences)
        print(f"confidence: min={min(confidences):.2f}  avg={avg:.2f}  max={max(confidences):.2f}")
    return 0


def cmd_all() -> int:
    rc1 = cmd_validate()
    rc2 = cmd_links()
    return rc1 or rc2


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd == "validate":
        sys.exit(cmd_validate())
    if cmd == "links":
        sys.exit(cmd_links())
    if cmd == "belief-stats":
        sys.exit(cmd_belief_stats())
    if cmd == "all":
        sys.exit(cmd_all())
    sys.stderr.write(f"unknown command: {cmd}\n")
    sys.exit(2)
