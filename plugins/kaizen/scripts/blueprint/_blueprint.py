"""kaizen _blueprint — pure-core read/mutate helpers for blueprint JSON.

Companion to _atomic (the atomic-write primitive). Blueprint-specific
because it understands the items[] array, id semantics, and DAG links.
Pure functions only — no I/O side effects other than the atomic-write
wrappers in the mutating helpers.

## Design — 1-2 roundtrip access

The blueprint is a single JSON file with `items[]` as an array. Common
reads need ONE call:

  read_plan(path)                   — whole plan (1 roundtrip)
  read_item(path, index=N)          — items[N] by array index (1 roundtrip)
  read_item(path, id=X)             — items[?].id == X (1 roundtrip)
  read_subtree(path, root, hops=1)  — root + linked children (1 roundtrip;
                                       walks DAG in-memory after one read)

Mutating helpers ALWAYS go through _atomic.atomic_write_json so partial
writes are impossible:

  set_item_status(path, id, status)   — flip status atomically
  set_task_status(path, task_id, ..)  — flip task status atomically
  add_item(path, item)                — append item (validates id-unique)
  add_task(path, list_id, task)       — append task to a task-list item

Schema-validation is OPTIONAL — pass `validate=True` to any mutator and
it'll jsonschema-check before writing. Default is fast-path (no
jsonschema import unless asked).

Stdlib-only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Add sibling scripts to path so `import _atomic` works whether this
# module is invoked as `python3 .../blueprint/_blueprint.py` or imported
# from the CLI wrapper.
_THIS = Path(__file__).resolve()
_SCRIPTS_ROOT = _THIS.parent.parent
sys.path.insert(0, str(_SCRIPTS_ROOT / "io"))

import _atomic  # noqa: E402


# ─── Format detection (.json vs .yaml) ──────────────────────────────────

def _is_yaml(path: str | Path) -> bool:
    """True iff path ends in .yaml or .yml (case-insensitive)."""
    s = str(path).lower()
    return s.endswith(".yaml") or s.endswith(".yml")


def _write_plan(path: str | Path, data: dict) -> None:
    """Atomic-write a blueprint, picking JSON or YAML by extension.
    JSON is via _atomic.atomic_write_json (sort_keys=False). YAML is
    via PyYAML safe_dump + _atomic.atomic_write (string)."""
    if _is_yaml(path):
        import yaml
        body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True,
                              default_flow_style=False) + ""
        _atomic.atomic_write(path, body)
    else:
        _atomic.atomic_write_json(path, data, sort_keys=False)


# ─── Pure reads (1 roundtrip each) ──────────────────────────────────────

def read_plan(path: str | Path) -> dict[str, Any]:
    """Return the whole blueprint as a dict. Auto-detects format by
    extension (.yaml / .yml → PyYAML safe_load; else json.loads)."""
    text = Path(path).read_text(encoding="utf-8")
    if _is_yaml(path):
        import yaml
        return yaml.safe_load(text)
    return json.loads(text)


def read_item(path: str | Path, *, index: int | None = None,
              id: str | None = None) -> dict[str, Any]:
    """Return one item by INDEX (items[N]) or by ID (items[?].id == id).

    Exactly one of `index` / `id` must be provided. Raises KeyError if
    the id isn't found; IndexError if the index is out of range.
    """
    if (index is None) == (id is None):
        raise ValueError("read_item: pass exactly one of index= or id=")
    plan = read_plan(path)
    items = plan.get("items", [])
    if index is not None:
        return items[index]  # IndexError if out of range
    for it in items:
        if it.get("id") == id:
            return it
    raise KeyError(f"no item with id={id!r}")


def read_subtree(path: str | Path, root_id: str,
                 *, hops: int = 1,
                 follow: str = "children") -> dict[str, Any]:
    """Return root + items reachable via `links.<follow>` within `hops` hops.

    `follow` ∈ {children, parents, related, supersedes}. Default 1-hop
    (root + direct children). Returns a dict shaped:
        {"root": <item>, "linked": [<item>, ...]}
    The linked list preserves DAG order (BFS from root).
    """
    plan = read_plan(path)
    by_id = {i["id"]: i for i in plan.get("items", [])}
    if root_id not in by_id:
        raise KeyError(f"no item with id={root_id!r}")
    seen = {root_id}
    frontier = [root_id]
    linked: list[dict[str, Any]] = []
    for _ in range(hops):
        next_frontier: list[str] = []
        for node_id in frontier:
            refs = by_id[node_id].get("links", {}).get(follow, [])
            if not isinstance(refs, list):
                refs = [refs] if refs else []
            for r in refs:
                if r and r in by_id and r not in seen:
                    seen.add(r)
                    linked.append(by_id[r])
                    next_frontier.append(r)
        frontier = next_frontier
        if not frontier:
            break
    return {"root": by_id[root_id], "linked": linked}


def list_items(path: str | Path) -> list[dict[str, str]]:
    """Return a compact index: one row per item with id / kind / title /
    status. Use this when you want to scan-before-pull."""
    return [
        {
            "index": i,
            "id": it.get("id", ""),
            "kind": it.get("kind", ""),
            "status": it.get("status", ""),
            "title": it.get("title", ""),
        }
        for i, it in enumerate(read_plan(path).get("items", []))
    ]


# ─── Mutating helpers (atomic-write via _atomic) ────────────────────────

def _find_item_index(plan: dict, item_id: str) -> int:
    for i, it in enumerate(plan.get("items", [])):
        if it.get("id") == item_id:
            return i
    raise KeyError(f"no item with id={item_id!r}")


def set_item_status(path: str | Path, item_id: str, new_status: str,
                    *, validate: bool = False) -> dict[str, str]:
    """Flip an item's status atomically. Returns {old, new}.

    If validate=True, schema-check before writing.
    """
    plan = read_plan(path)
    idx = _find_item_index(plan, item_id)
    old = plan["items"][idx].get("status", "")
    plan["items"][idx]["status"] = new_status
    if validate:
        _schema_validate(plan)
    _write_plan(path, plan)
    return {"old": old, "new": new_status}


def set_task_status(path: str | Path, task_id: str, new_status: str,
                    *, validate: bool = False) -> dict[str, str]:
    """Flip a task's status atomically. Task ids are looked up across
    every task-list item's tasks[]. Returns {old, new}."""
    plan = read_plan(path)
    for it in plan.get("items", []):
        for t in (it.get("tasks") or []):
            if t.get("id") == task_id:
                old = t.get("status", "")
                t["status"] = new_status
                if validate:
                    _schema_validate(plan)
                _write_plan(path, plan)
                return {"old": old, "new": new_status}
    raise KeyError(f"no task with id={task_id!r}")


def add_item(path: str | Path, new_item: dict,
             *, validate: bool = False) -> str:
    """Append `new_item` to items[]. Validates id-uniqueness. Returns the new id."""
    plan = read_plan(path)
    existing_ids = {it.get("id") for it in plan.get("items", [])}
    nid = new_item.get("id")
    if not nid:
        raise ValueError("new_item must have id")
    if nid in existing_ids:
        raise ValueError(f"item id={nid!r} already exists")
    plan["items"].append(new_item)
    if validate:
        _schema_validate(plan)
    _write_plan(path, plan)
    return nid


def add_task(path: str | Path, list_id: str, new_task: dict,
             *, validate: bool = False) -> str:
    """Append `new_task` to the items[?].tasks[] where id == list_id.
    Validates task-id uniqueness within the list. Returns new task id."""
    plan = read_plan(path)
    idx = _find_item_index(plan, list_id)
    item = plan["items"][idx]
    if item.get("kind") != "task-list":
        raise ValueError(f"item {list_id} is kind={item.get('kind')}, "
                         f"not task-list")
    tasks = item.get("tasks") or []
    existing = {t.get("id") for t in tasks}
    tid = new_task.get("id")
    if not tid:
        raise ValueError("new_task must have id")
    if tid in existing:
        raise ValueError(f"task id={tid!r} already exists in {list_id}")
    tasks.append(new_task)
    item["tasks"] = tasks
    if validate:
        _schema_validate(plan)
    _write_plan(path, plan)
    return tid


# ─── Schema validation (lazy import — only when validate=True) ──────────

_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent.parent
    / ".kaizen" / "docs" / "templates" / "blueprint.schema.json"
)
# Fallback to the legacy location if the new one isn't there yet.
_SCHEMA_PATH_FALLBACK = (
    Path(__file__).resolve().parent.parent.parent.parent.parent
    / ".kaizen" / "superpowers" / "templates" / "planning-blueprint"
    / "blueprint.schema.json"
)


def _schema_validate(plan: dict) -> None:
    """jsonschema-validate the plan against blueprint.schema.json. Raises
    on failure. Imports jsonschema lazily so callers who don't validate
    don't pay the import cost."""
    import jsonschema
    schema_path = _SCHEMA_PATH if _SCHEMA_PATH.is_file() else _SCHEMA_PATH_FALLBACK
    schema = json.loads(schema_path.read_text())
    jsonschema.validate(plan, schema)


def resume(path: str | Path) -> dict | None:
    """Pick the next actionable task. Returns the task + its parent
    item, or None if nothing is actionable.

    Order (first match wins):
      1. Any task with status=in_progress (resume mid-task)
      2. The first pending task whose blocked_by deps are all completed
      3. None — nothing pending OR everything blocked

    Returns: {item: <task-list item>, task: <task>, reason: str}
    """
    plan = read_plan(path)
    items = plan.get("items", [])
    all_tasks_by_id: dict[str, dict] = {}
    for it in items:
        for t in (it.get("tasks") or []):
            all_tasks_by_id[t.get("id", "")] = t

    # Pass 1: any in_progress
    for it in items:
        for t in (it.get("tasks") or []):
            if t.get("status") == "in_progress":
                return {"item": it, "task": t,
                        "reason": "task in_progress — resume mid-flight"}
    # Pass 2: first unblocked pending
    for it in items:
        for t in (it.get("tasks") or []):
            if t.get("status") != "pending":
                continue
            blocked_by = t.get("blocked_by") or []
            unmet = [b for b in blocked_by
                     if all_tasks_by_id.get(b, {}).get("status")
                     not in ("completed", "skipped")]
            if not unmet:
                return {"item": it, "task": t,
                        "reason": "pending + all blocked_by deps clear"}
    return None


def dag_check(path: str | Path) -> list[str]:
    """Return a list of broken-link errors. Empty list = DAG clean."""
    plan = read_plan(path)
    ids = {i["id"] for i in plan.get("items", [])}
    broken: list[str] = []
    for it in plan.get("items", []):
        for kind, refs in (it.get("links") or {}).items():
            if isinstance(refs, list):
                for r in refs:
                    if r and r not in ids:
                        broken.append(
                            f"{it['id']}.links.{kind} -> {r}"
                        )
    return broken


# ─── Chunking (parallel-branches kit D2 / chunk-sizing rubric) ──────────

def chunk_tasks(path: str | Path, list_id: str,
                *, subagents: bool = False) -> dict:
    """Decompose a task-list's tasks[] into chunks.

    DEFAULT (subagents=False) — parent walks 3 tasks per chunk. The
    chunks-of-3 give the parent natural commit/verify boundaries
    between batches. No Agent() dispatch.

    OPT-IN (subagents=True) — apply the parallel-branches kit's
    chunking-floor rubric (D2) for subagent dispatch:

      ≤3 items     → PARENT_DOES_IT  — no dispatch; parent walks
      4-6 items    → ONE_SUBAGENT    — 1 dispatch, no decomposition
      7-30 items   → GRID            — ceil(N/3) chunks; 2-3 tasks each
      31+ items    → POOL            — queue-picker (out of CLI scope)

    Returns:
        {
          "bucket": str,
          "chunks": [[task, ...], ...],   # one inner list per chunk
          "n_tasks": int,
          "n_chunks": int,
          "dispatch_hint": dict,           # mode + isolation + agent
          "rationale": str,
        }

    Skips tasks already in status `completed` or `skipped` — chunking
    only considers in-flight + pending work.
    """
    plan = read_plan(path)
    item = next((i for i in plan.get("items", []) if i.get("id") == list_id),
                None)
    if item is None:
        raise KeyError(f"no item with id={list_id!r}")
    if item.get("kind") != "task-list":
        raise ValueError(
            f"item {list_id} is kind={item.get('kind')}, not task-list"
        )
    tasks = item.get("tasks") or []
    in_flight = [t for t in tasks if t.get("status") not in
                 ("completed", "skipped")]
    n = len(in_flight)

    if not subagents:
        # DEFAULT — parent walks 3 tasks per chunk. No dispatch.
        import math
        chunks: list[list] = []
        for i in range(0, n, 3):
            chunks.append(in_flight[i:i + 3])
        n_chunks = len(chunks)
        bucket = "PARENT_DOES_IT"
        rationale = (
            f"{n} in-flight tasks → {n_chunks} chunk(s) of 3 (parent "
            "executes; commit/verify between chunks). No Agent() dispatch."
        )
        dispatch_hint = {"mode": "sequential", "isolation": "inline",
                         "agent": None}
        return {
            "bucket": bucket,
            "chunks": chunks,
            "n_tasks": n,
            "n_chunks": n_chunks,
            "dispatch_hint": dispatch_hint,
            "rationale": rationale,
        }

    # OPT-IN subagent path — D2 rubric
    if n <= 3:
        bucket = "PARENT_DOES_IT"
        chunks = [in_flight] if in_flight else []
        rationale = (f"{n} in-flight tasks ≤3 — setup cost > work cost; "
                     "parent walks them directly. No Agent() dispatch.")
        dispatch_hint = {"mode": "sequential", "isolation": "inline",
                         "agent": None}
    elif n <= 6:
        bucket = "ONE_SUBAGENT"
        chunks = [in_flight]
        rationale = (f"{n} in-flight tasks (4-6) — one fresh subagent, "
                     "worktree isolation. No chunking.")
        dispatch_hint = {"mode": "sequential", "isolation": "worktree",
                         "agent": "kaizen-implementer"}
    elif n <= 30:
        import math
        n_chunks = math.ceil(n / 3)
        chunks = []
        per_chunk = math.ceil(n / n_chunks)
        for i in range(0, n, per_chunk):
            chunks.append(in_flight[i:i + per_chunk])
        bucket = "GRID"
        rationale = (f"{n} in-flight tasks → {n_chunks} chunks of "
                     f"~{per_chunk} tasks each (D2 floor: 2-3/chunk).")
        dispatch_hint = {"mode": "parallel", "isolation": "worktree",
                         "agent": "kaizen-implementer"}
    else:
        bucket = "POOL"
        chunks = []
        rationale = (f"{n} tasks > 30 — queue-picker pool, out of scope "
                     "for this CLI. Use parallel-branches kit runtime.")
        dispatch_hint = {"mode": "waves", "isolation": "worktree",
                         "agent": "kaizen-implementer"}
    return {
        "bucket": bucket,
        "chunks": chunks,
        "n_tasks": n,
        "n_chunks": len(chunks),
        "dispatch_hint": dispatch_hint,
        "rationale": rationale,
    }


__all__ = [
    "read_plan",
    "read_item",
    "read_subtree",
    "list_items",
    "set_item_status",
    "set_task_status",
    "add_item",
    "add_task",
    "dag_check",
    "chunk_tasks",
    "resume",
]
