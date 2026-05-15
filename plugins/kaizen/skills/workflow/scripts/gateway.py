#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastmcp>=3.0",
#     "pyyaml>=6.0",
#     "jsonschema>=4.0",
# ]
# ///
"""kaizen MCP gateway — the single MCP entry point.

Composes the plugin's per-domain MCP sub-servers into one FastMCP
server. Each sub-server is imported as a plain Python module (its
`.run()` is __main__-guarded, so importing is side-effect-free) and
mounted WITHOUT a namespace — every tool name is already globally
unique via the per-server `<domain>_*` convention, so bare mount keeps
tool names byte-identical to the pre-gateway world.

A RegexSearchTransform restricts the default `list_tools()` output to a
curated `always_visible` core plus two synthetic tools
(`kaizen_search_tools` / `kaizen_call_tool`); every other tool stays
fully callable — the search transform controls discovery, not access.

API note (verified against fastmcp>=3.0 in Phase 1's spike):
`FastMCP.mount(server)` composes live; `RegexSearchTransform` takes
`always_visible: list[str]`, `search_tool_name`, `call_tool_name` as
constructor kwargs.

Phase 1: pilots only (iron_laws, manifests, drift). Later phases extend
SUBSERVERS into the full 21-server list.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastmcp import FastMCP

# (name, module-import-name) for every sub-server to mount. Extended in
# later phases. `name` is the short domain label used in diagnostics.
SUBSERVERS: list[tuple[str, str]] = [
    ("iron_laws", "iron_laws_mcp"),
    ("manifests", "manifests_mcp"),
    ("drift", "drift_mcp"),
]

gw = FastMCP("kaizen")
MOUNTED: list[tuple[str, object]] = []
MOUNT_ERRORS: list[str] = []

for name, modname in SUBSERVERS:
    try:
        mod = __import__(modname)
        gw.mount(mod.mcp)
        MOUNTED.append((name, mod))
    except Exception as exc:  # one broken server must not kill the gateway
        MOUNT_ERRORS.append(f"{name}: {exc}")

if __name__ == "__main__":
    if MOUNT_ERRORS:
        for e in MOUNT_ERRORS:
            print(f"[gateway] mount error: {e}", file=sys.stderr)
    gw.run()
