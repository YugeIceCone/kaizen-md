#!/usr/bin/env python3
"""kaizen — PreToolUse Bash gate (unified single-process entry).

Collapses what was up to 6 python3 spawns in pretooluse-bash-gate.sh into
ONE (H3 speed fix): read the event JSON from stdin, extract the command,
run the destructive-op match, run the bash-discipline scan, and emit the
final hook-decision JSON.

Emits to stdout exactly one of:
  - permissionDecision (ask)  — for a destructive op (git rm / push --force
                                / reset --hard / clean -fd / rm -rf)
  - systemMessage             — for a bash-invocation-discipline advisory
  - {}                        — clean / no opinion

Stdlib-only. Reuses scan() from _bash_discipline_scan.py (DRY) — the
discipline rules have a single source of truth.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bash_discipline_scan import scan  # noqa: E402


# Destructive-op patterns — ordered most-specific first. Mirrors the grep
# ladder that lived inline in pretooluse-bash-gate.sh pre-collapse.
_GIT_RM = re.compile(r"(^|[^a-zA-Z])git\s+rm\s")
# Matches `--force` and `--force-with-lease` (the \b before `-with-lease`
# also catches the bare form); `--forced` etc. are excluded by \b.
_GIT_PUSH_FORCE = re.compile(r"git\s+push\b.*--force\b")
_GIT_RESET_HARD = re.compile(r"git\s+reset\s+--hard")
_GIT_CLEAN = re.compile(r"git\s+clean\s+-[fdx]+")
_RM_RF = re.compile(r"rm\s+-[rR][fF]?\s")
_RM_RF_SAFE = re.compile(
    r"rm\s+-[rR][fF]?\s+(/tmp|/var/tmp|~/?\.cache|\$TMPDIR|\$HOME/\.cache)"
)

_NO_DELETIONS_BELIEF = Path.home() / ".claude" / "brain" / "Notes" / "pref-no-deletions.md"


def destructive_decision(command: str) -> tuple[str, str] | None:
    """Return (permissionDecision, reason) for a destructive command, else None.

    `git rm` only fires when the no-deletions belief file exists — the gate
    is the model-runs-command-time mirror of the git-commit-time pre-deletion
    check, and both key off the same belief scan.
    """
    if _GIT_RM.search(command):
        if _NO_DELETIONS_BELIEF.is_file():
            return ("ask",
                    f"`git rm` triggers the no-deletions belief at "
                    f"{_NO_DELETIONS_BELIEF} — confirm explicit user "
                    f"authorization before proceeding.")
        return None
    if _GIT_PUSH_FORCE.search(command):
        return ("ask",
                "`git push --force` overwrites remote history. Confirm "
                "target branch + that no collaborator pushes will be lost.")
    if _GIT_RESET_HARD.search(command):
        return ("ask",
                "`git reset --hard` discards uncommitted changes. Confirm "
                "no local work will be lost (run `git status` first).")
    if _GIT_CLEAN.search(command):
        return ("ask",
                "`git clean -fd` deletes untracked files. Confirm none are "
                "in-progress work (e.g. new test files).")
    if _RM_RF.search(command) and not _RM_RF_SAFE.search(command):
        return ("ask",
                "`rm -rf` outside /tmp / cache dirs — confirm path is not a "
                "source-of-truth (config, brain, plans/, .workflow/).")
    return None


def advisory_message(command: str) -> str | None:
    """Return a formatted bash-discipline advisory string, else None."""
    warnings = scan(command)
    if not warnings:
        return None
    n = len(warnings)
    lines = [f"kaizen bash-discipline advisory ({n} warning{'' if n == 1 else 's'}):"]
    for w in warnings:
        lines.append("  [{}] {}: {}".format(
            w.get("severity", "soft").upper(),
            w.get("rule", "?"),
            w.get("message", "")))
    return "\n".join(lines)


def decide(command: str) -> dict:
    """Pure decision function — command in, hook-output dict out."""
    if not command:
        return {}
    destructive = destructive_decision(command)
    if destructive:
        verb, reason = destructive
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": verb,
                "permissionDecisionReason": reason,
            }
        }
    advisory = advisory_message(command)
    if advisory:
        return {"systemMessage": advisory}
    return {}


def _read_command() -> str:
    """Extract tool_input.command from a PreToolUse event JSON on stdin."""
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return ""
    if not isinstance(event, dict):
        return ""
    tool_input = event.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return ""
    return tool_input.get("command", "") or ""


def main() -> int:
    print(json.dumps(decide(_read_command())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
