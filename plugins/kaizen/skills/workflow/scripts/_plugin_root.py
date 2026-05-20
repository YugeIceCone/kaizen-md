"""MIGRATION BRIDGE — _plugin_root moved to scripts/io/_plugin_root.py.

Bare ``import _plugin_root`` still resolves here when callers have only
``skills/workflow/scripts/`` on ``sys.path``. This stub loads the
canonical module from ``scripts/io/_plugin_root.py`` and aliases
``sys.modules["_plugin_root"]`` to it, so the caller observes the real
module — not an empty stub namespace. Both legacy and canonical
imports return the SAME module object (no duplicate-module pitfall).

Remove once every consumer adopts its own
``sys.path.insert(<plugin>/scripts/io)`` bridge.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_IO_DIR = _PLUGIN_ROOT / "scripts" / "io"
_LEGACY_DIR = _PLUGIN_ROOT / "skills" / "workflow" / "scripts"
_CANONICAL = _IO_DIR / "_plugin_root.py"

for _p in (_LEGACY_DIR, _IO_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_spec = importlib.util.spec_from_file_location("_plugin_root", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["_plugin_root"] = _mod
_spec.loader.exec_module(_mod)

# BK-061 — when invoked as `python3 .../skills/workflow/scripts/_plugin_root.py`
# (NOT as an import), mirror the canonical's __main__ behavior. importlib's
# exec_module doesn't trigger the canonical's `if __name__ == "__main__"`
# block — so the shim must explicitly forward the CLI semantics here.
if __name__ == "__main__":
    try:
        print(_mod.plugin_root())
    except _mod.PluginRootNotFound as e:
        sys.stderr.write(f"[_plugin_root] {e}\n")
        sys.exit(1)
