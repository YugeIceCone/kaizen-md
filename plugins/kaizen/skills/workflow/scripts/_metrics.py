"""kaizen metrics core — trace-log primitives.

Pure, side-effect-light primitives consumed by ``metrics.py`` (CLI)
and ``metrics_mcp.py`` (MCP server). Carved out of the original
single-file ``metrics.py`` so the feature matches the canonical
11-slot shape (``_<feature>.py`` core + ``<feature>.py`` public CLI).

What lives here:

- **Path resolution** — ``trace_log_path`` / ``plugin_root``
- **Event reader** — ``iter_events`` streams the trace jsonl
- **Duration parsing** — ``parse_duration`` ('7d' / '30m' / ISO)
- **Rollup** — the ``Rollup`` dataclass + ``rollup_events`` orchestrator
- **Session lookup** — ``latest_session_id``
- **Artifact discovery** — ``available_skills`` / ``available_mcp_servers``
  / ``available_bins`` + the ``VENDORED_SKILLS`` exclusion set
- **never_used** — adoption-gap computation per kind
- **detect_skips** + ``SKIP_RULES`` — skill-skip detection
- **top_n** — most-used artifacts of a kind

The CLI (`metrics.py`) imports the public surface via
``from _metrics import *`` (gated by ``__all__`` below).
"""

from __future__ import annotations

import collections
import datetime as dt
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional


__all__ = [
    "trace_log_path",
    "plugin_root",
    "iter_events",
    "parse_duration",
    "Rollup",
    "rollup_events",
    "latest_session_id",
    "VENDORED_SKILLS",
    "available_skills",
    "available_mcp_servers",
    "available_bins",
    "never_used",
    "SKIP_RULES",
    "detect_skips",
    "top_n",
]


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

    Returns the bare server name (``workflow_mcp.py`` → ``workflow``).
    The trace's mcp__plugin_kaizen_<name>__ prefix is normalized to
    this bare form in ``never_used``."""
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
            "untracked_uses": sorted(used - available),  # invoked but not in available_skills (e.g. vendored)
        }
    if kind == "mcp":
        # MCP tools appear as 'mcp__plugin_kaizen_<server>__<tool>' in trace
        used_raw = set(full.by_mcp.keys())
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


# ─── Skip detection ──────────────────────────────────────────────────


# Rules: skill-name → glob patterns whose presence in the session's
# file-edit activity implies the skill SHOULD have been loaded.
# Mirrors iron-laws.yaml::skill-cant-be-skipped, but encoded here
# for fast machine evaluation.
SKIP_RULES = [
    {
        "skill": "plugin-development",
        "patterns": [
            "plugins/kaizen/skills/workflow/scripts/",
            "plugins/kaizen/skills/<>/",  # any feature dir under skills/
            "plugins/kaizen/commands/",
            "plugins/kaizen/hooks/",
            "plugins/kaizen/bin/",
            "plugins/kaizen/.claude-plugin/plugin.json",
            "plugins/kaizen/hooks/hooks.json",
        ],
        "rationale": "iron-laws.yaml::skill-cant-be-skipped + pref-kaizen-plugin-dev",
    },
    {
        "skill": "brain",
        "patterns": [
            "plugins/kaizen/skills/brain/",
            "plugins/kaizen/skills/workflow/scripts/_brain.py",
            "plugins/kaizen/skills/workflow/scripts/brain",  # prefix match
            "~/.claude/brain/Notes/",
            "~/.claude/brain/Persona.md",
        ],
        "rationale": "Touching brain Notes / pipeline without the brain skill loaded",
    },
    {
        "skill": "workflow",
        "patterns": [
            "plugins/kaizen/skills/workflow/scripts/workflow",  # prefix
            "plugins/kaizen/commands/workflow.md",
        ],
        "rationale": "Touching workflow scripts without loading workflow skill",
    },
]


def detect_skips(sid: Optional[str] = None) -> list[dict]:
    """For the given session (or the latest), return skill-skip
    candidates: skills whose triggering files were touched but the
    skill itself was never loaded.

    Returns a list of {skill, rationale, touched_files} dicts.
    Empty list when no skips detected."""
    sid = sid or latest_session_id()
    if not sid:
        return []
    # Files touched this session (via Edit / Write / NotebookEdit ident)
    touched_paths: set[str] = set()
    skills_loaded: set[str] = set()
    for rec in iter_events(sid=sid):
        evt = rec.get("evt", "")
        if not evt.startswith("PreToolUse-"):
            continue
        tool = rec.get("tool", "")
        data = rec.get("data") or {}
        ident = data.get("ident", "")
        if tool in {"Edit", "Write", "NotebookEdit"} and ident:
            touched_paths.add(ident)
        elif tool == "Skill" and ident:
            skills_loaded.add(ident)
    out: list[dict] = []
    for rule in SKIP_RULES:
        skill = rule["skill"]
        if skill in skills_loaded:
            continue
        triggers = []
        for path in touched_paths:
            for pattern in rule["patterns"]:
                # Wildcard <> placeholder = any single path component
                if "<>" in pattern:
                    parts = pattern.split("<>", 1)
                    if path.startswith(parts[0]) and parts[1] in path:
                        triggers.append(path)
                        break
                elif pattern.startswith("~/"):
                    expanded = os.path.expanduser(pattern)
                    if expanded in path or path.startswith(expanded):
                        triggers.append(path)
                        break
                else:
                    if pattern in path:
                        triggers.append(path)
                        break
        if triggers:
            out.append({
                "skill": skill,
                "rationale": rule["rationale"],
                "touched_files": sorted(set(triggers))[:10],
                "touched_count": len(set(triggers)),
            })
    return out


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
