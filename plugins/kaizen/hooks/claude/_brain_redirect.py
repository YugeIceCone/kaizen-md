#!/usr/bin/env python3
"""PreToolUse hook: nudge Read on memory files → kaizen-brain show.

Per user 2026-05-19 — "automate it don't rely on skills." Agents
shouldn't have to read SKILL.md to discover that block-ops exist;
this hook intercepts Read on Markdown under brain/ + project-memory/
and emits `additionalContext` listing the addressable heading-paths
plus the precise `kaizen-brain show` command.

Never blocks (no permissionDecision); purely advisory.
Bypass: `KAIZEN_BRAIN_REDIRECT_DISABLE=1`.

Design contract:
  PROGRAMMABLE  — should_redirect / build_hint pure
  REPRODUCIBLE  — same (tool, input, file content) → same hint
  CONSISTENT    — always emits valid hook-decision JSON
  DETERMINISTIC — no clock, no random
  REUSABLE      — sibling pattern: pretooluse-bash-gate / -roundtrip-detect
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_BRAIN_SUFFIX_PARTS = (".kaizen/brain/", "/projects/", "/memory/")


def should_redirect(tool_name: str, tool_input: dict) -> bool:
    """True iff this Read tool call should get a redirect nudge."""
    if os.environ.get("KAIZEN_BRAIN_REDIRECT_DISABLE") == "1":
        return False
    if tool_name != "Read":
        return False
    fp = tool_input.get("file_path", "")
    if not isinstance(fp, str) or not fp.endswith(".md"):
        return False
    # Matches if path is under brain/ OR <project>/memory/
    if ".kaizen/brain/" in fp:
        return True
    if "/memory/" in fp and "/projects/" in fp:
        return True
    return False


def build_hint(path: Path) -> str:
    """Render the additionalContext text — block list + suggested CLI."""
    try:
        scripts_dir = Path(__file__).resolve().parent.parent.parent / "skills" / "workflow" / "scripts"
        sys.path.insert(0, str(scripts_dir))
        import _brain_blocks as _bb  # type: ignore
        text = path.read_text(encoding="utf-8", errors="replace")
        blocks = _bb.parse_blocks(text)
    except (OSError, ImportError):
        blocks = []
    lines = [
        f"💡 Memory file detected: {path}",
        "Prefer `kaizen-brain` block ops over `Read` — 8× fewer tokens, "
        "atomic edits, no fragile `old_string` matching.",
    ]
    if blocks and any(b["path"] for b in blocks):
        lines.append("")
        lines.append("Addressable blocks:")
        for b in blocks:
            if not b["path"]:
                continue
            lines.append(f"  - {b['path']}  (lines {b['start']}-{b['end']})")
        lines.append("")
        lines.append(f"Extract one:  kaizen-brain show --file {path} --block \"<path>\"")
        lines.append(f"Edit one:     kaizen-brain edit --file {path} --block \"<path>\" --replace BODY")
        lines.append(f"Append one:   kaizen-brain edit --file {path} --block \"<path>\" --append LINE")
    else:
        lines.append("")
        lines.append(f"Discover blocks:  kaizen-brain blocks --file {path}")
    return "\n".join(lines)


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        print("{}")
        return 0
    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input", {}) or {}
    if not should_redirect(tool_name, tool_input):
        print("{}")
        return 0
    fp = Path(tool_input.get("file_path", ""))
    hint = build_hint(fp)
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": hint,
        }
    }
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
