"""kaizen stop_self_improving_review — periodic memory-curation nudge.

Fires every N stops (default 5, override via KAIZEN_SELF_IMPROVING_EVERY_N).
Reads dxm event count for the session, computes (stop_count % N == 0),
emits a systemMessage suggesting /kaizen:self-improving review when due.

Cheap — no actual memory scan happens here; the systemMessage just
prompts the agent to invoke the review subcommand if/when relevant.
Keeps the hot path silent + lets the agent decide based on context.

Bypass: KAIZEN_SELF_IMPROVING_REVIEW_DISABLE=1.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path

import _session_jsonl as _sj  # noqa: E402

def _dxm_dir() -> Path:
    env = os.environ.get("KAIZEN_DXM_DIR")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    return Path.home() / ".claude" / ".kaizen" / "dxm"

def _every_n() -> int:
    raw = os.environ.get("KAIZEN_SELF_IMPROVING_EVERY_N", "5")
    try:
        n = int(raw)
        return n if n >= 1 else 5
    except ValueError:
        return 5

def _stop_count(session_id: str) -> int:
    """Count of Stop events in dxm for this session."""
    path = _dxm_dir() / f"events-{session_id}.jsonl"
    if not path.is_file():
        return 0
    count = 0
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                # Cheap substring — dxm events are flat one-line JSON
                if '"evt_type":"Stop"' in line:
                    count += 1
    except OSError:
        return 0
    return count

def check(session_id: str | None = None) -> dict:
    if os.environ.get("KAIZEN_SELF_IMPROVING_REVIEW_DISABLE") == "1":
        return {}
    sid = session_id or _sj.discover_active_session_id()
    if not sid:
        return {}
    n = _every_n()
    stops = _stop_count(sid)
    # Fire on stops that are positive multiples of N (1st fire = N-th stop).
    if stops < n or stops % n != 0:
        return {}
    msg = (
        f"🧠 kaizen-self-improving: {stops} Stop events this session "
        f"(every {n}-th nudge). Consider running /kaizen:self-improving "
        f"review to surface auto-memory promotion candidates.\n"
        f"Adjust cadence via KAIZEN_SELF_IMPROVING_EVERY_N=<int>, mute "
        f"with KAIZEN_SELF_IMPROVING_REVIEW_DISABLE=1."
    )
    return {"systemMessage": msg}

def _cmd_check(args) -> int:
    print(json.dumps(check(session_id=args.session) or {}))
    return 0

def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-self-improving-review",
        description="Stop-hook periodic memory-curation nudge.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("check")
    sc.add_argument("--session", default=None)
    sc.set_defaults(func=_cmd_check)
    args = p.parse_args(argv)
    return args.func(args)

if __name__ == "__main__":
    raise SystemExit(main())
