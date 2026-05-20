"""MIGRATION BRIDGE — complexity_checker moved to scripts/karpathy/.

Loads the canonical module from ``scripts/karpathy/complexity_checker.py``
and aliases ``sys.modules["complexity_checker"]``. Migrated as part of
the v1.40+ consolidation that drains skills/<feature>/scripts/ into
scripts/<feature>/.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_KARPATHY_DIR = _PLUGIN_ROOT / "scripts" / "karpathy"
_LEGACY_DIR = _PLUGIN_ROOT / "skills" / "karpathy" / "scripts"
_CANONICAL = _KARPATHY_DIR / "complexity_checker.py"

for _p in (_LEGACY_DIR, _KARPATHY_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_spec = importlib.util.spec_from_file_location("complexity_checker", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["complexity_checker"] = _mod
_spec.loader.exec_module(_mod)
