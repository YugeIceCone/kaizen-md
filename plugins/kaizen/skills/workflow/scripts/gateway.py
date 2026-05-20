#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastmcp>=3.0",
#     "pyyaml>=6.0",
#     "jsonschema>=4.0",
# ]
# ///
"""MIGRATION BRIDGE — gateway moved to scripts/mcp/gateway.py.

Dual behavior:
  - ``uv run --script .../gateway.py`` (legacy .mcp.json invocation):
    forwards execution to the canonical as __main__ via runpy so the
    FastMCP server actually starts.
  - ``import gateway`` (test + sibling-MCP consumers): loads the
    canonical via importlib.spec_from_file_location and aliases
    ``sys.modules["gateway"]`` so attribute access (SUBSERVERS,
    MOUNTED, CURATED_CORE, etc.) works regardless of sys.path order.

PEP-723 script-metadata kept identical so `uv run --script` resolves
the same dependency set.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_CANONICAL = _PLUGIN_ROOT / "scripts" / "mcp" / "gateway.py"

if not _CANONICAL.is_file():
    sys.stderr.write(f"gateway shim: canonical missing at {_CANONICAL}\n")
    sys.exit(1)

if __name__ == "__main__":
    # Production path: started via `uv run --script .../skills/workflow/
    # scripts/gateway.py` from .mcp.json. Forward to canonical __main__.
    import runpy
    runpy.run_path(str(_CANONICAL), run_name="__main__")
else:
    # Import path: tests + sibling MCPs do `import gateway`. Load the
    # canonical as a proper module + alias sys.modules so consumers
    # observe the real module object regardless of sys.path order.
    _spec = importlib.util.spec_from_file_location("gateway", _CANONICAL)
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["gateway"] = _mod
    _spec.loader.exec_module(_mod)
    # Re-export the canonical's public attributes on this shim module so
    # `from gateway import SUBSERVERS` resolves through either path.
    for _k in ("SUBSERVERS", "MOUNTED", "MOUNT_ERRORS", "CURATED_CORE",
               "SEARCH_TRANSFORM_APPLIED", "gw"):
        if hasattr(_mod, _k):
            globals()[_k] = getattr(_mod, _k)
