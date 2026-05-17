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


# Per-model context windows. New entries belong here. Heuristic below
# (`-1m` / `[1m]` substring) covers future 1M models without a code change.
_MODEL_LIMITS: dict[str, int] = {
    "claude-opus-4-7[1m]": 1_000_000,
    "claude-opus-4-7-1m":  1_000_000,
}


def limit_for_model(model_id: str | None) -> int:
    """Pure: map a model id to its context-window size in tokens.

    Direct lookup in _MODEL_LIMITS first; then a `-1m`/`[1m]` substring
    heuristic for forward-compat with future 1M-context model ids; else
    the 200k default."""
    if not model_id:
        return 200_000
    if model_id in _MODEL_LIMITS:
        return _MODEL_LIMITS[model_id]
    low = model_id.lower()
    if "[1m]" in low or "-1m" in low:
        return 1_000_000
    return 200_000


def _model_id_from_jsonl(cwd_path=None) -> str:
    """Return the model id of the latest assistant turn, or "" on miss.
    Walks the active CC session JSONL — same source as token-count reads."""
    import sys as _sys
    from pathlib import Path as _Path
    _here = _Path(__file__).resolve().parent
    _sys.path.insert(0, str(_here))
    try:
        import _session_jsonl as _sj
    except ImportError:
        return ""
    sid = _sj.discover_active_session_id(cwd_path)
    if not sid:
        return ""
    slug = _sj.cwd_to_slug(_Path(cwd_path or ".").resolve())
    jsonl = _Path.home() / ".claude" / "projects" / slug / f"{sid}.jsonl"
    if not jsonl.is_file():
        return ""
    last_model = ""
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
                    m = (o.get("message") or {}).get("model")
                    if isinstance(m, str) and m:
                        last_model = m
    except OSError:
        return ""
    return last_model


def get_model_id() -> str:
    """Active model id. Resolution order:
    KAIZEN_MODEL_ID env > CLAUDE_MODEL_ID env > latest assistant turn in JSONL."""
    for k in ("KAIZEN_MODEL_ID", "CLAUDE_MODEL_ID"):
        v = os.environ.get(k, "").strip()
        if v:
            return v
    return _model_id_from_jsonl()


def get_limit() -> int:
    """Active context-window size. Resolution order:

    1. KAIZEN_CONTEXT_LIMIT env (explicit override)
    2. Model-derived from KAIZEN_MODEL_ID / CLAUDE_MODEL_ID / live JSONL
       (catches `[1m]` / `-1m` markers when present)
    3. Defensive auto-detect: if the active session has ever observed
       >200k tokens in a single turn, the active model MUST be 1M
       context — the standard 200k window couldn't have held it. This
       catches the case where CC's JSONL strips the `[1m]` suffix
       (saves `claude-opus-4-7` not `claude-opus-4-7[1m]`).
    4. 200k default.
    """
    v = os.environ.get("KAIZEN_CONTEXT_LIMIT", "").strip()
    if v:
        try:
            return int(v)
        except ValueError:
            pass  # fall through to model-derived

    # Model-id-based mapping (covers [1m]/-1m markers when present)
    derived = limit_for_model(get_model_id())
    if derived > 200_000:
        return derived

    # Defensive: if observed usage > 200k, infer 1M context
    try:
        summary = get_usage_summary()
        peak = summary.get("peak_tokens")
        if isinstance(peak, int) and peak > 200_000:
            return 1_000_000
    except Exception:
        pass

    return derived


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


def _usage_total(usage: dict) -> int:
    return (
        int(usage.get("input_tokens") or 0)
        + int(usage.get("cache_creation_input_tokens") or 0)
        + int(usage.get("cache_read_input_tokens") or 0)
        + int(usage.get("output_tokens") or 0)
    )


def get_usage_summary(cwd_path=None) -> dict:
    """BK-015 — peak-aware reader for the active CC session JSONL.

    Walks every assistant turn (not just the last one) and tracks the
    maximum total tokens. Counts `isCompactSummary:true` markers to
    detect compaction events; flags whether the peak occurred before
    the last marker (i.e. pre-compact peak that the post-compact view
    can no longer see).

    Returns dict with stable keys (None when JSONL unavailable):
        {
          "current_tokens":   int | None,  # last assistant turn
          "peak_tokens":      int | None,  # max across all turns
          "peak_pre_compact": bool,        # peak occurred before last
                                            #  isCompactSummary marker
          "compact_count":    int,         # number of compact markers
        }
    """
    import sys as _sys
    from pathlib import Path as _Path
    _here = _Path(__file__).resolve().parent
    _sys.path.insert(0, str(_here))
    try:
        import _session_jsonl as _sj
    except ImportError:
        return {"current_tokens": None, "peak_tokens": None,
                 "peak_pre_compact": False, "compact_count": 0}
    sid = _sj.discover_active_session_id(cwd_path)
    empty = {"current_tokens": None, "peak_tokens": None,
              "peak_pre_compact": False, "compact_count": 0}
    if not sid:
        return empty
    slug = _sj.cwd_to_slug(_Path(cwd_path or ".").resolve())
    jsonl = _Path.home() / ".claude" / "projects" / slug / f"{sid}.jsonl"
    if not jsonl.is_file():
        return empty

    peak = 0
    peak_line = -1
    last_total = None
    compact_count = 0
    last_compact_line = -1
    try:
        with jsonl.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if o.get("isCompactSummary") is True:
                    compact_count += 1
                    last_compact_line = line_no
                    continue
                if o.get("type") == "assistant":
                    usage = (o.get("message") or {}).get("usage")
                    if isinstance(usage, dict):
                        total = _usage_total(usage)
                        last_total = total
                        if total > peak:
                            peak = total
                            peak_line = line_no
    except OSError:
        return empty

    if last_total is None:
        return empty

    peak_pre_compact = (
        last_compact_line >= 0 and peak_line < last_compact_line
    )
    return {
        "current_tokens":   last_total,
        "peak_tokens":      peak,
        "peak_pre_compact": peak_pre_compact,
        "compact_count":    compact_count,
    }


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

    elif cmd == "line":
        # Pre-formatted statusline segment — replaces 5 python3 spawns
        # in statusline.sh with 1. Empty stdout means "no segment".
        if tokens is None:
            return
        icon = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(z, "⚪")
        tokens_k = tokens // 1000
        limit_k = limit // 1000
        print(f"{icon} {tokens_k}k/{limit_k}k ({pct}%)")

    elif cmd in ("-h", "--help"):
        print(__doc__)

    else:
        sys.exit(f"unknown subcommand: {cmd}\ntry: show|json|zone|pct|should-warn")


if __name__ == "__main__":
    main()
