#!/usr/bin/env python3
"""kaizen pocketflow demo — Node+Flow analysis of the backlog.

Demonstrates the Node+Flow discipline (from shodan's CLAUDE.md
"Engine + Modes + Nodes" section) applied to a real artifact: this
plugin's backlog.json. The Flow:

    ReadBacklogNode → AnalyzeNode → ReportNode

Each step is a single-responsibility Node with prep/exec/post phases.
Shared store carries data between nodes — no module-global state.

Install once:
    pip install --user pocketflow

Run:
    python3 flow_demo.py [path/to/backlog.json]

Default path: resolved via .kaizen.toml's backlog_path, or
.workflow/backlog.json under the current git repo root.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

try:
    from pocketflow import Node, Flow
except ImportError:
    print(
        "kaizen flow_demo: pocketflow not installed.\n"
        "  Install: pip install --user pocketflow\n"
        "  Then re-run.",
        file=sys.stderr,
    )
    sys.exit(1)


# ─── Helpers ──────────────────────────────────────────────────────────


def resolve_backlog_path() -> Path:
    """Resolve backlog.json via .kaizen.toml's backlog_path, or fallback."""
    try:
        root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except subprocess.CalledProcessError:
        sys.exit("flow_demo: not in a git repo")

    cfg = Path(root) / ".kaizen.toml"
    backlog_md = ".workflow/backlog.md"
    if cfg.exists():
        for line in cfg.read_text().splitlines():
            if line.strip().startswith("backlog_path"):
                v = line.split("=", 1)[1].strip().strip('"').strip("'")
                backlog_md = v
                break

    return Path(root) / backlog_md.replace(".md", ".json")


# ─── Nodes (single-responsibility, prep / exec / post phases) ─────────


class ReadBacklogNode(Node):
    """Load backlog.json from disk. prep: resolve path; exec: parse JSON."""

    def prep(self, shared):
        return shared["backlog_path"]

    def exec(self, path: Path):
        if not path.exists():
            raise FileNotFoundError(f"backlog.json not found at {path}")
        return json.loads(path.read_text())

    def post(self, shared, prep_res, exec_res):
        shared["data"] = exec_res
        return "default"


class AnalyzeNode(Node):
    """Count items per section + tag; identify probe/verify completeness."""

    def prep(self, shared):
        return shared["data"]

    def exec(self, data: dict):
        items = data.get("items", [])
        decisions = data.get("decisions", [])
        sections = Counter(it["section"] for it in items)
        tags = Counter(t for it in items for t in it.get("tags", []))
        missing_probe = sum(1 for it in items if not it.get("probe"))
        missing_verify = sum(1 for it in items if not it.get("verify"))
        return {
            "total": len(items),
            "sections": dict(sections),
            "tags_top5": tags.most_common(5),
            "missing_probe": missing_probe,
            "missing_verify": missing_verify,
            "decisions": len(decisions),
        }

    def post(self, shared, prep_res, exec_res):
        shared["analysis"] = exec_res
        return "default"


class ReportNode(Node):
    """Format the analysis as human-readable text."""

    def prep(self, shared):
        return shared["analysis"]

    def exec(self, analysis: dict):
        s = analysis["sections"]
        lines = [
            "Backlog analysis (pocketflow Flow demo)",
            "=" * 40,
            f"Total items:       {analysis['total']}",
            f"  in_flight:       {s.get('in_flight', 0)}",
            f"  next_up:         {s.get('next_up', 0)}",
            f"  done:            {s.get('done', 0)}",
            f"  parked:          {s.get('parked', 0)}",
            f"Decisions:         {analysis['decisions']}",
            "",
            "Top 5 tags:",
        ]
        if analysis["tags_top5"]:
            for tag, count in analysis["tags_top5"]:
                lines.append(f"  {tag:<20} {count}")
        else:
            lines.append("  (no tags yet)")
        lines += [
            "",
            "Discipline gaps:",
            f"  items missing probe field:   {analysis['missing_probe']}",
            f"  items missing verify field:  {analysis['missing_verify']}",
        ]
        return "\n".join(lines)

    def post(self, shared, prep_res, exec_res):
        shared["report"] = exec_res
        return "default"


# ─── Flow assembly + entry point ──────────────────────────────────────


def build_flow() -> Flow:
    """Wire the 3 nodes in sequence using PocketFlow's `>>` operator."""
    read = ReadBacklogNode()
    analyze = AnalyzeNode()
    report = ReportNode()
    read >> analyze >> report
    return Flow(start=read)


def main():
    if len(sys.argv) > 1:
        backlog_path = Path(sys.argv[1])
    else:
        backlog_path = resolve_backlog_path()

    shared = {"backlog_path": backlog_path}
    flow = build_flow()
    flow.run(shared)
    print(shared["report"])


if __name__ == "__main__":
    main()
