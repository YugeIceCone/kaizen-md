"""kaizen metrics — rollup + never-used catalog over the trace log.

Reads ``~/.claude/.kaizen/trace/events.jsonl`` (the canonical trace
output) and computes:

- **Per-session rollup**: tool counts / skill loads / mcp invocations
  for one session_id (or the latest).
- **Lifetime rollup**: all-time counts; identifies hot vs cold features.
- **Never-used catalog**: which kaizen-original skills, MCP tools, and
  bin wrappers have zero invocations across the entire trace.
- **Top-N**: most-used skills / tools / MCP servers, descending.

## Subcommands

::

   kaizen-metrics session [--sid SID] [--json]
       Rollup for one session (default: most recent active sid)
   kaizen-metrics lifetime [--since DUR] [--json]
       Rollup over all of trace.jsonl (or --since '7d' / '30d' / ISO)
   kaizen-metrics never-used [--kind skill|tool|mcp|bin] [--json]
       What's available but never invoked
   kaizen-metrics top [--kind skill|tool|mcp] [--n 10] [--json]
       Most-used artifacts of each kind
   kaizen-metrics path
       Print the trace log path

Exit 0 always (informational). Non-zero only on argument errors.

## Why this exists

Until v1.34's M1 universal-trace hook, only Bash tool calls left a
trace footprint. With M1 in place, every Skill / Edit / Write / MCP
invocation lands in the same jsonl. This module is the rollup
surface — without it, the trace is a flat append-only log that's
hard to interrogate.

The never-used catalog is the critical signal for self-correction:
"which feature have you NEVER used" answers the user's question
about mistakes/skips. Skills that should be loaded but aren't, MCP
tools shipped but never called, bin wrappers that hit zero use —
all flagged here.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional


# ─── Paths ────────────────────────────────────────────────────────────


def trace_log_path() -> Path:
    """Resolve the trace log path.

    Priority: KAIZEN_TRACE_DIR env > ~/.claude/.kaizen/trace/."""
    env = os.environ.get("KAIZEN_TRACE_DIR", "")
    if env:
        return Path(os.path.expandvars(env)).expanduser().resolve() / "events.jsonl"
    return Path("~/.claude/.kaizen/trace/events.jsonl").expanduser().resolve()


def plugin_root() -> Path:
    """Walk up from this script to find the plugin root."""
    here = Path(__file__).resolve().parent  # skills/workflow/scripts
    # plugins/kaizen
    return here.parent.parent.parent


# ─── Event reader ────────────────────────────────────────────────────


def iter_events(
    since: Optional[dt.datetime] = None,
    sid: Optional[str] = None,
) -> Iterator[dict]:
    """Stream events from the trace jsonl, oldest first.

    ``since`` filters to events ts >= cutoff. ``sid`` filters to one
    session. Both are optional. Malformed JSON lines are skipped
    silently."""
    path = trace_log_path()
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            if sid is not None and rec.get("sid") != sid:
                continue
            if since is not None:
                ts_str = rec.get("ts", "")
                ts = _parse_ts(ts_str)
                if ts is None or ts < since:
                    continue
            yield rec


_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _parse_ts(s: str) -> Optional[dt.datetime]:
    """Parse the trace's ISO timestamp. Tolerates the trailing 'Z'."""
    if not s or not _TS_RE.match(s):
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return dt.datetime.fromisoformat(s)
    except ValueError:
        return None


# ─── Duration parser ─────────────────────────────────────────────────


_DURATION_RE = re.compile(r"^(\d+)([smhdw])$")


def parse_duration(s: str) -> Optional[dt.datetime]:
    """Convert a duration string ('7d', '30m', '1h', '2w') to a cutoff
    datetime in UTC. ISO timestamps are also accepted."""
    if not s:
        return None
    m = _DURATION_RE.match(s.strip())
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        seconds = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]
        now = dt.datetime.now(dt.timezone.utc)
        return now - dt.timedelta(seconds=n * seconds)
    return _parse_ts(s)


# ─── Rollup logic ────────────────────────────────────────────────────


@dataclass
class Rollup:
    total_events: int = 0
    by_evt: collections.Counter = field(default_factory=collections.Counter)
    by_tool: collections.Counter = field(default_factory=collections.Counter)
    by_skill: collections.Counter = field(default_factory=collections.Counter)
    by_mcp: collections.Counter = field(default_factory=collections.Counter)
    sessions: set = field(default_factory=set)
    earliest_ts: Optional[str] = None
    latest_ts: Optional[str] = None
    errors: int = 0

    def add(self, rec: dict) -> None:
        self.total_events += 1
        evt = rec.get("evt", "")
        tool = rec.get("tool", "")
        sid = rec.get("sid", "")
        ts = rec.get("ts", "")
        if sid:
            self.sessions.add(sid)
        if ts:
            if self.earliest_ts is None or ts < self.earliest_ts:
                self.earliest_ts = ts
            if self.latest_ts is None or ts > self.latest_ts:
                self.latest_ts = ts
        if evt:
            self.by_evt[evt] += 1
        # Tool tracking — only count PreToolUse-* events to avoid
        # double-counting (Pre + Post = one invocation).
        if tool and evt.startswith("PreToolUse-"):
            self.by_tool[tool] += 1
            # Skill-specific roll-up via data.ident
            if tool == "Skill":
                ident = (rec.get("data") or {}).get("ident", "")
                if ident:
                    self.by_skill[ident] += 1
            elif tool.startswith("mcp__"):
                self.by_mcp[tool] += 1
        # Error counter — PostToolUse with result=err
        if evt.startswith("PostToolUse-"):
            result = (rec.get("data") or {}).get("result", "")
            if result == "err":
                self.errors += 1

    def to_dict(self) -> dict:
        return {
            "total_events": self.total_events,
            "earliest_ts": self.earliest_ts,
            "latest_ts": self.latest_ts,
            "sessions": len(self.sessions),
            "errors": self.errors,
            "by_evt": dict(self.by_evt.most_common(50)),
            "by_tool": dict(self.by_tool.most_common(50)),
            "by_skill": dict(self.by_skill.most_common(50)),
            "by_mcp": dict(self.by_mcp.most_common(50)),
        }


def rollup_events(
    since: Optional[dt.datetime] = None,
    sid: Optional[str] = None,
) -> Rollup:
    r = Rollup()
    for rec in iter_events(since=since, sid=sid):
        r.add(rec)
    return r


def latest_session_id() -> Optional[str]:
    """Return the SessionStart with the most recent ts, or the most
    recent sid seen anywhere if no SessionStart was captured."""
    last_start_ts = ""
    last_start_sid = None
    last_any_ts = ""
    last_any_sid = None
    for rec in iter_events():
        sid = rec.get("sid", "")
        ts = rec.get("ts", "")
        if not sid:
            continue
        if rec.get("evt") == "SessionStart":
            if ts > last_start_ts:
                last_start_ts = ts
                last_start_sid = sid
        if ts > last_any_ts:
            last_any_ts = ts
            last_any_sid = sid
    return last_start_sid or last_any_sid


# ─── Available-artifact discovery (for never-used) ───────────────────


# Vendored skills don't count as kaizen-original — exclude from the
# never-used report. Same list as the plugin-development validator.
VENDORED_SKILLS = {
    "kiss", "solid", "dry", "yagni", "karpathy", "boy-scout-rule",
    "convention-over-configuration", "law-of-demeter",
    "separation-of-concerns", "brainstorming", "executing-plans",
    "writing-plans", "using-superpowers", "subagent-driven-development",
    "test-driven-development", "verification-before-completion",
    "dispatching-parallel-agents", "finishing-a-development-branch",
    "using-git-worktrees", "writing-skills", "receiving-code-review",
    "requesting-code-review", "systematic-debugging", "tdd",
    "init", "remember", "process", "evolve", "reflect", "synthesize",
    "status",
}


def available_skills() -> list[str]:
    """List plugin-original skill names (matches Skill tool input)."""
    skills_dir = plugin_root() / "skills"
    if not skills_dir.is_dir():
        return []
    out = []
    for p in sorted(skills_dir.iterdir()):
        if not p.is_dir():
            continue
        if p.name in VENDORED_SKILLS:
            continue
        if (p / "SKILL.md").is_file():
            out.append(p.name)
    return out


def available_mcp_servers() -> list[str]:
    """List plugin-original MCP server scripts.

    Returns the canonical mcp__plugin_kaizen_<name>__ prefix shape
    that PreToolUse events would carry (after Claude Code's
    namespacing). The actual prefix depends on plugin install
    name; we use kaizen-<server> as the lookup key for the bare-
    server name comparison."""
    scripts = plugin_root() / "skills" / "workflow" / "scripts"
    if not scripts.is_dir():
        return []
    out = []
    for p in sorted(scripts.glob("*_mcp.py")):
        # workflow_mcp.py → workflow
        name = p.stem
        if name.endswith("_mcp"):
            name = name[:-4]
        out.append(name)
    return out


def available_bins() -> list[str]:
    """List kaizen-* bin wrappers."""
    bin_dir = plugin_root() / "bin"
    if not bin_dir.is_dir():
        return []
    return sorted(p.name for p in bin_dir.iterdir() if p.is_file())


# ─── Never-used computation ──────────────────────────────────────────


def never_used(kind: str = "skill") -> dict:
    """Return artifacts of `kind` that have zero invocations in the
    trace log.

    kind ∈ {'skill', 'tool', 'mcp', 'bin'}.
    """
    full = rollup_events()
    if kind == "skill":
        used = set(full.by_skill.keys())
        available = set(available_skills())
        return {
            "kind": "skill",
            "available_count": len(available),
            "used_count": len(used & available),
            "never_used": sorted(available - used),
            "untracked_uses": sorted(used - available),  # things invoked but not in available_skills (e.g. vendored)
        }
    if kind == "mcp":
        # MCP tools appear as 'mcp__plugin_kaizen_<server>__<tool>' in trace
        used_raw = set(full.by_mcp.keys())
        # Extract the bare server name from each used entry
        used_servers = set()
        for full_name in used_raw:
            # Common shape: mcp__plugin_kaizen_<server>__<tool>
            m = re.match(r"mcp__plugin_kaizen_([a-zA-Z0-9-]+)__", full_name)
            if m:
                used_servers.add(m.group(1).replace("-", "_"))
            else:
                # Fallback shape: mcp__<server>__<tool>
                m2 = re.match(r"mcp__([a-zA-Z0-9_-]+)__", full_name)
                if m2:
                    used_servers.add(m2.group(1).replace("-", "_"))
        available = set(available_mcp_servers())
        # Normalize comparison: available are bare names ('brain', 'workflow', ...);
        # used_servers also bare-ish after the regex above
        never = sorted(available - {x.replace("-", "_") for x in used_servers})
        return {
            "kind": "mcp",
            "available_count": len(available),
            "used_count": len(available - set(never)),
            "never_used": never,
            "raw_used": sorted(used_raw)[:20],  # first 20 for context
        }
    if kind == "tool":
        used = set(full.by_tool.keys())
        # All tools we care about — match plugin-development's coverage list
        expected = {
            "Bash", "Skill", "Edit", "Write", "Read", "Glob", "Grep",
            "Agent", "TaskCreate", "TaskUpdate", "WebFetch", "WebSearch",
            "NotebookEdit",
        }
        return {
            "kind": "tool",
            "expected_count": len(expected),
            "used_count": len(used & expected),
            "never_used": sorted(expected - used),
            "untracked_uses": sorted(used - expected),
        }
    if kind == "bin":
        available = set(available_bins())
        # Bin invocations land as Bash events with 'kaizen-X' in the
        # command. We sub-parse the trace to detect.
        used: set[str] = set()
        for rec in iter_events():
            if rec.get("tool") != "Bash":
                continue
            data = rec.get("data") or {}
            cmd = data.get("command", "") or ""
            for b in available:
                if b in cmd:
                    used.add(b)
        return {
            "kind": "bin",
            "available_count": len(available),
            "used_count": len(used),
            "never_used": sorted(available - used),
        }
    raise ValueError(f"unknown kind: {kind!r}")


# ─── Top-N helpers ───────────────────────────────────────────────────


def top_n(kind: str, n: int = 10) -> list[tuple[str, int]]:
    full = rollup_events()
    if kind == "skill":
        return full.by_skill.most_common(n)
    if kind == "tool":
        return full.by_tool.most_common(n)
    if kind == "mcp":
        return full.by_mcp.most_common(n)
    if kind == "evt":
        return full.by_evt.most_common(n)
    raise ValueError(f"unknown kind: {kind!r}")


# ─── CLI ─────────────────────────────────────────────────────────────


def _cmd_session(args) -> int:
    sid = args.sid or latest_session_id()
    if not sid:
        print(json.dumps({"error": "no sessions found in trace"}))
        return 0
    r = rollup_events(sid=sid)
    d = r.to_dict()
    d["sid"] = sid
    if args.json:
        print(json.dumps(d, indent=2))
        return 0
    _print_rollup(d, title=f"Session {sid[:12]}")
    return 0


def _cmd_lifetime(args) -> int:
    since = parse_duration(args.since) if args.since else None
    r = rollup_events(since=since)
    d = r.to_dict()
    if args.json:
        print(json.dumps(d, indent=2))
        return 0
    _print_rollup(d, title=f"Lifetime{(' since ' + args.since) if args.since else ''}")
    return 0


def _cmd_never_used(args) -> int:
    result = never_used(args.kind)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    print(f"\n[kaizen-metrics never-used] kind={result['kind']}")
    print(f"  available: {result.get('available_count', result.get('expected_count', 0))}")
    print(f"  used:      {result['used_count']}")
    print(f"  never used: {len(result['never_used'])}")
    if result["never_used"]:
        print()
        for name in result["never_used"]:
            print(f"    - {name}")
    return 0


def _cmd_top(args) -> int:
    items = top_n(args.kind, args.n)
    if args.json:
        print(json.dumps([{"name": n, "count": c} for n, c in items], indent=2))
        return 0
    print(f"\n[kaizen-metrics top-{args.n}] kind={args.kind}")
    if not items:
        print("  (no data)")
        return 0
    for name, count in items:
        print(f"  {count:>6}  {name}")
    return 0


def _cmd_path(args) -> int:
    print(json.dumps({"trace_log": str(trace_log_path())}, indent=2))
    return 0


def _print_rollup(d: dict, title: str) -> None:
    print(f"\n[kaizen-metrics] {title}")
    print(f"  events     : {d['total_events']:>6}")
    print(f"  sessions   : {d['sessions']:>6}")
    print(f"  errors     : {d['errors']:>6}")
    print(f"  earliest   : {d.get('earliest_ts', '-')}")
    print(f"  latest     : {d.get('latest_ts', '-')}")
    if d.get("by_tool"):
        print("\n  by_tool (top 10):")
        for name, count in list(d["by_tool"].items())[:10]:
            print(f"    {count:>6}  {name}")
    if d.get("by_skill"):
        print("\n  by_skill (top 10):")
        for name, count in list(d["by_skill"].items())[:10]:
            print(f"    {count:>6}  {name}")
    if d.get("by_mcp"):
        print("\n  by_mcp (top 10):")
        for name, count in list(d["by_mcp"].items())[:10]:
            print(f"    {count:>6}  {name}")


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-metrics",
        description="Rollup + never-used catalog over the kaizen trace log.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s_sess = sub.add_parser("session", help="rollup for one session")
    s_sess.add_argument("--sid", help="session id (default: latest)")
    s_sess.add_argument("--json", action="store_true")
    s_sess.set_defaults(func=_cmd_session)

    s_life = sub.add_parser("lifetime", help="rollup over all events")
    s_life.add_argument("--since", help="duration (7d, 30m, 2w) or ISO timestamp")
    s_life.add_argument("--json", action="store_true")
    s_life.set_defaults(func=_cmd_lifetime)

    s_never = sub.add_parser("never-used", help="features available but never invoked")
    s_never.add_argument("--kind", choices=["skill", "tool", "mcp", "bin"],
                         default="skill")
    s_never.add_argument("--json", action="store_true")
    s_never.set_defaults(func=_cmd_never_used)

    s_top = sub.add_parser("top", help="most-used artifacts of a kind")
    s_top.add_argument("--kind", choices=["skill", "tool", "mcp", "evt"],
                       default="skill")
    s_top.add_argument("--n", type=int, default=10)
    s_top.add_argument("--json", action="store_true")
    s_top.set_defaults(func=_cmd_top)

    s_path = sub.add_parser("path", help="print trace log path")
    s_path.set_defaults(func=_cmd_path)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
