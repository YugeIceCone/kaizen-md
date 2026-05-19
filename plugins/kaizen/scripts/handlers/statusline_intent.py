"""statusline_intent — print one statusline segment when an intent matches.

Parallel to statusline_dxm: reads dxm events for the active session,
runs intent scan (event_pattern triggers), emits one line when an
intent fires. Empty when no match / no session / disabled.

Designed to render in <50ms.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


def _disabled() -> bool:
    return os.environ.get("KAIZEN_INTENT_DISABLE") == "1"


def _dxm_dir() -> Path:
    env = os.environ.get("KAIZEN_DXM_DIR")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    return Path.home() / ".claude" / ".kaizen" / "dxm"


def _discover_session(cwd: Path) -> str | None:
    """Shared session discovery via _session_jsonl helper."""
    _SCRIPT_DIR = Path(__file__).resolve().parent
    sys.path.insert(0, str(_SCRIPT_DIR))
    # MIGRATION BRIDGE — kaizen modules still at skills/workflow/scripts/
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "workflow" / "scripts"))
    from _session_jsonl import discover_active_session_id
    return discover_active_session_id(cwd)


def _read_recent_events(sid: str, back_seconds: float) -> list[dict]:
    path = _dxm_dir() / f"events-{sid}.jsonl"
    if not path.is_file():
        return []
    cutoff = time.time() - back_seconds
    out: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = e.get("ts_unix")
                if isinstance(ts, (int, float)) and ts >= cutoff:
                    out.append(e)
    except OSError:
        return []
    return out


def _run_intent_scan(events: list[dict]) -> dict | None:
    """Load intents + return best event_pattern match (or None)."""
    # Lazy import of intent.py
    SCRIPT_DIR = Path(__file__).resolve().parent
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        import intent  # type: ignore
    except ImportError:
        return None
    try:
        intents = intent._load_intents()
    except Exception:
        return None
    best = None
    best_conf = -1.0
    for i in intents:
        if intent._intent_matches(i, "", events):
            conf = intent._intent_confidence(i)
            if conf > best_conf:
                best = i
                best_conf = conf
    if best is None:
        return None
    return {
        "id":          best.get("id"),
        "confidence":  best_conf,
        "action":      best.get("action") or {},
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="statusline_intent",
        description="One statusline segment for intent matches.",
    )
    p.add_argument("--back", type=float, default=120.0,
                    help="event window in seconds (default 120)")
    p.add_argument("--cwd", default=None)
    args = p.parse_args(argv)

    if _disabled():
        return 0

    cwd = Path(args.cwd or ".").resolve()
    sid = _discover_session(cwd)
    if not sid:
        return 0

    events = _read_recent_events(sid, args.back)
    if not events:
        return 0

    match = _run_intent_scan(events)
    if not match:
        return 0

    # Compact segment: "intent: <id> (conf)"
    print(f"intent: {match['id']} ({match['confidence']:.2f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
