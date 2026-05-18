"""kaizen-chatlog — pure-function core: trigger matcher + slicer.

Splits the slicing primitives out of the CLI (chatlog.py) so they can be
unit-tested in-process. Drift-resilient: no module-level state.

## Design contract (per pref-prcdr-contract-declared)

- **Programmable** — match_event / extract_slice / slice_transcript are pure
- **Reproducible** — same (events, rules) → same output (deterministic)
- **Consistent** — every rule returns a list (empty for no matches)
- **Deterministic** — no wall-clock; no env reads; no randomness
- **Reusable** — works for any JSONL transcript shape with `type` + `message`
"""
from __future__ import annotations

import re
from typing import Any, Iterable


def _user_text(event: dict) -> str:
    """Return concatenated user-message text. '' for non-user events."""
    if event.get("type") != "user":
        return ""
    msg = event.get("message")
    if not isinstance(msg, dict):
        return ""
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                parts.append(c.get("text", ""))
            elif isinstance(c, str):
                parts.append(c)
        return " ".join(parts)
    return ""


def _assistant_tool_names(event: dict) -> list[str]:
    """Return tool_use names for assistant events. [] for non-assistant."""
    if event.get("type") != "assistant":
        return []
    msg = event.get("message")
    if not isinstance(msg, dict):
        return []
    content = msg.get("content")
    if not isinstance(content, list):
        return []
    names = []
    for c in content:
        if isinstance(c, dict) and c.get("type") == "tool_use":
            name = c.get("name")
            if name:
                names.append(name)
    return names


def match_event(event: dict, rule: dict) -> bool:
    """Return True iff event matches the rule's trigger."""
    trigger = rule.get("trigger") or {}
    kind = trigger.get("type")

    if kind == "event_type":
        want = trigger.get("event_type")
        return event.get("type") == want

    if kind == "user_keyword":
        pattern = trigger.get("pattern")
        if not pattern:
            return False
        text = _user_text(event)
        if not text:
            return False
        try:
            return re.search(pattern, text, re.IGNORECASE) is not None
        except re.error:
            return False

    if kind == "assistant_tool_use":
        want = trigger.get("tool_name")
        if not want:
            return False
        return want in _assistant_tool_names(event)

    # Unknown trigger type — no match (caller can lint separately)
    return False


def extract_slice(events: list, idx: int, before: int, after: int) -> list:
    """Return events[idx-before .. idx+after] (inclusive, clamped to bounds)."""
    lo = max(0, idx - max(0, before))
    hi = min(len(events), idx + max(0, after) + 1)
    return events[lo:hi]


def slice_transcript(events: Iterable[dict], rules: list[dict]) -> dict[str, list]:
    """For each rule, return list of slices (each slice = list of events).

    Walks events once. For each match against a rule, captures the
    capture-window. Returns dict[rule_id → list[slice]] with empty list
    for rules that didn't match anything.
    """
    events = list(events)
    out: dict[str, list] = {rule.get("id") or f"rule-{i}": []
                              for i, rule in enumerate(rules)}
    for idx, event in enumerate(events):
        for rule in rules:
            if match_event(event, rule):
                rid = rule.get("id") or f"rule-{rules.index(rule)}"
                cap = rule.get("capture") or {}
                sl = extract_slice(events, idx,
                                    int(cap.get("before", 0)),
                                    int(cap.get("after", 0)))
                out[rid].append(sl)
    return out


__all__ = ["match_event", "extract_slice", "slice_transcript"]
