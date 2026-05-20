"""uv-run-with helper.

Builds the canonical `uv run --with <tool> -- <tool> <args...>` command list.

## Why this exists

System binaries installed via snap (e.g. `/snap/bin/ruff`) are confined and
cannot read `~/.claude/` or other directories the user might lint. Using
`uv run --with <tool>` forces uv to download the tool into a one-shot venv
so the binary runs in the unconfined Python environment instead.

This pattern is repeated 5× in lint_mcp.py (ruff_check, ruff_format,
ruff_rules, ty_check, ty_explain) and likely will be repeated as more
MCPs wrap Python tooling. Extracting the command-builder keeps the
pattern DRY and reduces the chance of an MCP-tool author forgetting
the `--no-cache` flag or the `--` separator.

## Usage

    from _uv import uv_cmd

    cmd = uv_cmd("ruff", ["check", "--output-format=json", path])
    # → ["uv", "run", "--with", "ruff", "--", "ruff", "check", ...]
    result = subprocess.run(cmd, ...)

The helper is *just* the command-builder, not a subprocess.run wrapper —
callers may want different timeout/cwd/text handling, and a separate
`_run` helper already exists per-MCP for that. Keeping concerns split
(build cmd vs run cmd) matches SoC.

## Caveats

- `--no-cache` is added for `ruff` only (not `ty`) to match the existing
  lint_mcp.py pattern. ty has different cache semantics.
- The tool name is repeated (`--with <name> -- <name>`) because uv's
  `--with` installs the package and the bare `--` separator lets the
  remaining args go to the installed binary, not to uv.
"""
from __future__ import annotations

def uv_cmd(tool: str, args: list[str]) -> list[str]:
    """Build a `uv run --with <tool> -- <tool> <args...>` command list.

    tool: the binary name to install + run (e.g. "ruff", "ty").
    args: positional args to pass to the tool itself (including any
          tool-specific flags like `--no-cache` for ruff).

    Returns a list ready to pass to `subprocess.run([list], ...)`.
    Never returns shell-quoted strings; the list-form is the security
    barrier against argument injection."""
    return ["uv", "run", "--with", tool, "--", tool, *args]
