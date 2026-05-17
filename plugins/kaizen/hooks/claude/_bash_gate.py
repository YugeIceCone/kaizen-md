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

# Lazy-loaded — etu_scan lives in another skill, importing fails when
# the skill is absent (consumer repos that don't ship kaizen). Falls back
# to no-op in that case so the gate never blocks on its own absence.
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
_ETU_SCAN = _PLUGIN_ROOT / "skills" / "efficient-tool-use" / "application" / "etu_scan.py"


def _load_etu_scan_text():
    """Return etu_scan.scan_text if available, else a no-op stub.

    Bypass: KAIZEN_ETU_GATE_DISABLE=1 short-circuits to the stub
    (satisfies the hook-bypass-knob iron-law).
    """
    import os
    if os.environ.get("KAIZEN_ETU_GATE_DISABLE") == "1":
        return None
    if not _ETU_SCAN.is_file():
        return None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "kaizen_etu_for_bash_gate", _ETU_SCAN
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["kaizen_etu_for_bash_gate"] = mod
        spec.loader.exec_module(mod)
        return mod.scan_text
    except (ImportError, AttributeError, OSError):
        return None


# Long-form path → short-form `kaizen <sub>` suggester.
# Matches `bash plugins/kaizen/.../bin/kaizen-FOO` OR
# `python3 plugins/kaizen/skills/workflow/scripts/FOO.py` and infers the
# subcommand name. The `kaizen` dispatcher is on $PATH after
# /kaizen:setup install (typically).
_LONG_FORM_BIN = re.compile(
    r"(?:^|[\s|;&])(?:bash\s+)?[^\s]*plugins/kaizen/bin/kaizen-([\w-]+)\b"
)
_LONG_FORM_SCRIPT = re.compile(
    r"(?:^|[\s|;&])(?:python3?|uv run --script)\s+[^\s]*plugins/kaizen/skills/workflow/scripts/([\w-]+)\.(?:py|sh)\b"
)


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

# Heredoc body: `<<['"]?WORD['"]?` … newline … a line that is just WORD.
# The body is opaque DATA (not re-interpreted as commands) — strip it so a
# commit message that merely *mentions* `git push --force` doesn't trip the
# gate. Non-greedy + DOTALL stops at the first matching close delimiter.
_HEREDOC = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?.*?\n[ \t]*\1\b", re.DOTALL)
_DQUOTE = re.compile(r'"[^"]*"')
_SQUOTE = re.compile(r"'[^']*'")


def _strip_noncommand(command: str) -> str:
    """Blank out heredoc bodies and quoted-string literals.

    The gate must inspect the *commands the shell will run*, not text the
    shell treats as data. A `git commit -m "$(cat <<EOF … EOF)"` carries a
    whole commit message — destructive-op tokens quoted inside it are prose,
    not commands. Stripping that DATA leaves real unquoted command tokens
    (`rm -rf /foo`, `git push --force`) intact, so the patterns still catch
    genuine destructive commands while shedding the mid-message false hits.
    """
    s = _HEREDOC.sub(" ", command)
    # Double-quotes first — `$(... )` substitutions and most commit `-m`
    # bodies are double-quoted; doing them first avoids a stray `'` inside
    # a double-quoted string anchoring a spurious single-quote match.
    s = _DQUOTE.sub(" ", s)
    s = _SQUOTE.sub(" ", s)
    return s


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


def etu_decision(command: str) -> tuple[str, str] | None:
    """Run etu_scan.scan_text against the command. Return (verb, reason)
    if any `error`-severity anti-pattern fires (eval $user_input, find /,
    rm -rf $unset, etc.) so Claude is asked to confirm before running it.

    Lazy-loaded — if etu_scan isn't available (consumer repo, gate
    disabled via KAIZEN_ETU_GATE_DISABLE=1), returns None silently.
    """
    scan_text = _load_etu_scan_text()
    if scan_text is None:
        return None
    try:
        findings = scan_text(command, source="<bash-tool-call>")
    except Exception:
        return None
    errors = [f for f in findings if getattr(f, "severity", "") == "error"]
    if not errors:
        return None
    # Format: cite the first 3 patterns + count of any extra
    first = errors[:3]
    lines = [
        f"kaizen etu gate: {len(errors)} error finding(s) in command — "
        "potential safety / correctness issue. Confirm intent or revise:",
    ]
    for f in first:
        lines.append(f"  [{f.pattern_id}] {f.why_bad}")
        lines.append(f"    fix: {f.replacement}")
    if len(errors) > 3:
        lines.append(f"  + {len(errors) - 3} more")
    lines.append(
        "Bypass: prepend `KAIZEN_ETU_GATE_DISABLE=1 ` to the command, "
        "OR add `# noqa: etu` to the line (file-edit case)."
    )
    return ("ask", "\n".join(lines))


def long_form_nudge(command: str) -> str | None:
    """Detect long-form invocations of kaizen scripts and suggest the
    `kaizen <sub>` short form. Advisory-only — never blocks."""
    matches = []
    for m in _LONG_FORM_BIN.finditer(command):
        sub = m.group(1)
        matches.append((m.group(0).strip(), f"kaizen {sub}"))
    for m in _LONG_FORM_SCRIPT.finditer(command):
        sub = m.group(1)
        # `_mcp` suffix → MCP server module (no `kaizen <sub>` mapping)
        if sub.endswith("_mcp") or sub.startswith("_"):
            continue
        short = sub.replace("_", "-")
        matches.append((m.group(0).strip(), f"kaizen {short}"))
    if not matches:
        return None
    lines = [
        "kaizen-cli nudge: long-form path detected — `kaizen <sub>` is "
        "shorter, on $PATH, and emits trace events:"
    ]
    for found, short in matches[:3]:
        lines.append(f"  found: {found}")
        lines.append(f"  use:   {short}")
    if len(matches) > 3:
        lines.append(f"  + {len(matches) - 3} more")
    return "\n".join(lines)


def decide(command: str) -> dict:
    """Pure decision function — command in, hook-output dict out.

    Heredoc bodies and quoted-string literals are stripped before pattern
    matching so the gate reasons about commands, not data the shell carries
    (e.g. a commit message that mentions a destructive command).

    Decision ladder, in order:
      1. destructive op (`git rm`, `rm -rf`, `git push --force`, etc.)
         → permissionDecision: ask
      2. etu `error`-severity anti-pattern (eval $user_input, find /, etc.)
         → permissionDecision: ask
      3. bash-discipline advisory + long-form-path nudge (concatenated)
         → systemMessage
      4. clean → {}
    """
    if not command:
        return {}
    scan_target = _strip_noncommand(command)

    destructive = destructive_decision(scan_target)
    if destructive:
        verb, reason = destructive
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": verb,
                "permissionDecisionReason": reason,
            }
        }

    # etu sees the RAW command — `eval "$user_input"` is the pattern
    # we want to catch, but _strip_noncommand would erase its argument.
    # `eval` itself is the danger, so we scan unstripped.
    etu = etu_decision(command)
    if etu:
        verb, reason = etu
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": verb,
                "permissionDecisionReason": reason,
            }
        }

    # Combine bash-discipline advisory + long-form nudge into one
    # systemMessage (or emit either alone).
    parts = []
    advisory = advisory_message(scan_target)
    if advisory:
        parts.append(advisory)
    nudge = long_form_nudge(scan_target)
    if nudge:
        parts.append(nudge)
    if parts:
        return {"systemMessage": "\n\n".join(parts)}

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
