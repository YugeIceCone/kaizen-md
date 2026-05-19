#!/usr/bin/env python3
"""kaizen session_start — SessionStart hook port of upstream session_start.js.

Loads the brain Persona + emits "REMEMBER BRAIN LOADED" banner with
truncated Evidence Log + optional passive-nudge instructions. Replaces
the upstream Node.js script with an all-stdlib Python equivalent so
the plugin no longer depends on `node` at runtime.

Bypass: REMEMBER_PROCESSING=1 (silent no-op — for nested invocations
during processing flows that mustn't trigger the SessionStart banner
again).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


_SCRIPT_DIR = Path(__file__).resolve().parent
_PLUGIN_ROOT = _SCRIPT_DIR.parent
_DEFAULTS_FILE = _PLUGIN_ROOT / "config.defaults.json"

# Max Evidence Log lines retained in the injected Persona — prevents
# the log from growing unbounded and blowing the SessionStart context
# budget. Mirrors the upstream MAX_EVIDENCE_LINES constant.
MAX_EVIDENCE_LINES = 10


PASSIVE_NUDGE_INSTRUCTION = """\
CAPTURE NUDGE (apply silently throughout this session):
If during this conversation the user reveals a stable preference, technical
decision they're committing to, or a recurring pattern worth remembering
(in any language — English, Romanian, mixed), at most ONCE per topic,
gently suggest at the end of your response, **showing the exact content
you'd save** so the user can verify before confirming:

> 💡 Want me to remember this?
> "<the verbatim or near-verbatim phrasing you'd capture>"

Format the quoted content faithfully. Trim it to one or two lines if the
original is long, but keep the technical specifics (paths, commands, names,
numbers) intact. Don't paraphrase away the precision.

Rules:
- Only nudge for content that is stable, opinionated, or factual — NOT for
  ongoing exploration, hypotheticals, or things the user is still figuring out.
- Never nudge twice for the same topic in one session.
- Skip the nudge entirely if the user's message already starts with a
  capture keyword (remember this, save this, brain dump, salvează, notează…).
- On a short affirmative response ("yes", "da", "ok", "save it", "go ahead",
  "sigur", "salveaza", etc.) immediately following your nudge, invoke the
  capture skill using the quoted content from the nudge as the input.
- If the user replies with edits ("yes but change X to Y", "save it as Z
  instead"), apply the edits and then capture the corrected version.
- On a negative or non-committal response ("no", "nu", "later", "skip",
  silence + new topic), drop the nudge silently — never re-prompt.
- Never auto-capture without explicit affirmative confirmation.
- Be brief. The nudge is two lines max (the question + the quoted content).
  Don't disrupt the flow of the answer itself."""


def brain_root() -> Path:
    """v1.38.0+ single env knob: KAIZEN_BRAIN_DIR > <KAIZEN_DIR>/brain
    (default ~/.claude/.kaizen/brain). Mirrors upstream config.getBrainRoot."""
    raw = os.environ.get("KAIZEN_BRAIN_DIR") or os.path.join(
        os.environ.get("KAIZEN_DIR") or os.path.expanduser("~/.claude/.kaizen"),
        "brain",
    )
    return Path(raw).expanduser().resolve()


def load_config() -> dict:
    """Load config.defaults.json. Falls back to hardcoded defaults if
    the file is missing or malformed (matches upstream behavior)."""
    try:
        return json.loads(_DEFAULTS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "session": {
                "brain_dump_keywords": [
                    "save this", "remember this", "brain dump",
                    "note to self", "capture this", "save to brain",
                    "write to brain", "add to brain",
                ],
                "load_persona": True,
                "passive_nudge": True,
            },
        }


_EVIDENCE_HEADER_RE = re.compile(r"^###?\s*Evidence\s*Log", re.IGNORECASE | re.MULTILINE)
_NEXT_SECTION_RE = re.compile(r"^##\s", re.MULTILINE)


def truncate_evidence_log(persona: str, max_lines: int = MAX_EVIDENCE_LINES) -> str:
    """Truncate the Evidence Log section to the last ``max_lines`` entries.

    Looks for ``## Evidence Log`` (or ``### Evidence Log``) header,
    keeps everything before + after, and trims the entries in between
    to the last N list items. Preserves the section header + the after
    section verbatim. Mirrors upstream session_start.js logic.
    """
    m = _EVIDENCE_HEADER_RE.search(persona)
    if not m:
        return persona
    header_end = m.end()
    after = persona[header_end:]
    next_sec = _NEXT_SECTION_RE.search(after)
    if next_sec:
        block, after_block = after[: next_sec.start()], after[next_sec.start():]
    else:
        block, after_block = after, ""
    entries = [
        line for line in block.split("\n")
        if line.lstrip().startswith(("-", "["))
    ]
    if len(entries) <= max_lines:
        return persona
    truncated = entries[-max_lines:]
    return (
        persona[:header_end]
        + "\n" + "\n".join(truncated) + "\n\n"
        + after_block
    )


def render_session_start(brain_dir: Path, persona: str, *,
                         passive_nudge_enabled: bool) -> str:
    """Build the stdout payload — banner + Persona + optional nudge."""
    nudge_block = (
        f"{PASSIVE_NUDGE_INSTRUCTION}\n\n" if passive_nudge_enabled else ""
    )
    return (
        f"REMEMBER BRAIN LOADED. Brain: {brain_dir}\n\n"
        f"PERSONA (apply throughout session):\n{persona}\n\n"
        + nudge_block
        + "Commands: /remember:process, /remember:status, "
          "'remember this: ...'\n"
    )


def main() -> int:
    if os.environ.get("REMEMBER_PROCESSING") == "1":
        return 0
    brain = brain_root()
    if not brain.is_dir():
        return 0
    persona_path = brain / "Persona.md"
    try:
        persona = persona_path.read_text(encoding="utf-8")
    except OSError:
        return 0
    if not persona.strip():
        return 0
    persona = truncate_evidence_log(persona, MAX_EVIDENCE_LINES)
    config = load_config()
    passive_nudge = config.get("session", {}).get("passive_nudge", True) is not False
    sys.stdout.write(render_session_start(
        brain, persona, passive_nudge_enabled=passive_nudge,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
