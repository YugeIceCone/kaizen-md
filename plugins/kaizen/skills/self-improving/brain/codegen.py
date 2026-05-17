#!/usr/bin/env python3
"""kaizen brain codegen — regenerate Persona.md sections from Notes.

## What it does

Scans `~/.claude/.kaizen/brain/Notes/pref-*.md`, sorts by confidence × sources_count,
and emits a canonical `## Top Beliefs` block. Either previews to stdout or
writes back to Persona.md preserving the surrounding sections.

## Usage

    python3 codegen.py preview          # print regenerated block to stdout
    python3 codegen.py write            # write to Persona.md in place
    python3 codegen.py --check          # exit non-zero if Persona drifted

## Idempotency

Running `write` twice produces byte-identical Persona.md after the first.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# Resolve brain root via the kaizen SSOT (v1.38.0+).
_SCRIPTS = Path(__file__).resolve().parents[2] / "workflow" / "scripts"
sys.path.insert(0, str(_SCRIPTS))
import _paths  # noqa: E402

BRAIN = _paths.BRAIN_DIR
PERSONA = _paths.BRAIN_PERSONA

try:
    import yaml
except ImportError:
    sys.stderr.write("[brain-codegen] pyyaml required\n")
    sys.exit(1)


def _read_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return {}
    return yaml.safe_load(m.group(1)) or {}


def gather_beliefs() -> list[dict]:
    """Read every pref-*.md and return a sorted list of belief metadata."""
    beliefs: list[dict] = []
    for n in (BRAIN / "Notes").glob("pref-*.md"):
        fm = _read_frontmatter(n)
        if fm.get("type") != "belief":
            continue
        beliefs.append({
            "file": n.name,
            "stem": n.stem,
            "confidence": float(fm.get("confidence", 0.0)),
            "sources_count": int(fm.get("sources_count", 0)),
            "freshness": fm.get("freshness", "unknown"),
            "tags": fm.get("tags", []),
        })
    # Sort: highest confidence × sources first; freshness tie-breaker
    freshness_order = {"hardened": 3, "stable": 2, "fresh": 1, "stale": 0, "archived": -1, "unknown": -2}
    beliefs.sort(
        key=lambda b: (
            -b["confidence"] * max(b["sources_count"], 1),
            -freshness_order.get(b["freshness"], -2),
            b["stem"],
        )
    )
    return beliefs


def render_top_beliefs(beliefs: list[dict]) -> str:
    """Render the ## Top Beliefs section."""
    lines = ["## Top Beliefs\n"]
    for i, b in enumerate(beliefs, 1):
        lines.append(
            f"{i}. [[Notes/{b['stem']}.md]] — "
            f"conf={b['confidence']:.2f} "
            f"sources={b['sources_count']} "
            f"freshness={b['freshness']}"
        )
    return "\n".join(lines) + "\n"


def splice_section(persona_text: str, new_section: str) -> str:
    """Replace the `## Top Beliefs` section in Persona.md with `new_section`.

    Preserves everything before the section and everything from the next `## `
    onward. If the section doesn't exist, append before `## Evidence Log` or at end.
    """
    pattern = re.compile(r"^## Top Beliefs\s*\n", re.MULTILINE)
    m = pattern.search(persona_text)
    if not m:
        # Try to insert before ## Evidence Log
        evidence = re.search(r"^## Evidence Log", persona_text, re.MULTILINE)
        if evidence:
            insert_at = evidence.start()
            return persona_text[:insert_at] + new_section + "\n" + persona_text[insert_at:]
        return persona_text.rstrip() + "\n\n" + new_section
    # Find end of section (next ## heading or EOF)
    start = m.start()
    next_h = re.search(r"^## ", persona_text[m.end():], re.MULTILINE)
    end = m.end() + next_h.start() if next_h else len(persona_text)
    return persona_text[:start] + new_section + "\n" + persona_text[end:]


def cmd_preview() -> int:
    if not BRAIN.exists():
        print("brain not present — nothing to preview")
        return 0
    beliefs = gather_beliefs()
    print(render_top_beliefs(beliefs))
    return 0


def cmd_write(dry_run: bool = False) -> int:
    if not PERSONA.exists():
        sys.stderr.write(f"missing Persona.md at {PERSONA}\n")
        return 1
    beliefs = gather_beliefs()
    new_section = render_top_beliefs(beliefs)
    old_text = PERSONA.read_text(encoding="utf-8")
    new_text = splice_section(old_text, new_section)
    if old_text == new_text:
        print("unchanged: Persona.md already in sync")
        return 0
    if dry_run:
        print("DRIFT: Persona.md would change")
        return 1
    PERSONA.write_text(new_text, encoding="utf-8")
    print(f"wrote: Persona.md (updated {len(beliefs)} beliefs)")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("cmd", choices=["preview", "write"], nargs="?", default="preview")
    parser.add_argument("--check", action="store_true", help="exit non-zero if Persona drifted")
    args = parser.parse_args()
    if args.check:
        sys.exit(cmd_write(dry_run=True))
    if args.cmd == "preview":
        sys.exit(cmd_preview())
    sys.exit(cmd_write())
