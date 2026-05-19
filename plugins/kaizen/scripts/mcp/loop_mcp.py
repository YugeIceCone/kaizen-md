#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastmcp>=3.0",
# ]
# ///
"""kaizen loop-mcp — MCP server exposing controlled access to the kaizen
Ralph-loop state file at .kaizen/loop.state.md.

Wraps `loop_state.py` (the validated CRUD module). Use these tools
instead of hand-editing the state file: every mutation is schema-checked
and audit-logged, and the `complete_item` tool refuses to bypass the
hook's verify gate for items that have one.

Tools (Claude can invoke):

  loop_add_item(desc, verify="")
    Append a new pending item. Auto-IDs (i1, i2, ...). `verify` is a
    bash command the Stop hook will run; omit (or empty string) for a
    trust-based item that must be manually completed via loop_complete_item.

  loop_list_pending()
    List current pending items (id, desc, verify).

  loop_list_completed()
    List completed items (audit log: id, desc, verify, iteration,
    completed_at, manual?). Read-only.

  loop_status()
    Loop iteration counter + pending/completed counts + started_at.

  loop_complete_item(id_or_desc, note="")
    Manually mark a `verify: null` item complete. Refuses items with a
    verify command (those must pass the hook gate — cheat-proof).

  loop_cancel()
    Remove the state file (equivalent of /kaizen:loop --cancel).

## State

Per-cwd SQLite-less state at `<cwd>/.kaizen/loop.state.md`. The MCP server
inherits cwd from the Claude Code project that spawned it. Override via
`KAIZEN_LOOP_STATE` env var.

## Spawning

Registered in `.mcp.json` as `loop`. Claude Code spawns on-demand when the
first `mcp__plugin_kaizen_loop__*` tool fires.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
# MIGRATION BRIDGE — relocated modules + legacy helpers
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "workflow" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "brain"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "indexers"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "handlers"))

try:
    from fastmcp import FastMCP
    import loop_state as ls  # type: ignore
except ImportError as e:
    sys.stderr.write(
        f"kaizen-loop-mcp: missing dep: {e}\n"
        "Ensure mcp>=1.0 is installed (uv handles this automatically).\n"
    )
    sys.exit(1)


mcp = FastMCP("kaizen-loop")


@mcp.tool()
async def loop_add_item(desc: str, verify: str = "") -> dict:
    """Append a new pending item to the active loop's ledger.

    desc:   short description of the work item (required, non-empty).
    verify: bash command the hook will run between iterations. The item
            moves to `completed` only when this command exits 0
            (cheat-proof gate). Omit (or empty string) for a trust-based
            item — must be manually closed via loop_complete_item.

    Returns the created item: {id, desc, verify}. The id auto-increments
    (i1, i2, ...) so subsequent calls can reference it unambiguously.

    Errors:
        FileNotFoundError if no active loop (.kaizen/loop.state.md missing)
        ValueError if desc is empty or body schema is broken"""
    try:
        return ls.add_item(desc, verify=verify or None)
    except FileNotFoundError as e:
        return {"error": str(e)}
    except ValueError as e:
        return {"error": str(e)}


@mcp.tool()
async def loop_list_pending() -> list[dict]:
    """List current pending items in the loop ledger.

    Returns [{id, desc, verify}, ...]. Empty list if no loop active or
    if all work is complete."""
    try:
        return ls.list_pending()
    except FileNotFoundError:
        return []


@mcp.tool()
async def loop_list_completed() -> list[dict]:
    """Audit log: items the hook (or manual completion) has moved to done.

    Returns [{id, desc, verify, iteration, completed_at, manual?}, ...].
    Read-only — the MCP cannot mutate this list (hook-owned)."""
    try:
        return ls.list_completed()
    except FileNotFoundError:
        return []


@mcp.tool()
async def loop_status() -> dict:
    """Loop state summary.

    Returns {active, iteration, max_iterations, pending_count,
    completed_count, completion_promise, started_at, state_path}.
    `active: false` means no loop is currently running."""
    return ls.status()


@mcp.tool()
async def loop_complete_item(id_or_desc: str, note: str = "") -> dict:
    """Manually complete a trust-based (verify=null) item.

    id_or_desc: exact `id` match (e.g. 'i3') OR case-insensitive
                substring match against the item's desc.
    note:       optional free-text reason / evidence, recorded in the
                completed entry.

    Returns the completed entry. Refuses items that have a `verify`
    command — those MUST pass the hook's verify gate (this is the
    cheat-proof completion path; manual completion of verify-bearing
    items would bypass the gate)."""
    try:
        return ls.complete_item(id_or_desc, note=note or None)
    except (FileNotFoundError, KeyError, ValueError) as e:
        return {"error": str(e)}


@mcp.tool()
async def loop_next() -> dict:
    """Token-saving accessor: just the next pending item.

    Returns the first item in the ledger's `pending` list as
    {id, desc, verify}, or {"empty": true} when the ledger is empty
    / no loop is active. Use this instead of loop_list_pending() when
    you only need the immediate next task (saves ~200 tokens on a
    20-item ledger)."""
    item = ls.next_pending()
    if item is None:
        return {"empty": True}
    return item


@mcp.tool()
async def loop_progress() -> dict:
    """Token-saving accessor: just the counters.

    Returns {active, iteration, pending_count, completed_count,
    max_iterations, pct_done}. No per-item details. For "how far along"
    queries during an iteration."""
    return ls.progress()


@mcp.tool()
async def loop_tldr() -> str:
    """Token-saving accessor: one-line compact summary string.

    Format: "iter N/M | P pending | C done | NEXT: <desc>". Empty
    string when no loop is active. Most-compact loop view — useful
    as a one-shot status header without parsing dicts."""
    return ls.tldr()


@mcp.tool()
async def loop_promise(phrase: str) -> dict:
    """Emit the completion promise as a structured tool call.

    Unambiguous alternative to writing <promise>X</promise> in text:
    tool calls cannot be confused with code-fence examples or
    explanatory text mentions. Recommended over the text-tag form.

    phrase: must exactly match the loop's configured completion_promise.

    Returns {emitted, phrase, matches, configured_promise}. The Stop
    hook checks the `last_promise` frontmatter field BEFORE the text-
    based regex extraction, so a successful call here ends the loop on
    the next Stop event."""
    try:
        return ls.emit_promise(phrase)
    except (FileNotFoundError, ValueError) as e:
        return {"error": str(e)}


@mcp.tool()
async def loop_cancel() -> dict:
    """Cancel the active loop (remove .kaizen/loop.state.md).

    Returns {cancelled: bool, iteration?, pending_count?, completed_count?}.
    A no-op if no loop is active."""
    return ls.cancel()


if __name__ == "__main__":
    mcp.run()
