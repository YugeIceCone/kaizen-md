"""MIGRATION BRIDGE — rubric moved to scripts/rules/rubric.py.

Bare ``import rubric`` still resolves here when callers have only
``skills/workflow/scripts/`` on ``sys.path``. This stub loads the
canonical module from ``scripts/rules/rubric.py`` and aliases
``sys.modules["rubric"]`` to it, so the caller observes the real
CLI entry points — not an empty stub namespace. Both legacy and
canonical imports return the SAME module object.

Remove once every consumer adopts its own
``sys.path.insert(<plugin>/scripts/rules)`` bridge.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_RULES_DIR = _PLUGIN_ROOT / "scripts" / "rules"
_LEGACY_DIR = _PLUGIN_ROOT / "skills" / "workflow" / "scripts"
_CANONICAL = _RULES_DIR / "rubric.py"

for _p in (_LEGACY_DIR, _RULES_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_spec = importlib.util.spec_from_file_location("rubric", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["rubric"] = _mod
_spec.loader.exec_module(_mod)
