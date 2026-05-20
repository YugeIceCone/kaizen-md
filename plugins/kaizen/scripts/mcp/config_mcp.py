#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp>=3.0"]
# ///
"""kaizen MCP server — config lookup as MCP tools.

Wraps config.py so agents can query `.kaizen.toml` + plugin defaults
without subprocess. Sister to the bare `kaizen-config` bin.

Tools:
  config_get(key, default='')  → {key, value}
  config_defaults()             → {<PLUGIN_DEFAULTS dict>}
  config_validate()             → {errors[], warnings[], path}
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastmcp import FastMCP

_HERE = Path(os.path.realpath(__file__)).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import config as _cfg  # noqa: E402

mcp = FastMCP("config")

def config_get(key: str, default: str = "") -> dict:
    """Resolve a config key per the documented precedence
    (env > .kaizen.toml > plugin default > fallback).

    Args:
      key: config key to look up (e.g. 'compile_check_cmd', 'backlog_path').
      default: fallback when the key isn't set anywhere.

    Returns:
      dict with `key` (the queried name) + `value` (resolved string).
    """
    value = _cfg.get(key, default=default)
    return {"key": key, "value": value}

def config_defaults() -> dict:
    """Print the plugin-wide PLUGIN_DEFAULTS section as a flat dict.

    Returns:
      dict — every editable plugin knob (EMBED_MODEL, EMBED_DIM,
      USER_DIR_NAME, etc.). Mirrors `kaizen-config --defaults`.
    """
    return _cfg.plugin_defaults_dict()

def config_validate() -> dict:
    """Validate the current `.kaizen.toml` (when present).

    Returns:
      dict with `errors` (list of validation errors), `warnings`
      (list), `path` (resolved config-file path or null).
    """
    result = _cfg.validate()
    if not isinstance(result, dict):
        return {"errors": [], "warnings": [], "path": None}
    return result

mcp.tool()(config_get)
mcp.tool()(config_defaults)
mcp.tool()(config_validate)

if __name__ == "__main__":
    mcp.run()
