#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastmcp>=3.0",
# ]
# ///
"""kaizen manifests-mcp — multi-language manifest hygiene + MCP wrapper.

Tools:
  manifests_languages()   — list languages detected at root
  manifests_audit()       — all manifests + dep counts
  manifests_unused()      — heuristically-unused deps
"""
from __future__ import annotations

import dataclasses
import os
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
    import _manifests as kz_m  # type: ignore
except ImportError as e:
    sys.stderr.write(f"kaizen-manifests-mcp: missing dep: {e}\n")
    sys.exit(1)


mcp = FastMCP("kaizen-manifests")


def _root() -> Path:
    env = os.environ.get("KAIZEN_MANIFESTS_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return Path.cwd()


@mcp.tool()
async def manifests_languages() -> list[str]:
    """List languages with at least one canonical manifest file under
    the current root (rust/python/javascript/go). Polyglot repos
    return multiple."""
    return kz_m.languages_present(_root())


@mcp.tool()
async def manifests_audit() -> dict:
    """Full audit: every detected manifest + its dep list. Returns
    {root, languages, manifests: [{language, path, deps}], total_deps}.

    Read-only. The `deps` arrays carry `{name, version, kind}` per dep.
    For Cargo, `kind="workspace"` marks workspace.dependencies entries."""
    result = kz_m.audit(_root())
    # Convert Manifest dataclasses to dicts for JSON-friendly output
    out = dict(result)
    out["manifests"] = [
        {
            "language": m.language,
            "path": m.path,
            "deps": [dataclasses.asdict(d) for d in m.deps],
        }
        for m in result["manifests"]
    ]
    return out


@mcp.tool()
async def manifests_unused() -> dict:
    """Heuristically-unused deps across the repo.

    A dep is "unused" iff no source-tree file contains an
    import/require/use mention. Cheap text-grep — false positives
    possible (build-time deps, macros). Treat as cleanup candidates."""
    return kz_m.unused(_root())


if __name__ == "__main__":
    mcp.run()
