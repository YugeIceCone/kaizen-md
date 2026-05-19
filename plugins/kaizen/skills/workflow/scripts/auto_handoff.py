"""MIGRATION BRIDGE — auto_handoff moved to scripts/handoff/auto_handoff.py.

Bare ``import auto_handoff`` still resolves here when callers have only
``skills/workflow/scripts/`` on ``sys.path``. Loads the canonical and
aliases ``sys.modules["auto_handoff"]`` so legacy + canonical imports
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
_CANONICAL = _HANDOFF_DIR / "auto_handoff.py"

if str(_HANDOFF_DIR) not in sys.path:
    sys.path.insert(0, str(_HANDOFF_DIR))

_spec = importlib.util.spec_from_file_location("auto_handoff", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["auto_handoff"] = _mod
_spec.loader.exec_module(_mod)
