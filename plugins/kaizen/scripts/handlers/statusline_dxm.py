"""statusline_dxm — print one statusline segment for dxm live state.

Designed to render in <50ms (statusline budget). Reads dxm events for
the active session and emits ONE line: empty when no session/events,
else "dxm: Nev/Xs [Tool:K]" where N=count, X=lag-seconds, optional
top-tool breakdown when --show-top.

Wired into statusline.sh as one segment of the composition.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path


def _disabled() -> bool:
    return os.environ.get("KAIZEN_DXM_DISABLE") == "1"


def _dxm_dir() -> Path:
    env = os.environ.get("KAIZEN_DXM_DIR")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    return Path.home() / ".claude" / ".kaizen" / "dxm"


def _discover_session(cwd: Path) -> str | None:
    """Shared session discovery via _session_jsonl helper."""
    _SCRIPT_DIR = Path(__file__).resolve().parent
    sys.path.insert(0, str(_SCRIPT_DIR))
    # MIGRATION BRIDGE — _session_jsonl still at skills/workflow/scripts/
    sys.path.insert(0, str(_SCRIPT_DIR.parents[1] / "skills" / "workflow" / "scripts"))
    from _session_jsonl import discover_active_session_id
    return discover_active_session_id(cwd)


def _read_events(sid: str) -> list[dict]:
    path = _dxm_dir() / f"events-{sid}.jsonl"
    if not path.is_file():
        return []
    out: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return out


def _format_lag(seconds: float) -> str:
    """Compact lag format: 0.05s / 12s / 5m / 2h."""
    if seconds < 60:
        return f"{seconds:.1f}s" if seconds < 10 else f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds / 60)}m"
    return f"{int(seconds / 3600)}h"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="statusline_dxm",
        description="One statusline segment for dxm live state.",
    )
    p.add_argument("--back", type=float, default=None,
                    help="filter to events in last N seconds (default: all)")
    p.add_argument("--show-top", action="store_true",
                    help="append top tool:count breakdown")
    p.add_argument("--cwd", default=None,
                    help="override cwd for session discovery (test aid)")
    args = p.parse_args(argv)

    if _disabled():
        return 0  # empty stdout

    cwd = Path(args.cwd or ".").resolve()
    sid = _discover_session(cwd)
    if not sid:
        return 0

    events = _read_events(sid)
    if not events:
        return 0

    if args.back is not None:
        cutoff = time.time() - args.back
        events = [e for e in events
                   if isinstance(e.get("ts_unix"), (int, float))
                   and e["ts_unix"] >= cutoff]
        if not events:
            return 0

    # Lag = now - latest event ts
    latest = 0.0
    for e in events:
        ts = e.get("ts_unix")
        if isinstance(ts, (int, float)) and ts > latest:
            latest = ts
    lag = time.time() - latest if latest > 0 else 0.0

    segment = f"dxm: {len(events)}ev/{_format_lag(lag)}"

    if args.show_top:
        tools: Counter[str] = Counter()
        for e in events:
            tn = e.get("tool_name")
            if tn:
                tools[tn] += 1
        if tools:
            top, n = tools.most_common(1)[0]
            segment += f" {top}:{n}"

    print(segment)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
