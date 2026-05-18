#!/usr/bin/env python3
"""kaizen-brainstorm — typed contract for brainstorming JSONL output.

Public surface (more added in P4-P7):

    _compute_idea_signals(draft: dict) -> dict
        Pure fn — maps an idea-draft dict to the signals dict the
        brainstorm-rubric.yaml walks. Mirrors handoff exemplar.

The full CLI (`score`), override loop, and threshold gate land in
subsequent phases of BK-012.
"""
from __future__ import annotations

import re

_TRIGGER_RE = re.compile(r"\bwhen\b|\btrigger\b|→|\bif\b.*\bthen\b", re.I)


def _compute_idea_signals(draft: dict) -> dict:
    """Map an idea-draft to the signals dict walked by brainstorm-rubric.yaml.

    Pure: no I/O, no env, no clock. Same input → same output. Does
    not mutate `draft`. Mirrors brainstorm-rubric.yaml `signal:` keys
    one-for-one (named-once discipline from decision-rubric Iron Laws).
    """
    text = draft.get("idea", "") or ""
    return {
        "length_words":    len(text.split()),
        "has_tool_dep":    bool(draft.get("tools")),
        "trigger_present": bool(_TRIGGER_RE.search(text)),
        "effort_bucket":   draft.get("effort_estimate", "M") or "M",
        "yagni_flag":      bool(draft.get("yagni", False)),
        "radical_flag":    bool(draft.get("radical", False)),
        "llm_confidence":  float(draft.get("confidence", 0.5) or 0.5),
        "novelty_score":   float(draft.get("novelty_score", 0.5) or 0.5),
    }
