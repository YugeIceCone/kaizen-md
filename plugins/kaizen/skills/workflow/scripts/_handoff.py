"""MIGRATION BRIDGE — _handoff moved to scripts/handoff/_handoff.py.

Bare ``import _handoff`` still resolves here when callers have only
``skills/workflow/scripts/`` on ``sys.path``. Loads the canonical and
aliases ``sys.modules["_handoff"]`` so legacy + canonical imports
return the SAME module object.

Remove once every consumer adopts its own
``sys.path.insert(<plugin>/scripts/handoff)`` bridge.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_HANDOFF_DIR = _PLUGIN_ROOT / "scripts" / "handoff"
_CANONICAL = _HANDOFF_DIR / "_handoff.py"

if str(_HANDOFF_DIR) not in sys.path:
    sys.path.insert(0, str(_HANDOFF_DIR))

_spec = importlib.util.spec_from_file_location("_handoff", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["_handoff"] = _mod
_spec.loader.exec_module(_mod)
