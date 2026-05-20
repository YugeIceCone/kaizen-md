#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastmcp>=3.0",
# ]
# ///
"""kaizen workflow-mcp — MCP server exposing workflow-routing's state machine.

Wraps `workflow.sh` + `workflow_runner.py` so Claude can drive multi-stage
workflows (audit / build-feature / fix-bug / refactor / migrate / harden /
schema=<name>) without the user typing a single slash command.

## Tools

  workflow_init(prompt, schema?, subagent?, auto?, tdd?)
  workflow_advance(stage, summary)
  workflow_artifact(key, value)
  workflow_branch(stage, key)               (v1.17.0+ confidence branching)
  workflow_status()                         current state JSON
  workflow_reset(confirm=True)              clear state (requires confirm)
  workflow_list_schemas()                   all available schemas + paths
  workflow_show_schema(name)                full schema content
  workflow_validate_schema(name)            validate; return errors

## Pattern

Same FastMCP + subprocess pattern as state_mcp.py. No embedding model.
All `*_mcp.py` follow this shape — see kaizen-state for the precedent.

## Why an MCP server for workflows

Without this, driving a workflow requires the user to either:
1. Type `bash workflow.sh advance <stage>` between every Claude turn, or
2. Ask Claude to do it via the Bash tool (verbose + permission prompts)

With it: Claude calls `mcp__plugin_kaizen_kaizen-workflow__workflow_advance`
directly. Same auth surface as the other 9 kaizen MCP servers.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path

try:
    # ty: ignore[unresolved-import]  — uv-script PEP 723 deps invisible to ty
    from fastmcp import FastMCP
except ImportError as e:
    sys.stderr.write(f"kaizen-workflow-mcp: missing mcp dep: {e}\n")
    sys.exit(1)

mcp = FastMCP("workflow")

SCRIPT_DIR = Path(__file__).resolve().parent
# workflow.sh + workflow_runner.py now live alongside this file at
# skills/workflow/scripts/ (v1.31.0 merge — was skills/workflow-routing/scripts/).

# M2 dedup: shared in _subproc.py (default timeout 30s is the workflow MCP variant).
from _subproc import git_repo_root as _repo_root  # noqa: E402, F401
from _subproc import run as _run  # noqa: E402

def _read_state() -> dict | None:
    """Return current state.json contents (parsed) or None if no workflow active."""
    state_path = Path(_repo_root()) / ".kaizen" / "workflow" / "state.json"
    if not state_path.exists():
        return None
    try:
        return json.loads(state_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None

# ─── Workflow state-machine tools ────────────────────────────────────

@mcp.tool()
async def workflow_init(
    prompt: str,
    schema: str = "",
    subagent: str = "no",
    auto: str = "no",
    tdd: str = "no",
    skill: str = "",
) -> dict:
    """Initialize a workflow run. Writes .kaizen/workflow/state.json.

    prompt: natural-language task description (workflow.sh verb-detects from this)
    schema: optional schema name (overrides verb-detection; one of the 10 built-ins)
    subagent: "no" | "yes" | "full"
    auto: "no" (pause for approval after create-tasks) | "yes" (auto-continue)
    tdd: "no" | "yes" (enforce TDD discipline per stage)
    skill: optional starting-stage skill name (skip earlier stages)

    Returns parsed state.json + the next stage to run."""
    full_prompt = prompt
    for key, val in [("schema", schema), ("subagent", subagent),
                     ("auto", auto), ("tdd", tdd), ("skill", skill)]:
        if val and val != "no":  # "no" is the default; only append if non-default
            full_prompt += f" {key}={val}"
    r = _run(["bash", str(WF_SH), "init", full_prompt])
    state = _read_state()
    return {
        "exit_code": r["exit_code"],
        "init_output": r["stdout"],
        "stderr": r["stderr"] if r["exit_code"] != 0 else "",
        "state": state,
    }

@mcp.tool()
async def workflow_advance(stage: str, summary: str) -> dict:
    """Advance from <stage> to the next stage. summary is a one-line result note.

    Returns the new state + the next-stage name. If the workflow completed,
    `next_stage` will be null."""
    r = _run(["bash", str(WF_SH), "advance", stage, summary])
    state = _read_state()
    next_stage = None
    if state:
        cur = state.get("current", 0)
        stages = state.get("stages", [])
        next_stage = stages[cur] if cur < len(stages) else None
    return {
        "exit_code": r["exit_code"],
        "output": r["stdout"],
        "stderr": r["stderr"] if r["exit_code"] != 0 else "",
        "next_stage": next_stage,
        "state": state,
    }

@mcp.tool()
async def workflow_artifact(key: str, value: str) -> dict:
    """Record an artifact (key=value pair) in state.json.

    Standard keys: plan_file, tasks_file, audit_report, mcp_server, fix_diff."""
    r = _run(["bash", str(WF_SH), "artifact", key, value])
    return {
        "exit_code": r["exit_code"],
        "output": r["stdout"].strip(),
        "stderr": r["stderr"] if r["exit_code"] != 0 else "",
    }

@mcp.tool()
async def workflow_branch(stage: str, key: str) -> dict:
    """Splice state.stages[current:] with the schema's branch_<key> for <stage>.

    Requires a schema-driven workflow. `key` is one of "high", "medium", "low".
    Use after a confidence-scored stage completes to pick the branch path.

    Inspect available branches via workflow_show_schema(<name>) — look at
    artifacts[].branch_high / branch_medium / branch_low."""
    r = _run(["bash", str(WF_SH), "branch", stage, key])
    return {
        "exit_code": r["exit_code"],
        "output": r["stdout"],
        "stderr": r["stderr"] if r["exit_code"] != 0 else "",
        "state": _read_state(),
    }

@mcp.tool()
async def workflow_status() -> dict:
    """Current workflow state. Returns {state: <state.json>, summary: <str>}.

    Returns {state: null} if no workflow is active."""
    state = _read_state()
    if state is None:
        return {"state": None, "summary": "no active workflow"}
    cur = state.get("current", 0)
    stages = state.get("stages", [])
    return {
        "state": state,
        "summary": {
            "id": state.get("id"),
            "routine": state.get("routine"),
            "current_index": cur,
            "current_stage": stages[cur] if cur < len(stages) else None,
            "completed": stages[:cur],
            "remaining": stages[cur:],
            "auto": state.get("auto"),
            "subagent": state.get("subagent"),
        },
    }

@mcp.tool()
async def workflow_reset(confirm: bool = False) -> dict:
    """Reset the active workflow (delete state.json). REQUIRES confirm=True.

    Pre-deletion belief: this destroys workflow state. The caller must
    explicitly pass confirm=True. Without it, the tool returns the would-be
    action without performing it."""
    if not confirm:
        return {
            "would_reset": True,
            "current_state": _read_state(),
            "hint": "Call again with confirm=True to actually reset.",
        }
    r = _run(["bash", str(WF_SH), "reset"])
    return {
        "exit_code": r["exit_code"],
        "output": r["stdout"],
        "stderr": r["stderr"] if r["exit_code"] != 0 else "",
    }

# ─── Schema introspection ────────────────────────────────────────────

@mcp.tool()
async def workflow_list_schemas() -> list[dict]:
    """List all available workflow schemas across project/user/built-in tiers.

    Returns [{name, tier, path}], where tier is "project" / "user" / "built-in"."""
    r = _run(["python3", str(WF_RUNNER), "list"])
    out: list[dict] = []
    for line in r["stdout"].splitlines():
        line = line.strip()
        if not line:
            continue
        # Format: "<name>  [<tier>] <path>"
        parts = line.split(None, 2)
        if len(parts) >= 3 and parts[1].startswith("[") and parts[1].endswith("]"):
            out.append({
                "name": parts[0],
                "tier": parts[1].strip("[]"),
                "path": parts[2],
            })
    return out

@mcp.tool()
async def workflow_show_schema(name: str) -> dict:
    """Return the full schema content (parsed). Useful for inspecting
    artifacts/requires/branch_* structure."""
    r = _run(["python3", str(WF_RUNNER), "show", name])
    if r["exit_code"] != 0:
        return {"error": r["stderr"] or "schema not found", "exit_code": r["exit_code"]}
    try:
        return json.loads(r["stdout"])
    except json.JSONDecodeError as e:
        return {"error": f"parse_error: {e}", "raw": r["stdout"][:2000]}

@mcp.tool()
async def workflow_validate_schema(name: str) -> dict:
    """Validate a schema's structure. Returns {valid: bool, errors: [str]}."""
    r = _run(["python3", str(WF_RUNNER), "validate", name])
    return {
        "valid": r["exit_code"] == 0,
        "output": r["stdout"].strip(),
        "errors": [e.strip("  • ") for e in r["stdout"].splitlines() if e.startswith("  •")] if r["exit_code"] != 0 else [],
    }

if __name__ == "__main__":
    mcp.run()
