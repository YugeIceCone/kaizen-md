"""MIGRATION BRIDGE — schema_cli moved to scripts/rules/schema_cli.py.

Bare ``import schema_cli`` still resolves here when callers have only
``skills/workflow/scripts/`` on ``sys.path``. This stub loads the
canonical module from ``scripts/rules/schema_cli.py`` and aliases
``sys.modules["schema_cli"]`` to it, so the caller observes the real
``schema_cli`` (BucketWalker, lens_dispatch, etc.) — not an empty stub
namespace. Both legacy and canonical imports return the SAME module
object, so ``isinstance`` checks remain coherent.

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
_CANONICAL = _RULES_DIR / "schema_cli.py"

for _p in (_LEGACY_DIR, _RULES_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_spec = importlib.util.spec_from_file_location("schema_cli", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["schema_cli"] = _mod
_spec.loader.exec_module(_mod)
