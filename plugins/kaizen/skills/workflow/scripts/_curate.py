"""Token-efficient curator for findings/results lists.

Shared module — kaizen's MCP servers all return potentially-thousands-of-rows
result sets (ruff findings, ty findings, trace events, search hits). Letting
the raw list flow back through Claude's context burns tokens for items the
model will never look at past row ~10.

The curator compresses to a fixed shape that's typically <2 KB:

    {
        "total": <int>,
        "by_severity": {severity: count, ...},
        "by_rule_top5": {rule: count, ...},
        "by_file_top5": {file: count, ...},
        "findings_top_n": [first N rows],
        "truncated": <bool>,
    }

Generic enough to work for lint/typecheck findings AND any list-of-dicts
where the rows have `severity`, `code`/`rule`, `file` keys. Rows missing
any of those gain synthetic `unknown` / `uncoded` keys so aggregation still
works.

## Usage

    from _curate import curate, SEVERITY_RANK

    raw = [{"severity": "error", "code": "E501", "file": "a.py", "message": "..."},
           {"severity": "warning", "code": "W292", "file": "b.py", "message": "..."}]
    out = curate(raw, top_n=10, severity_min="warning")
    # → {"total": 2, "by_severity": {"error":1, "warning":1}, ...}

## Why a shared module

`lint_mcp.py` defined this inline first. As other MCPs (trace_mcp,
knowledge_mcp, scrape_mcp) grow their own result-pagination needs, they
should use the same compression shape so Claude sees a consistent API
across tools. DRY against the SEVERITY_RANK constant in particular —
divergent rankings between MCPs would be a subtle bug source.
"""
from __future__ import annotations

SEVERITY_RANK = {
    "error": 4,
    "warning": 3,
    "info": 2,
    "note": 1,
    "hint": 1,
    "": 0,
}


def curate(
    findings: list[dict],
    top_n: int = 10,
    severity_min: str = "",
    rule_key: str = "code",
) -> dict:
    """Compress a flat findings list into a token-efficient summary.

    findings: each item should have at least {severity, code/<rule_key>, file, message}.
              Missing keys map to "unknown" / "uncoded" — never raises.
    top_n: how many full findings to surface (default 10).
    severity_min: filter out anything below this severity rank ("" = no filter).
    rule_key: which key holds the rule identifier (default "code"; pass "rule"
              if your data uses that field name).

    Returns the shape documented in the module docstring.
    """
    if not findings:
        return {
            "total": 0,
            "by_severity": {},
            "by_rule_top5": {},
            "by_file_top5": {},
            "findings_top_n": [],
            "truncated": False,
        }

    min_rank = SEVERITY_RANK.get(severity_min, 0)
    if min_rank > 0:
        findings = [
            f for f in findings
            if SEVERITY_RANK.get(f.get("severity", ""), 0) >= min_rank
        ]

    by_sev: dict[str, int] = {}
    by_rule: dict[str, int] = {}
    by_file: dict[str, int] = {}
    for f in findings:
        s = f.get("severity") or "unknown"
        c = f.get(rule_key) or "uncoded"
        fp = f.get("file") or "unknown"
        by_sev[s] = by_sev.get(s, 0) + 1
        by_rule[c] = by_rule.get(c, 0) + 1
        by_file[fp] = by_file.get(fp, 0) + 1

    def _top(d: dict, n: int) -> dict:
        return dict(sorted(d.items(), key=lambda kv: -kv[1])[:n])

    return {
        "total": len(findings),
        "by_severity": by_sev,
        "by_rule_top5": _top(by_rule, 5),
        "by_file_top5": _top(by_file, 5),
        "findings_top_n": findings[:top_n],
        "truncated": len(findings) > top_n,
    }


def max_severity(by_sev: dict[str, int]) -> str:
    """Return the highest-ranked severity present in a by_severity map.

    Returns "" if the map is empty."""
    if not by_sev:
        return ""
    return max(by_sev.keys(), key=lambda s: SEVERITY_RANK.get(s, 0))
