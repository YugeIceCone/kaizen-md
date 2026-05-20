"""kaizen spec-driven — EARS notation linter + confidence scorer + gate.

Pure functions over a requirements.md / spec text. No I/O beyond
read+parse. Stdlib-only.

## EARS patterns (Easy Approach to Requirements Syntax)

  Ubiquitous   : THE SYSTEM SHALL <behavior>
  Event-driven : WHEN <trigger>, THE SYSTEM SHALL <behavior>
  State-driven : WHILE <state>, THE SYSTEM SHALL <behavior>
  Unwanted     : IF <condition>, THEN THE SYSTEM SHALL <response>
  Optional     : WHERE <feature>, THE SYSTEM SHALL <behavior>

A requirement line starts with `- **REQ-<n>**` or `- **NFR-<n>**`
followed by the EARS-compliant clause.

## API

  lint_requirements(text) -> {ok, violations, total, by_pattern}
  score_requirements(text) -> {score, signals, advisory}
  gate_check(plan_path, item_id) -> {ok, item_status, hash_ok, reason}
"""
from __future__ import annotations

import re
from typing import Any

# ─── EARS patterns ──────────────────────────────────────────────────────

# Compiled once at module load. Each pattern matches the EARS clause
# after the bold REQ-/NFR- marker has been stripped.

_PATTERNS = [
    ("ubiquitous",   re.compile(r"^\s*THE SYSTEM SHALL\b", re.IGNORECASE)),
    ("event_driven", re.compile(r"^\s*WHEN\b.+\b,\s*THE SYSTEM SHALL\b",
                                re.IGNORECASE)),
    ("state_driven", re.compile(r"^\s*WHILE\b.+\b,\s*THE SYSTEM SHALL\b",
                                re.IGNORECASE)),
    ("unwanted",     re.compile(r"^\s*IF\b.+\bTHEN\b.+\bTHE SYSTEM SHALL\b",
                                re.IGNORECASE | re.DOTALL)),
    ("optional",     re.compile(r"^\s*WHERE\b.+\b,\s*THE SYSTEM SHALL\b",
                                re.IGNORECASE)),
]

# Detects a requirement line: `- **REQ-001**` or `- **NFR-001**`.
_REQ_LINE = re.compile(
    r"^\s*-\s+\*\*(?P<id>(REQ|NFR)-\d+)\*\*\s+(?P<clause>.+?)\s*\.?\s*$",
    re.IGNORECASE,
)


def lint_requirements(text: str) -> dict[str, Any]:
    """Walk requirements.md lines; return EARS compliance report.

    Returns:
      {
        "ok": bool,
        "violations": [{line_num, id, clause, reason}, ...],
        "total": int,
        "by_pattern": {ubiquitous: N, event_driven: N, ...},
      }
    """
    violations: list[dict] = []
    by_pattern: dict[str, int] = {p[0]: 0 for p in _PATTERNS}
    total = 0
    for lineno, line in enumerate(text.splitlines(), start=1):
        m = _REQ_LINE.match(line)
        if not m:
            continue
        total += 1
        clause = m.group("clause")
        req_id = m.group("id")
        # Strip leading <PLACEHOLDER> markers (template-style)
        if "<" in clause and ">" in clause:
            violations.append({
                "line_num": lineno,
                "id": req_id,
                "clause": clause[:80],
                "reason": "unfilled placeholder (<...>)",
            })
            continue
        matched = False
        for name, rx in _PATTERNS:
            if rx.search(clause):
                by_pattern[name] += 1
                matched = True
                break
        if not matched:
            violations.append({
                "line_num": lineno,
                "id": req_id,
                "clause": clause[:80],
                "reason": "does not match any EARS pattern",
            })
    return {
        "ok": not violations,
        "violations": violations,
        "total": total,
        "by_pattern": by_pattern,
    }


# ─── Confidence-score automation ────────────────────────────────────────

# Ambiguity markers — words/phrases that erode confidence
_AMBIGUOUS = re.compile(
    r"\b(some|several|fast|slow|appropriate|reasonable|sufficient|"
    r"good|bad|nice|acceptable|adequate|user-friendly|"
    r"as needed|when possible|if applicable|etc\.?|tbd|tbc|fixme|"
    r"todo)\b",
    re.IGNORECASE,
)

# Number+unit pattern — concrete thresholds raise confidence
_CONCRETE_NUM = re.compile(
    r"\b\d+(\.\d+)?\s?(ms|s|min|hour|day|kb|mb|gb|"
    r"%|p50|p95|p99|req|rps|qps|gb/s|mb/s)\b",
    re.IGNORECASE,
)


def score_requirements(text: str) -> dict[str, Any]:
    """Heuristic confidence score for a requirements.md draft.

    Signals:
      ears_ratio       fraction of REQ-lines that pass EARS lint (0-1)
      placeholder_pct  fraction of REQ-lines with unfilled <...> (0-1)
      ambiguous_count  count of ambiguity markers in body
      concrete_count   count of numeric+unit thresholds in body
      total_reqs       int

    Score (0-100):
      Base 50.
      + (ears_ratio * 30)              EARS compliance
      - (placeholder_pct * 30)         unfilled templates
      - min(15, ambiguous_count * 3)   ambiguity penalty
      + min(15, concrete_count * 3)    concreteness bonus
      clamp [0, 100]
    """
    lint = lint_requirements(text)
    total = lint["total"]
    if total == 0:
        return {
            "score": 0,
            "advisory": "no requirements found",
            "signals": {"total_reqs": 0},
        }
    placeholder_count = sum(
        1 for v in lint["violations"]
        if v["reason"].startswith("unfilled placeholder"))
    other_violation_count = len(lint["violations"]) - placeholder_count
    ears_ratio = (total - len(lint["violations"])) / total
    placeholder_pct = placeholder_count / total

    ambiguous_count = len(_AMBIGUOUS.findall(text))
    concrete_count = len(_CONCRETE_NUM.findall(text))

    score = 50.0
    score += ears_ratio * 30
    score -= placeholder_pct * 30
    score -= min(15, ambiguous_count * 3)
    score += min(15, concrete_count * 3)
    score = max(0.0, min(100.0, score))

    if score >= 85:
        advisory = "high — branch_high: straight to tasks"
    elif score >= 66:
        advisory = "medium — branch_medium: PoC sub-section before tasks"
    else:
        advisory = "low — branch_low: re-analyze/re-design first"

    return {
        "score": round(score, 1),
        "advisory": advisory,
        "signals": {
            "total_reqs": total,
            "ears_ratio": round(ears_ratio, 3),
            "placeholder_pct": round(placeholder_pct, 3),
            "ambiguous_count": ambiguous_count,
            "concrete_count": concrete_count,
            "ears_violations": other_violation_count,
        },
    }


__all__ = ["lint_requirements", "score_requirements"]
