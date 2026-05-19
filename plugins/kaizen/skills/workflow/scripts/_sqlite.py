"""MIGRATION BRIDGE — _sqlite moved to scripts/io/_sqlite.py.

Bare ``import _sqlite`` still resolves here when callers have only
``skills/workflow/scripts/`` on ``sys.path``. This stub loads the
canonical module from ``scripts/io/_sqlite.py`` and aliases
``sys.modules["_sqlite"]`` to it, so the caller observes the real
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
_CANONICAL = _IO_DIR / "_sqlite.py"

for _p in (_LEGACY_DIR, _IO_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_spec = importlib.util.spec_from_file_location("_sqlite", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["_sqlite"] = _mod
_spec.loader.exec_module(_mod)
