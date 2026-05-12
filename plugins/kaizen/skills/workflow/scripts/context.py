#!/usr/bin/env python3
"""kaizen context — report on the Claude Code context window.

Resolves the current token count from (in priority):

  1. `CLAUDE_CONTEXT_TOKENS` env var (if the harness exports it).
  2. `CLAUDE_USAGE_TOTAL_TOKENS` env var (alternate name some plugins use).
  3. JSON read from stdin (Claude Code statusline schema): looks for
     `total_tokens` or `usage.total_tokens`.
  4. (Fallback) None — we don't know.

Limit: `KAIZEN_CONTEXT_LIMIT` env, defaults to 200_000 (Opus 4.7 cap).

Zones (pct of limit):

  - green:  0-59%
  - yellow: 60-79% — start thinking about /compact
  - red:    80%+   — actively warn; risk losing state at compaction
  - unknown — token count not available

Subcommands:

    show          — human-readable line (default if no subcmd)
    json          — full machine-readable record
    zone          — one of: green | yellow | red | unknown
    pct           — integer percentage (blank line if unknown)
    should-warn   — exits 0 if yellow/red, 1 if green/unknown
                    (use in shell guards: `context.py should-warn && echo "compact!"`)
"""

from __future__ import annotations

import json
import os
import sys


def get_limit() -> int:
    v = os.environ.get("KAIZEN_CONTEXT_LIMIT", "200000")
    try:
        return int(v)
    except ValueError:
        return 200_000


def get_tokens(stdin_text: str = "") -> int | None:
    for k in ("CLAUDE_CONTEXT_TOKENS", "CLAUDE_USAGE_TOTAL_TOKENS"):
        v = os.environ.get(k, "").strip()
        if v.isdigit():
            return int(v)
    if stdin_text:
        try:
            d = json.loads(stdin_text)
            t = d.get("total_tokens")
            if t is None:
                t = d.get("usage", {}).get("total_tokens")
            if isinstance(t, int):
                return t
        except (json.JSONDecodeError, AttributeError):
            pass
    return None


def zone_of(pct: int | None) -> str:
    if pct is None:
        return "unknown"
    if pct < 60:
        return "green"
    if pct < 80:
        return "yellow"
    return "red"


def main():
    stdin_text = ""
    if not sys.stdin.isatty():
        try:
            stdin_text = sys.stdin.read()
        except (OSError, ValueError):
            pass

    tokens = get_tokens(stdin_text)
    limit = get_limit()
    pct = (tokens * 100 // limit) if tokens is not None else None
    z = zone_of(pct)

    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"

    if cmd == "show":
        if tokens is None:
            print("context: unknown (no CLAUDE_CONTEXT_TOKENS env, no stdin JSON)")
        else:
            print(f"context: {tokens:,}/{limit:,} tokens ({pct}%, {z})")

    elif cmd == "json":
        print(json.dumps({
            "tokens": tokens,
            "limit": limit,
            "pct": pct,
            "zone": z,
        }, indent=2))

    elif cmd == "zone":
        print(z)

    elif cmd == "pct":
        print(pct if pct is not None else "")

    elif cmd == "should-warn":
        sys.exit(0 if z in ("yellow", "red") else 1)

    elif cmd in ("-h", "--help"):
        print(__doc__)

    else:
        sys.exit(f"unknown subcommand: {cmd}\ntry: show|json|zone|pct|should-warn")


if __name__ == "__main__":
    main()
