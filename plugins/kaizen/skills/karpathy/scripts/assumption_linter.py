"""MIGRATION BRIDGE — assumption_linter moved to scripts/karpathy/.

See [[complexity_checker.py]] for the full migration rationale.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_KARPATHY_DIR = _PLUGIN_ROOT / "scripts" / "karpathy"
_LEGACY_DIR = _PLUGIN_ROOT / "skills" / "karpathy" / "scripts"
_CANONICAL = _KARPATHY_DIR / "assumption_linter.py"

for _p in (_LEGACY_DIR, _KARPATHY_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_spec = importlib.util.spec_from_file_location("assumption_linter", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["assumption_linter"] = _mod
_spec.loader.exec_module(_mod)
