"""kaizen spec-driven — phase-gate verifier.

Before advancing the workflow runner from phase N → phase N+1, verify:

  1. The blueprint item representing phase N has status ∈ {shipped, active}
     (active = in-flight but tests green; shipped = closed-success).
  2. The blueprint's content_hash matches its stored value (no external
     mutation since the last CLI write).
  3. Optionally — N's all tasks are completed (when item kind=task-list).

A failing gate refuses advance + returns the reason. Pairs with
kaizen-blueprint::verify_hash + kaizen:workflow phase-advance hooks.

API:

  gate_check(plan_path, item_id, *, require_shipped=True,
             require_all_tasks_completed=False) -> dict
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Reach into the sibling blueprint module
_THIS = Path(__file__).resolve()
sys.path.insert(0, str(_THIS.parent.parent / "blueprint"))
import _blueprint as bp  # noqa: E402


def gate_check(plan_path: str | Path, item_id: str, *,
               require_shipped: bool = True,
               require_all_tasks_completed: bool = False) -> dict[str, Any]:
    """Verify a phase gate. Returns:

      {
        "ok": bool,
        "reason": str,
        "item_status": str,
        "hash_ok": bool,
        "hash_first_read": bool,
        "task_summary": {pending, in_progress, completed, total} | None,
      }
    """
    # Item presence + status
    try:
        item = bp.read_item(plan_path, id=item_id)
    except (KeyError, ValueError) as e:
        return {
            "ok": False,
            "reason": f"item {item_id!r} not found in plan",
            "item_status": None,
            "hash_ok": False,
            "hash_first_read": False,
            "task_summary": None,
        }
    status = item.get("status", "")
    expected = ("shipped",) if require_shipped else ("active", "shipped")
    status_ok = status in expected

    # Hash integrity
    hash_result = bp.verify_hash(plan_path)
    hash_ok = hash_result["ok"]
    hash_first_read = hash_result["first_read"]

    # Task summary (when item is a task-list)
    task_summary = None
    tasks_ok = True
    if item.get("kind") == "task-list" and item.get("tasks"):
        tasks = item["tasks"]
        summary = {"pending": 0, "in_progress": 0, "completed": 0,
                   "blocked": 0, "skipped": 0, "total": len(tasks)}
        for t in tasks:
            s = t.get("status", "pending")
            summary[s] = summary.get(s, 0) + 1
        task_summary = summary
        if require_all_tasks_completed:
            unfinished = summary["pending"] + summary["in_progress"] \
                       + summary["blocked"]
            tasks_ok = unfinished == 0

    # Compose verdict
    if not status_ok:
        return {
            "ok": False,
            "reason": f"item.status={status!r}, expected one of {expected}",
            "item_status": status,
            "hash_ok": hash_ok,
            "hash_first_read": hash_first_read,
            "task_summary": task_summary,
        }
    if not hash_ok and not hash_first_read:
        return {
            "ok": False,
            "reason": "content_hash drift detected — external mutation",
            "item_status": status,
            "hash_ok": False,
            "hash_first_read": False,
            "task_summary": task_summary,
        }
    if not tasks_ok:
        return {
            "ok": False,
            "reason": (f"task-list has unfinished tasks: "
                       f"pending={task_summary['pending']} "
                       f"in_progress={task_summary['in_progress']} "
                       f"blocked={task_summary['blocked']}"),
            "item_status": status,
            "hash_ok": hash_ok,
            "hash_first_read": hash_first_read,
            "task_summary": task_summary,
        }
    return {
        "ok": True,
        "reason": "gate clear",
        "item_status": status,
        "hash_ok": hash_ok,
        "hash_first_read": hash_first_read,
        "task_summary": task_summary,
    }


__all__ = ["gate_check"]
