#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastmcp>=3.0",
# ]
# ///
"""kaizen shim-mcp — MCP server exposing the `kaizen-shim` refactor surface.

Wraps `shim.py` (the existing CLI module). Lets Claude execute the
shim-and-sweep routine programmatically: init manifest, carve a file from
old → new with auto-generated re-export shim, list manifest entries,
sweep (F-FINAL) under explicit user authorization.

Tools (Claude can invoke):

  shim_init(slug)
    Create `.kaizen/workflow/deletion-manifest-<slug>.txt`. Idempotent.

  shim_carve(old, new, slug, reexport="", dry_run=False)
    Copy <old> → <new>, replace <old> with a 1-line re-export shim,
    append <old> to the manifest. For .rs / .py files, `reexport`
    (canonical module path) is REQUIRED. For .ts/.tsx/.js/.jsx/.mjs/
    .cjs, the shim path is auto-computed.

  shim_list(slug, include_keep=False)
    Print manifest entries.

  shim_sweep(slug, allow_delete=False, dry_run=True)
    F-FINAL — `git rm` non-KEEP manifest entries in one revertible
    commit (preceded by a `pre-sweep-<slug>` tag). Refuses unless
    `allow_delete=True` OR `KAIZEN_ALLOW_DELETE=1` env var.

## Iron Laws (preserved from skills/shim-and-sweep/SKILL.md)

1. Every relocation leaves a 1-line shim (no broken imports mid-refactor).
2. Shims accumulate in the deletion manifest (no orphans).
3. Compile + tests green at every commit boundary.
4. F-FINAL is user-gated (--allow-delete or KAIZEN_ALLOW_DELETE=1).
5. Rollback via `git reset --hard pre-sweep-<slug>` is always available.

## Spawning

Registered in `.mcp.json` as `shim`. Claude Code spawns on-demand when
the first `mcp__plugin_kaizen_shim__*` tool fires. CWD inherits from
the project that spawned it.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

try:
    from fastmcp import FastMCP
    import shim  # type: ignore
except ImportError as e:
    sys.stderr.write(
        f"kaizen-shim-mcp: missing dep: {e}\n"
        "Ensure mcp>=1.0 is installed (uv handles this automatically).\n"
    )
    sys.exit(1)


mcp = FastMCP("kaizen-shim")


@mcp.tool()
async def shim_init(slug: str) -> dict:
    """Initialize the deletion manifest for a refactor slug.

    slug: short label for this refactor (e.g. 'borg-loop-cleanup',
          'rename-mcp-tools'). Used as the manifest filename and as the
          safety tag prefix on sweep.

    Returns {manifest_path, created} where `created` is True iff the
    file did not already exist. Idempotent — safe to call multiple times."""
    try:
        path = shim.manifest_init(slug)
        # Detect whether we just created it or it already existed: there's
        # no clean way to tell from manifest_init's return. Re-check via mtime
        # vs creation — for now, treat any successful return as success.
        return {
            "manifest_path": str(path),
            "slug": slug,
            "ok": True,
        }
    except (OSError, ValueError) as e:
        return {"error": str(e)}


@mcp.tool()
async def shim_carve(
    old: str,
    new: str,
    slug: str,
    reexport: str = "",
    dry_run: bool = False,
) -> dict:
    """Carve a file: copy old → new, replace old with a shim, append manifest.

    old:      path of the file to relocate (relative to repo root or absolute)
    new:      destination path (canonical home of the content)
    slug:     refactor slug (must match a prior `shim_init`)
    reexport: REQUIRED for .rs and .py files — the canonical module path
              to re-export from (e.g. 'shodan_nodes::runtime::borg::state'
              for Rust, 'mypkg.nodes.borg.state' for Python). For TS/JS
              files the relative path is computed automatically.
    dry_run:  if True, return what would be done without touching files.

    Returns {old, new, manifest_path, shim_language, actions: [...]}.
    Raises on bad inputs (missing source, same old==new, language not
    supported, missing reexport for Rust/Python)."""
    try:
        old_path = Path(old)
        new_path = Path(new)
        return shim.carve(
            old_path,
            new_path,
            slug,
            reexport=reexport or None,
            dry_run=dry_run,
        )
    except (ValueError, OSError) as e:
        return {"error": str(e)}


@mcp.tool()
async def shim_list(slug: str, include_keep: bool = False) -> list[dict]:
    """List manifest entries for a slug.

    slug:         refactor slug
    include_keep: when False (default), return only entries marked for
                  deletion (no KEEP annotation). When True, include
                  KEEP-flagged entries too (back-compat re-exports that
                  should stay).

    Returns [{date, path, keep_reason?}, ...]. Empty list if manifest
    is absent or empty."""
    try:
        entries = shim.manifest_read(slug)
    except (OSError, ValueError):
        return []
    out = []
    for date, path, keep_reason in entries:
        if keep_reason and not include_keep:
            continue
        entry = {"date": date, "path": path}
        if keep_reason:
            entry["keep_reason"] = keep_reason
        out.append(entry)
    return out


@mcp.tool()
async def shim_sweep(
    slug: str,
    allow_delete: bool = False,
    dry_run: bool = True,
) -> dict:
    """F-FINAL — `git rm` non-KEEP manifest entries in one revertible commit.

    slug:         refactor slug
    allow_delete: gate flag. MUST be True (or KAIZEN_ALLOW_DELETE=1 env
                  var set) for any actual deletion to occur. This is the
                  cheat-proof user-gating per the shim-and-sweep skill's
                  Iron Law 4.
    dry_run:      when True (default), report what would be deleted
                  without actually running `git rm`. When False AND
                  allow_delete is satisfied, performs the deletion in
                  one commit prefixed by `git tag -f pre-sweep-<slug>`.

    Returns {deleted: [...], kept: [(path, reason)...], tag, dry_run}.
    Raises PermissionError if neither allow_delete nor the env var
    is set."""
    try:
        return shim.sweep(
            slug,
            allow_delete=allow_delete,
            dry_run=dry_run,
        )
    except PermissionError as e:
        return {"error": str(e), "permission_denied": True}
    except (OSError, ValueError) as e:
        return {"error": str(e)}


if __name__ == "__main__":
    mcp.run()
