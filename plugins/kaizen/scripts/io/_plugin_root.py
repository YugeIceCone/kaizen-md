"""kaizen plugin-root resolver — Python mirror of `_plugin_root.sh`.

Use this from any kaizen Python script that needs to reference the
plugin's own files (hooks, MCP entrypoints, scripts):

    from _plugin_root import plugin_root
    root = plugin_root()                 # raises if unresolved
    root = plugin_root(strict=False)     # returns None instead of raising

Resolution order (first hit wins):
  1. ``$CLAUDE_PLUGIN_ROOT``  if set and points at a kaizen plugin dir
  2. ``$KAIZEN_PLUGIN_ROOT``  if set and points at a kaizen plugin dir
  3. derived from this file's own path by walking up to find
     ``.claude-plugin/plugin.json``

A "kaizen plugin dir" is any dir containing
``.claude-plugin/plugin.json``. This makes the helper work across Claude
Code (sets ``$CLAUDE_PLUGIN_ROOT`` at hook-fire time), Codex CLI (no env
at all → script-derived), or any other host that prefers to set
``$KAIZEN_PLUGIN_ROOT`` explicitly.

Keep this in sync with ``_plugin_root.sh`` (same env vars, same order,
same marker file).
"""
from __future__ import annotations

import os
from pathlib import Path

# Public for the test suite + tooling; mirrored in `_plugin_root.sh`.
MARKER = Path(".claude-plugin") / "plugin.json"
ENV_VARS = ("CLAUDE_PLUGIN_ROOT", "KAIZEN_PLUGIN_ROOT")

class PluginRootNotFound(RuntimeError):
    """Raised when no candidate satisfies the resolution order."""

def _is_plugin_dir(candidate: Path) -> bool:
    return (candidate / MARKER).is_file()

def _from_env() -> Path | None:
    """Return the first env-var value that points at a kaizen plugin dir."""
    for name in ENV_VARS:
        raw = os.environ.get(name)
        if not raw:
            continue
        p = Path(raw)
        if _is_plugin_dir(p):
            return p
    return None

def _from_script_path(start: Path) -> Path | None:
    """Walk up from `start` looking for the plugin marker. Returns None if not found."""
    cur = start.resolve()
    for candidate in (cur, *cur.parents):
        if _is_plugin_dir(candidate):
            return candidate
    return None

def plugin_root(strict: bool = True) -> Path | None:
    """Resolve the kaizen plugin root.

    Args:
        strict: when True (default), raise ``PluginRootNotFound`` if
            resolution fails. When False, return ``None``.

    Returns:
        ``Path`` to the plugin root, or ``None`` if not strict and
        unresolved.
    """
    found = _from_env() or _from_script_path(Path(__file__))
    if found is not None:
        return found
    if strict:
        raise PluginRootNotFound(
            "kaizen plugin root unresolved — set CLAUDE_PLUGIN_ROOT or "
            "KAIZEN_PLUGIN_ROOT, or place this script under a directory "
            "containing .claude-plugin/plugin.json"
        )
    return None

if __name__ == "__main__":
    import sys

    try:
        print(plugin_root())
    except PluginRootNotFound as e:
        sys.stderr.write(f"[_plugin_root] {e}\n")
        sys.exit(1)
