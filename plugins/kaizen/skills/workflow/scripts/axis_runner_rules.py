"""MIGRATION BRIDGE — axis_runner_rules moved to scripts/quality/.

Loads the canonical module from ``scripts/quality/axis_runner_rules.py``
and aliases ``sys.modules["axis_runner_rules"]`` so legacy + canonical
imports return the same object. See [[axis_runner.py]] for the full
migration rationale (BK-059).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_QUALITY_DIR = _PLUGIN_ROOT / "scripts" / "quality"
_LEGACY_DIR = _PLUGIN_ROOT / "skills" / "workflow" / "scripts"
_CANONICAL = _QUALITY_DIR / "axis_runner_rules.py"

for _p in (_LEGACY_DIR, _QUALITY_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_spec = importlib.util.spec_from_file_location("axis_runner_rules", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["axis_runner_rules"] = _mod
_spec.loader.exec_module(_mod)
