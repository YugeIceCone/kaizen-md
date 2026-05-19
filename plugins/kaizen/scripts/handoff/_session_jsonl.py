"""kaizen _session_jsonl — Claude Code session-transcript miner.

Closes the "agent re-derives session state from memory" inefficiency by
extracting what the harness already records:

- latest ai-title (the running session-summary AI suggests)
- task graph (TaskCreate input subjects + TaskUpdate status flips,
  reconstructed into {task_id: {subject, status}})
- files touched (Read/Edit/Write tool_use file_path inputs)
- skills used (Skill tool_use skill names)
- session start timestamp (first timestamped record)
- per-tool invocation counts

Used by handoff scaffold to slash the agent's compose-from-memory cost.
Could also drive metrics, brain-audit enrichment, /loop scheduling.

Storage layout (Claude Code, single-user CLI):

    ~/.claude/projects/<cwd-slug>/
    └── <session-uuid>.jsonl     ← we mine this

Where `cwd-slug` is the cwd's absolute path with `/` → `-` (so
`/home/u/repo` becomes `-home-u-repo`).

Stdlib only. No fixture-API dependencies — the JSONL is a stable
Claude Code artifact; this module is the read-side adapter.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Optional

# `Task #N created successfully: <subject>` — the canonical TaskCreate
# tool_result format (verified against the live session JSONL). Drives
# the task_id↔subject mapping since TaskCreate's input has no id.
_TASKCREATE_RESULT_RE = re.compile(
    r"^Task\s+#(?P<id>\d+)\s+created successfully:\s*(?P<subject>.+?)$",
    re.MULTILINE,
)


# Tool names whose `file_path` input we want to harvest into files_touched
_FILE_TOOLS = frozenset({"Read", "Edit", "Write", "NotebookEdit"})


def cwd_to_slug(cwd: Path) -> str:
    """Translate an absolute cwd to the Claude Code project-slug shape.

    `/home/u/repo` → `-home-u-repo` (slash-prefixed → leading dash).
    Round-trip cousin of how CC creates `~/.claude/projects/<slug>/`."""
    s = str(cwd.resolve())
    return s.replace("/", "-")


def discover_session_jsonl(jsonl_dir: Path) -> Optional[Path]:
    """Return the most-recently-modified *.jsonl in `jsonl_dir`, or None.

    The agent's ACTIVE session is the JSONL currently being appended to
    — its mtime is RIGHT NOW (CC flushes per-event). So "latest mtime"
    is reliable for finding the active session from any kaizen tool the
    agent calls.

    Only top-level .jsonl files considered (subagent JSONLs live under
    `<slug>/<sid>/subagents/` — separate concern)."""
    if not jsonl_dir.is_dir():
        return None
    candidates = [p for p in jsonl_dir.iterdir() if p.is_file() and p.suffix == ".jsonl"]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def discover_active_session_id(cwd: Optional[Path] = None) -> Optional[str]:
    """One-call helper: cwd → ~/.claude/projects/<slug>/ → latest JSONL → stem.

    Returns the active session_id string (or None when not running under
    Claude Code, no project dir, or empty project dir).

    Single source for the cwd-based session discovery used by
    statusline_dxm, statusline_intent, dxm._cmd_session_id, and any
    future consumer that needs "what session am I in?"."""
    cwd_path = Path(cwd or ".").resolve()
    slug = cwd_to_slug(cwd_path)
    proj = Path.home() / ".claude" / "projects" / slug
    jsonl = discover_session_jsonl(proj)
    return jsonl.stem if jsonl else None


def _iter_records(jsonl_path: Path):
    """Yield parsed JSON records from a JSONL file, skipping malformed
    lines silently. The miner must never raise on bad input — partial
    extraction beats no extraction."""
    try:
        with jsonl_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def _extract_tool_use_blocks(record: dict):
    """For an assistant record, yield each tool_use content block dict."""
    if record.get("type") != "assistant":
        return
    msg = record.get("message")
    if not isinstance(msg, dict):
        return
    content = msg.get("content") or []
    if not isinstance(content, list):
        return
    for blk in content:
        if isinstance(blk, dict) and blk.get("type") == "tool_use":
            yield blk


def _extract_tool_result_blocks(record: dict):
    """For a user record, yield each tool_result content block dict."""
    if record.get("type") != "user":
        return
    msg = record.get("message")
    if not isinstance(msg, dict):
        return
    content = msg.get("content") or []
    if not isinstance(content, list):
        return
    for blk in content:
        if isinstance(blk, dict) and blk.get("type") == "tool_result":
            yield blk


def mine_session(jsonl_path: Path) -> dict[str, Any]:
    """Walk a session JSONL once and extract the mining payload.

    Returns a dict with stable keys (always present, even when empty):

        {
          "ai_title":            str | None,
          "session_started_at":  str | None,    # ISO 8601
          "tasks":               {task_id: {"subject": str, "status": str}},
          "completed_tasks":     [subject, ...] in creation order,
          "pending_tasks":       [subject, ...] in creation order
                                  (status in {pending, in_progress}),
          "files_touched":       set[str] of file_path inputs,
          "skills_used":         set[str] of skill names,
          "tools_used_counts":   {tool_name: count},
        }
    """
    ai_title: Optional[str] = None
    session_started_at: Optional[str] = None
    tasks: dict[str, dict[str, str]] = {}
    # task_creation_order preserves the order Task #1, #2, #3 ... so
    # completed_tasks / pending_tasks come back in a deterministic order.
    task_creation_order: list[str] = []
    files_touched: set[str] = set()
    skills_used: set[str] = set()
    tools_used: Counter[str] = Counter()

    # First pass: collect tool_use blocks + tool_result blocks + ai-title +
    # session start. Task subjects are pending until we see their result.
    pending_task_creates: dict[str, str] = {}  # tool_use_id → subject

    for record in _iter_records(jsonl_path):
        rtype = record.get("type")
        # ai-title: keep the latest
        if rtype == "ai-title":
            t = record.get("aiTitle")
            if t:
                ai_title = t
            continue

        # Session start: first record with a timestamp wins
        if session_started_at is None:
            ts = record.get("timestamp")
            if not ts:
                snap = record.get("snapshot") or {}
                ts = snap.get("timestamp") if isinstance(snap, dict) else None
            if ts:
                session_started_at = ts

        # Tool-use blocks (assistant turns)
        for blk in _extract_tool_use_blocks(record):
            name = blk.get("name") or ""
            tools_used[name] += 1
            inp = blk.get("input") or {}
            if not isinstance(inp, dict):
                continue
            if name == "TaskCreate":
                subj = inp.get("subject") or ""
                tool_use_id = blk.get("id") or ""
                if tool_use_id and subj:
                    pending_task_creates[tool_use_id] = subj
            elif name == "TaskUpdate":
                tid = inp.get("taskId")
                status = inp.get("status")
                if tid and status:
                    # Latest status wins (linear walk)
                    if tid in tasks:
                        tasks[tid]["status"] = status
                    else:
                        # TaskUpdate before any TaskCreate that landed —
                        # rare; record with placeholder subject.
                        tasks[tid] = {"subject": f"(unresolved task {tid})",
                                       "status": status}
                        task_creation_order.append(tid)
            elif name in _FILE_TOOLS:
                fp = inp.get("file_path")
                if isinstance(fp, str) and fp:
                    files_touched.add(fp)
            elif name == "Skill":
                skill = inp.get("skill")
                if isinstance(skill, str) and skill:
                    skills_used.add(skill)

        # Tool-result blocks (user turns following a tool_use)
        for blk in _extract_tool_result_blocks(record):
            tu_id = blk.get("tool_use_id")
            content = blk.get("content")
            if not isinstance(content, str) or not tu_id:
                continue
            if tu_id in pending_task_creates:
                m = _TASKCREATE_RESULT_RE.search(content)
                if m:
                    tid = m.group("id")
                    subj = pending_task_creates.pop(tu_id)
                    if tid not in tasks:
                        tasks[tid] = {"subject": subj, "status": "pending"}
                        task_creation_order.append(tid)

    # Build the bucket lists in creation order
    completed_tasks = [
        tasks[tid]["subject"]
        for tid in task_creation_order
        if tasks[tid]["status"] == "completed"
    ]
    pending_tasks = [
        tasks[tid]["subject"]
        for tid in task_creation_order
        if tasks[tid]["status"] in {"pending", "in_progress"}
    ]

    return {
        "ai_title":           ai_title,
        "session_started_at": session_started_at,
        "tasks":              tasks,
        "completed_tasks":    completed_tasks,
        "pending_tasks":      pending_tasks,
        "files_touched":      files_touched,
        "skills_used":        skills_used,
        "tools_used_counts":  dict(tools_used),
    }


__all__ = ["cwd_to_slug", "discover_session_jsonl",
            "discover_active_session_id", "mine_session"]
