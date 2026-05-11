#!/usr/bin/env python3
"""kaizen schemas — dataclass SSOT for kaizen's implicit JSON shapes.

Before v1.9.0, four shapes lived only in comments + scattered field
accesses across scripts:

  TraceEvent   — `~/.claude/.kaizen-trace/events.jsonl`
  InboxMessage — `~/.claude/kaizen-inbox/<ts>-<n>.json`
  DaemonState  — `~/.claude/.kaizen-daemon/state.json`
  BacklogItem  — `<repo>/.workflow/backlog.json` (items[])

This module declares each shape as a `@dataclass`. Writers construct
typed instances and serialize via `asdict()`. Readers may use
`from_dict()` for typed access or stay dict-based (tolerant for
backward compat).

## Forward / backward compat policy

- `from_dict()` IGNORES unknown fields (forward-compat: newer writers
  can add fields that older readers don't know about).
- Missing fields fall back to the dataclass default (backward-compat:
  older writers' files load cleanly under newer readers).
- This is incremental SDD — adopt the dataclass at one writer at a
  time; on-disk shape stays compatible throughout.

## Why not Pydantic / attrs

Stdlib-only: kaizen runs in any Python 3.10+ env including
constrained CI sandboxes. `dataclasses` + `typing` + `json` cover
the use case without a pip dep.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Optional


# ─── Helpers ─────────────────────────────────────────────────────────


def from_dict(cls, data: dict):
    """Construct a dataclass instance from a dict, tolerating extra +
    missing fields. Nested dataclasses NOT auto-resolved — caller
    handles those one level at a time (kept simple to stay stdlib-only)."""
    if not isinstance(data, dict):
        raise TypeError(f"expected dict, got {type(data).__name__}")
    known = {f.name for f in fields(cls)}
    kwargs = {k: v for k, v in data.items() if k in known}
    return cls(**kwargs)


# ─── TraceEvent ──────────────────────────────────────────────────────
#
# One line in events.jsonl. Producer: trace.py event command (called
# by hooks/_trace.sh, llm_proxy.py, daemon.py, browser_mcp.py via
# PreToolUse/PostToolUse, agent dispatches).


VALID_TRACE_SOURCES = frozenset({"hook", "agent", "llm", "tool", "user", "cc", "plugin"})


@dataclass
class TraceEvent:
    ts: str                           # ISO UTC, ms precision (e.g. "2026-05-12T00:30:00.123Z")
    src: str                          # one of VALID_TRACE_SOURCES
    evt: str                          # event name (free-form within src)
    sid: str = ""                     # session_id (empty if not applicable)
    tool: str = ""                    # tool name (for src=hook|tool events)
    ms: Optional[int] = None          # duration_ms (None if not measured)
    data: dict = field(default_factory=dict)

    def to_jsonl_dict(self) -> dict:
        """Compact dict for JSONL line write — drops empty/None fields."""
        out: dict = {"ts": self.ts, "src": self.src, "evt": self.evt}
        if self.sid:
            out["sid"] = self.sid
        if self.tool:
            out["tool"] = self.tool
        if self.ms is not None:
            out["ms"] = self.ms
        if self.data:
            out["data"] = self.data
        return out

    def validate(self) -> list[str]:
        """Return list of validation errors (empty = valid)."""
        errs: list[str] = []
        if self.src not in VALID_TRACE_SOURCES:
            errs.append(f"invalid src={self.src!r} (valid: {sorted(VALID_TRACE_SOURCES)})")
        if not self.evt:
            errs.append("evt is required (non-empty)")
        if self.ms is not None and self.ms < 0:
            errs.append(f"ms must be >=0, got {self.ms}")
        return errs


# ─── InboxMessage ────────────────────────────────────────────────────
#
# One file per user prompt under ~/.claude/kaizen-inbox/<ts>-<n>.json.
# Producer: inbox.py capture (called by hooks/userprompt-inbox.sh).
# Consumer: inbox.py {list,peek,drain,stats}.


@dataclass
class InboxMessage:
    ts: str                                    # ISO UTC, ms precision
    prompt: str                                # verbatim user text
    session_id: str = ""                       # CC session uuid
    drained: bool = False                      # surfaced via PostToolUse drain?
    drained_at: Optional[str] = None           # when drained (ISO)
    drain_reason: str = ""                     # "turn-starter-completed" | ""

    def to_dict(self) -> dict:
        """Full dict for on-disk persistence (preserves nullable fields)."""
        return asdict(self)


# ─── DaemonState ─────────────────────────────────────────────────────
#
# Single file ~/.claude/.kaizen-daemon/state.json. Producer + consumer:
# daemon.py tick / status.


@dataclass
class DaemonState:
    runs: int = 0                              # incremented per tick
    last_run: Optional[str] = None             # ISO UTC
    source_hash: str = ""                      # SHA1 of plugin source dir
    cache_hash: str = ""                       # SHA1 of cached version dir
    local_sha: str = ""                        # git rev-parse HEAD (marketplace)
    remote_sha: str = ""                       # ls-remote origin master
    actions: dict = field(default_factory=dict)  # {action_name: count}

    def to_dict(self) -> dict:
        return asdict(self)


# ─── BacklogItem / BacklogDecision / BacklogStore ────────────────────
#
# .workflow/backlog.json envelope. Producer + consumer: backlog.py.
# Note: BacklogStore migration is deferred to a separate micro since
# render_md() has a stable contract that's risky to refactor in one
# step. These dataclasses are available for future adoption.


@dataclass
class BacklogItem:
    id: str                                    # "BK-NNN"
    title: str
    section: str = "next_up"                   # next_up | in_flight | done | parked
    probe: str = ""                            # grep/cargo-tree/etc. proving micro size
    verify: str = ""                           # command proving completion
    ref: str = ""                              # source quote / context
    tags: list = field(default_factory=list)
    created: Optional[str] = None              # ISO UTC
    started: Optional[str] = None
    completed: Optional[str] = None
    parked: Optional[str] = None
    parked_reason: str = ""
    committed_sha: str = ""


@dataclass
class BacklogDecision:
    text: str
    why: str = ""
    ts: Optional[str] = None


@dataclass
class BacklogStore:
    schema_version: int = 1
    kind: str = "kaizen.backlog"
    items: list = field(default_factory=list)     # list[BacklogItem]
    decisions: list = field(default_factory=list) # list[BacklogDecision]
    metadata: dict = field(default_factory=dict)  # {created, updated, ...}


# ─── Module self-test ────────────────────────────────────────────────


def _self_test() -> None:
    """Sanity-check round-trips. Run with: python3 schemas.py"""
    # TraceEvent
    e = TraceEvent(ts="2026-05-12T00:30:00.123Z", src="hook", evt="PreToolUse-bash",
                    tool="Bash", sid="sid-1", ms=12, data={"command": "ls"})
    assert e.validate() == []
    bad = TraceEvent(ts="x", src="bogus", evt="x")
    assert "invalid src" in bad.validate()[0]
    d = e.to_jsonl_dict()
    assert d["src"] == "hook"
    e2 = from_dict(TraceEvent, d)
    assert e2.src == "hook" and e2.tool == "Bash"

    # InboxMessage
    m = InboxMessage(ts="2026-05-12T00:31:00Z", prompt="hi", session_id="sid-1")
    md = m.to_dict()
    m2 = from_dict(InboxMessage, md)
    assert m2.prompt == "hi"

    # InboxMessage with unknown field (forward-compat)
    m3 = from_dict(InboxMessage, {**md, "future_field": "ignored"})
    assert m3.prompt == "hi"

    # DaemonState
    s = DaemonState(runs=42, actions={"refresh-cache": 3, "hygiene": 42})
    sd = s.to_dict()
    s2 = from_dict(DaemonState, sd)
    assert s2.runs == 42 and s2.actions["hygiene"] == 42

    # BacklogItem
    b = BacklogItem(id="BK-001", title="test", probe="grep ...", verify="cargo test")
    bd = asdict(b)
    b2 = from_dict(BacklogItem, bd)
    assert b2.id == "BK-001"

    print("✓ all schema round-trips pass")


if __name__ == "__main__":
    _self_test()
