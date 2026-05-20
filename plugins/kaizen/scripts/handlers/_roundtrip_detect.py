"""Roundtrip-pattern detector — pure core for posttool-roundtrip-detect.sh.

Watches for the Read+Edit (or Read+Write) anti-pattern: same path opened
by Read then Edit/Write within N seconds. When detected, nudges the
agent to capture the friction via `kaizen-learn append --category
roundtrips ...`.

Design contract (per user 2026-05-18):
  - PROGRAMMABLE — pure functions; any caller can use process_event /
                   run_hook without spawning a subprocess.
  - REPRODUCIBLE — same (event, state, now, window) always yields the
                   same (new_state, nudge). Proven by
                   TestPureFunctionCore.test_idempotent_replay_*.
  - CONSISTENT   — matches kaizen-progress/kaizen-learn/kaizen-io
                   shape (env-overridable sink, append-only state,
                   never crashes the host).
  - DETERMINISTIC — no randomness; no wall-clock peek (`now` is param).
  - REUSABLE     — process_event accepts any (tool_name, file_path)
                   event shape; the Read→Edit pairing is configurable
                   via PAIRS. Adding "search → grep" or other pairs is
                   a registry edit, not a code rewrite.

Iron-laws (host-safety):
  - never raises; all paths return tuples
  - state file pruned on every call (entries older than window dropped)
  - bypass env: KAIZEN_LEARNING_DETECT_DISABLE=1 → no-op
  - exit 0 always (the bash wrapper guarantees this)
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Reusable registry: (trigger_tool, follower_tool) pairs that constitute
# a roundtrip when seen on the SAME file_path within the window.
# Adding more pairs (e.g. "Grep" → "Read" if the agent greps then reads
# the same file individually) is a one-line registry change.
PAIRS: dict[str, set[str]] = {
    "Read": {"Edit", "Write"},
}

def _parse_ts(ts: str) -> datetime | None:
    """Parse ISO-8601 timestamp; tolerate trailing Z. Returns None on garbage."""
    if not isinstance(ts, str) or not ts:
        return None
    try:
        # Python 3.11+ handles Z directly; older needs replace.
        normalized = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
        return datetime.fromisoformat(normalized).astimezone(UTC)
    except (ValueError, TypeError):
        return None

def _delta_seconds(later: datetime, earlier: datetime) -> float:
    return (later - earlier).total_seconds()

def _file_path(event: dict) -> str | None:
    """Extract file_path from event. None when not applicable."""
    if not isinstance(event, dict):
        return None
    tool_input = event.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return None
    path = tool_input.get("file_path")
    if isinstance(path, str) and path:
        return path
    return None

def _prune(state: dict, now: datetime, window_seconds: int) -> dict:
    """Drop entries older than `window_seconds` — keeps state bounded."""
    out: dict[str, dict] = {}
    for path, entry in state.items():
        ts = _parse_ts(entry.get("ts", ""))
        if ts is None:
            continue
        if _delta_seconds(now, ts) < window_seconds:
            out[path] = entry
    return out

def _render_nudge(*, trigger_tool: str, follower_tool: str,
                    path: str, gap_seconds: float) -> str:
    """One-line nudge text — surfaced to the agent as additionalContext."""
    return (
        f"[kaizen-learn detect] roundtrips: observed `{trigger_tool}` then "
        f"`{follower_tool}` on `{path}` within {int(gap_seconds)}s. "
        f"If you replaced N tool calls with 1 atomic CLI here, capture "
        f"the win via:\n"
        f"  kaizen-learn append --category roundtrips \\\n"
        f"    --problem \"<one-line>\" --solution \"<cli-or-pattern>\" \\\n"
        f"    --pattern \"<reusable rule>\" --savings-estimate \"<e.g. 2 calls -> 1>\" \\\n"
        f"    --reference \"{path}\""
    )

def process_event(event: dict, state: dict, *,
                    window_seconds: int = 30) -> tuple[dict, str | None]:
    """Pure core. Returns (new_state, nudge_text_or_None).

    No I/O. No wall-clock peek (uses event's `ts` field as the reference
    time). Same inputs always produce identical outputs.
    """
    new_state = dict(state)
    tool = (event or {}).get("tool_name", "") if isinstance(event, dict) else ""
    path = _file_path(event)
    now = _parse_ts((event or {}).get("ts", "")) if isinstance(event, dict) else None
    if now is None or not tool or not path:
        return new_state, None

    # Prune first so the window check below operates on fresh state only.
    new_state = _prune(new_state, now, window_seconds)

    # Did we see a TRIGGER tool earlier on the same path?
    # Check if the current tool is a FOLLOWER for some prior trigger.
    nudge: str | None = None
    prior = new_state.get(path)
    if prior is not None:
        prior_tool = prior.get("tool")
        prior_ts = _parse_ts(prior.get("ts", ""))
        if (prior_tool in PAIRS
                and tool in PAIRS[prior_tool]
                and prior_ts is not None
                and _delta_seconds(now, prior_ts) < window_seconds):
            nudge = _render_nudge(
                trigger_tool=prior_tool, follower_tool=tool,
                path=path, gap_seconds=_delta_seconds(now, prior_ts),
            )

    # Record current event (overwrites any prior on same path; we only
    # care about the LAST observation per path within the window).
    new_state[path] = {"tool": tool, "ts": event.get("ts")}
    return new_state, nudge

def _atomic_write_json(path: Path, data: dict) -> None:
    """tempfile + os.replace — partial writes can't corrupt state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp.", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

def _load_state(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

def run_hook(stdin_text: str, *, state_path: Path,
              window_seconds: int = 30, now: str | None = None
              ) -> tuple[dict, dict]:
    """Subprocess-style entry. Returns (stdout_envelope, new_state).

    Honors KAIZEN_LEARNING_DETECT_DISABLE=1 → no-op (empty envelope,
    state file untouched).
    """
    if os.environ.get("KAIZEN_LEARNING_DETECT_DISABLE") == "1":
        return {}, {}
    try:
        event = json.loads(stdin_text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}, {}
    if not isinstance(event, dict):
        return {}, {}
    # Inject `ts` if not present in the event (deterministic in tests via
    # the `now` parameter; production lets the event's own ts win).
    if "ts" not in event and now:
        event["ts"] = now

    state = _load_state(Path(state_path))
    new_state, nudge = process_event(event, state, window_seconds=window_seconds)

    try:
        _atomic_write_json(Path(state_path), new_state)
    except OSError:
        # Hook iron-law: never block the host. State write failure → keep going.
        pass

    if nudge:
        return {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": nudge,
            }
        }, new_state
    return {}, new_state

__all__ = ["process_event", "run_hook", "PAIRS"]
