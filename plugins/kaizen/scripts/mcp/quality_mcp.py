#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp>=3.0"]
# ///
"""kaizen MCP server — exposes 5 quality axes as discrete MCP tools.

The gatekeeper aggregator sums these axes into one verdict; this
server exposes each as a separate query so agents can drill into the
dimension they care about without re-running the whole gate.

Tools:
  frontmatter_gaps()       → {count, findings[]}
  coverage_gaps()          → {count, findings[]}
  name_quality_gaps()      → {count, findings[]}
  schema_coverage_gaps()   → {count, findings[]}
  slash_collisions(min=4)  → {count, findings[]}

Each returns a dict with `count` + `findings` (list). Empty list = clean.
Wraps the sibling axis-CLI helpers directly (no subprocess).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastmcp import FastMCP

_HERE = Path(os.path.realpath(__file__)).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
# MIGRATION BRIDGE — quality helpers (frontmatter, coverage, etc.) still at skills/workflow/scripts/
_LEGACY = _HERE.parents[1] / "skills" / "workflow" / "scripts"
if str(_LEGACY) not in sys.path:
    sys.path.insert(0, str(_LEGACY))

import frontmatter as _fm          # noqa: E402
import coverage as _cov             # noqa: E402
import name_quality as _nq          # noqa: E402
import schema_coverage as _sc       # noqa: E402
import slash_collision as _sl       # noqa: E402


mcp = FastMCP("quality")


def frontmatter_gaps() -> dict:
    """SKILL.md frontmatter conformance: name matches dir + ≥3 trigger phrases.

    Returns:
      dict with `count` (int) + `findings` (list of audit-row dicts —
      one per skill with at least one gap). Name-mismatch findings are
      ERROR-severity (commit-blocking); weak-routing is WARN-severity.
    """
    reports = [r for r in _fm.all_audits() if r.get("gaps")]
    return {"count": len(reports), "findings": reports}


def coverage_gaps() -> dict:
    """Code-to-test 1:1 coverage: every workflow/scripts/<x>.py has a
    matching tests/test_<x>*.py.

    Returns:
      dict with `count` (int — uncovered scripts) + `findings` (list of
      uncovered script names).
    """
    root = _cov._default_root()
    data = _cov._compute(root)
    uncovered = data.get("uncovered", [])
    return {
        "count":    len(uncovered),
        "findings": [{"script": s} for s in uncovered],
    }


def name_quality_gaps() -> dict:
    """Filename ↔ docstring-intent match across workflow/scripts/.

    Returns:
      dict with `count` (int — files verdicted bad/weak) + `findings`
      (list of score dicts with `path` + `verdict` + `score`).
    """
    reports = _nq.scan_scripts()
    flagged = [r for r in reports if r.get("verdict") in ("bad", "weak")]
    return {"count": len(flagged), "findings": flagged}


def schema_coverage_gaps() -> dict:
    """Feature-shape conformance — does each domain/-having feature
    match one of the 4 canonical shapes (lens-manifest / decision-rubric
    / plain-config / rule-catalog)?

    Returns:
      dict with `count` (int — non-conformant features) + `findings`
      (list of feature-report dicts).
    """
    reports = _sc.all_reports()
    flagged = [r for r in reports if not r.get("conformant", True)]
    return {"count": len(flagged), "findings": flagged}


def slash_collisions(min_prefix_len: int = 4) -> dict:
    """Tab-completion-ambiguous slash pairs (shared prefix ≥ min_prefix_len).

    Args:
      min_prefix_len: minimum shared prefix length to flag (default 4).
        Set to 3 to catch shorter collisions (e.g. mode/models pre-fold).

    Returns:
      dict with `count` (int) + `findings` (list of
      {prefix, members[]} groups).
    """
    target = _sl._plugin_commands_dir()
    coll = _sl.scan_commands_dir(target, min_prefix_len=min_prefix_len)
    return {"count": len(coll), "findings": coll}


# Register all 5 axes.
mcp.tool()(frontmatter_gaps)
mcp.tool()(coverage_gaps)
mcp.tool()(name_quality_gaps)
mcp.tool()(schema_coverage_gaps)
mcp.tool()(slash_collisions)


if __name__ == "__main__":
    mcp.run()
