"""MIGRATION BRIDGE — _plan_loader moved to scripts/parallel_branches/.

Test co-located with the skill also moved to plugins/kaizen/tests/
(canonical kaizen test location). Loads canonical via importlib +
sys.modules alias.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_PB_DIR = _PLUGIN_ROOT / "scripts" / "parallel_branches"
_LEGACY_DIR = _PLUGIN_ROOT / "skills" / "parallel-branches" / "scripts"
_CANONICAL = _PB_DIR / "_plan_loader.py"

for _p in (_LEGACY_DIR, _PB_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_spec = importlib.util.spec_from_file_location("_plan_loader", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["_plan_loader"] = _mod
_spec.loader.exec_module(_mod)
