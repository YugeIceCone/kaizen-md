"""MIGRATION BRIDGE — handoff moved to scripts/handoff/handoff.py.

Bare ``import handoff`` still resolves here when callers have only
``skills/workflow/scripts/`` on ``sys.path``. Loads the canonical and
aliases ``sys.modules["handoff"]`` so legacy + canonical imports return
the SAME module object.

NOTE: this stub is for module-import callers. Direct script invocation
(e.g. ``python3 skills/workflow/scripts/handoff.py``) does NOT trigger
the canonical's ``__main__`` block via ``spec.loader.exec_module``;
script-style callers should target ``scripts/handoff/handoff.py``
directly (bin/kaizen-handoff already does this).

Remove once every consumer adopts its own
``sys.path.insert(<plugin>/scripts/handoff)`` bridge.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_HANDOFF_DIR = _PLUGIN_ROOT / "scripts" / "handoff"
_CANONICAL = _HANDOFF_DIR / "handoff.py"

if str(_HANDOFF_DIR) not in sys.path:
    sys.path.insert(0, str(_HANDOFF_DIR))

_spec = importlib.util.spec_from_file_location("handoff", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["handoff"] = _mod
_spec.loader.exec_module(_mod)
