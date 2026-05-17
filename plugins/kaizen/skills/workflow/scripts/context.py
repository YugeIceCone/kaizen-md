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


def get_tokens_from_jsonl(cwd_path=None):
    """Read latest assistant turn's usage from active CC session JSONL.
    Returns total context tokens (input + cache_creation + cache_read +
    output) of the most-recent assistant turn, or None when unavailable.

    This is the AUTHORITATIVE source for context-window state — env
    vars are inconsistent across CC versions; the JSONL is reliable.
    """
    import sys as _sys
    from pathlib import Path as _Path
    _here = _Path(__file__).resolve().parent
    _sys.path.insert(0, str(_here))
    try:
        import _session_jsonl as _sj
    except ImportError:
        return None
    sid = _sj.discover_active_session_id(cwd_path)
    if not sid:
        return None
    slug = _sj.cwd_to_slug(_Path(cwd_path or ".").resolve())
    from pathlib import Path as _P
    jsonl = _P.home() / ".claude" / "projects" / slug / f"{sid}.jsonl"
    if not jsonl.is_file():
        return None
    last_usage = None
    try:
        with jsonl.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if o.get("type") == "assistant":
                    usage = (o.get("message") or {}).get("usage")
                    if isinstance(usage, dict):
                        last_usage = usage
    except OSError:
        return None
    if last_usage is None:
        return None
    return (
        int(last_usage.get("input_tokens") or 0)
        + int(last_usage.get("cache_creation_input_tokens") or 0)
        + int(last_usage.get("cache_read_input_tokens") or 0)
        + int(last_usage.get("output_tokens") or 0)
    )


def main():
    stdin_text = ""
    if not sys.stdin.isatty():
        try:
            stdin_text = sys.stdin.read()
        except (OSError, ValueError):
            pass

    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"

    # from-jsonl source: derive tokens from the active session JSONL
    # (the authoritative source — env vars are inconsistent)
    if cmd == "from-jsonl":
        tokens = get_tokens_from_jsonl()
        limit = get_limit()
        pct = (tokens * 100 // limit) if tokens is not None else None
        z = zone_of(pct)
        print(json.dumps({
            "tokens": tokens, "limit": limit, "pct": pct, "zone": z,
            "source": "jsonl",
        }, indent=2))
        return

    tokens = get_tokens(stdin_text)
    limit = get_limit()
    pct = (tokens * 100 // limit) if tokens is not None else None
    z = zone_of(pct)

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
