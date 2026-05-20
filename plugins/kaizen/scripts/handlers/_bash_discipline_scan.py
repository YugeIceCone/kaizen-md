#!/usr/bin/env python3
"""kaizen — Bash invocation discipline scanner.

Reads a bash command (from --command, --stdin, or argv) and reports
advisory warnings when it violates the rules declared in
skills/workflow/domain/git-discipline.yaml::bash_invocation_discipline.

Stdlib-only. Pure function — no I/O side effects.

## Usage

    # From a PreToolUse hook
    cat event.json | python3 _bash_discipline_scan.py --from-event

    # From a one-shot test
    python3 _bash_discipline_scan.py --command "cd /tmp && rm -rf x && mkdir x"

## Output

JSON to stdout. Empty `{}` if no warnings. Otherwise:

    {
      "warnings": [
        {"rule": "rm_in_isolation", "severity": "hard", "message": "..."},
        {"rule": "split_compound_when_destructive", "severity": "hard", "message": "..."}
      ]
    }

## Why advisory, not blocking

The 6 discipline rules are about CC permission-prompt minimization +
audit-frame isolation. They are not safety gates (existing gate handles
genuinely-destructive patterns with `ask`). Warning lets the agent
self-correct without breaking flow.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

# Pattern definitions — kept in-sync with
# skills/workflow/domain/git-discipline.yaml::bash_invocation_discipline.rules
# IDs match the yaml.rules[].id field.

_RM_RE = re.compile(r"\brm\s+(-[rRfF]+\s+|--recursive\s+|--force\s+)*[^\s|;&]+")
_DESTRUCTIVE_RE = re.compile(
    r"\b(rm\s+-[rRfF]+|"
    r"git\s+rm\b|"
    r"git\s+push.*--force|"
    r"git\s+reset\s+--hard|"
    r"git\s+clean\s+-[fdx]+|"
    r"dd\s+of=|"
    r"mkfs)"
)
_ENV_PREFIX_RE = re.compile(r"^\s*[A-Z_][A-Z0-9_]*=[^\s]+\s+\S")
_AND_CHAIN_RE = re.compile(r"&&")

def scan(command: str) -> list[dict[str, str]]:
    """Return a list of warning objects for advisory hooks to emit.

    Each entry: {"rule": id, "severity": "hard"|"soft", "message": str}.
    Empty list = clean.
    """
    warnings: list[dict[str, str]] = []
    if not command:
        return warnings

    has_rm = bool(_RM_RE.search(command))
    has_destructive = bool(_DESTRUCTIVE_RE.search(command))
    and_chains = len(_AND_CHAIN_RE.findall(command))
    has_newlines = "\n" in command.strip()

    # Rule 1: rm_in_isolation (hard) — rm combined with other ops
    if has_rm and (and_chains > 0 or has_newlines):
        warnings.append({
            "rule": "rm_in_isolation",
            "severity": "hard",
            "message": (
                "`rm` combined with other ops in one Bash call. CC's "
                "destructive-op heuristic reprompts even when Bash(*) is "
                "allowed. Split into separate Bash tool calls: setup, then "
                "test, then cleanup. See "
                "git-discipline.yaml::bash_invocation_discipline.rm_in_isolation."
            ),
        })

    # Rule 2: env-prefix (soft) — VAR=value cmd inline
    if _ENV_PREFIX_RE.match(command):
        warnings.append({
            "rule": "export_over_envprefix",
            "severity": "soft",
            "message": (
                "Inline `VAR=value cmd` env-prefix detected. CC's matcher "
                "may parse the env-var as the binary name and miss Bash(*) "
                "matching. Prefer `export VAR=value; cmd`."
            ),
        })

    # Rule 3: split_compound_when_destructive (hard) — &&-chain + destructive
    if and_chains > 0 and has_destructive:
        warnings.append({
            "rule": "split_compound_when_destructive",
            "severity": "hard",
            "message": (
                f"Compound &&-chain ({and_chains} &&) containing a "
                "destructive op. One risky token reprompts the whole. "
                "Split into discrete Bash tool calls."
            ),
        })

    # Rule 6: scope_tool_calls_narrowly (soft) — too many ops per call
    if and_chains >= 5:
        warnings.append({
            "rule": "scope_tool_calls_narrowly",
            "severity": "soft",
            "message": (
                f"This Bash call has {and_chains} &&-chained ops. "
                "Hard to debug mid-chain failures; permission decision "
                "applies to the whole. Split into ≤3 logical ops per call."
            ),
        })

    return warnings

def _read_event_stdin() -> str:
    """Read the bash command from a PreToolUse event JSON on stdin."""
    try:
        e = json.load(sys.stdin)
        return e.get("tool_input", {}).get("command", "") or ""
    except (json.JSONDecodeError, OSError):
        return ""

def main() -> int:
    parser = argparse.ArgumentParser(description="kaizen bash-discipline scanner")
    parser.add_argument("--command", "-c", help="bash command to scan")
    parser.add_argument("--from-event", action="store_true",
                        help="read PreToolUse event JSON from stdin and extract tool_input.command")
    args = parser.parse_args()

    if args.from_event:
        command = _read_event_stdin()
    elif args.command:
        command = args.command
    else:
        # No input given — read raw from stdin
        try:
            command = sys.stdin.read()
        except OSError:
            command = ""

    warnings = scan(command)
    json.dump({"warnings": warnings} if warnings else {}, sys.stdout)
    sys.stdout.write("\n")
    return 0

if __name__ == "__main__":
    sys.exit(main())
