"""MIGRATION BRIDGE — axis_runner moved to scripts/quality/axis_runner.py.

Bare ``import axis_runner`` still resolves here when callers have only
``skills/workflow/scripts/`` on ``sys.path``. This stub loads the
canonical module from ``scripts/quality/axis_runner.py`` and aliases
``sys.modules["axis_runner"]`` to it. Both legacy and canonical imports
return the SAME module object (no duplicate-module pitfall).

Migrated per BK-059 as part of the v1.40+ scripts/ consolidation:
the legacy mega-dir ``skills/workflow/scripts/`` is being thinned;
new axis modules live alongside their siblings in ``scripts/quality/``.

Remove once every consumer adopts its own
``sys.path.insert(<plugin>/scripts/quality)`` bridge.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_QUALITY_DIR = _PLUGIN_ROOT / "scripts" / "quality"
_LEGACY_DIR = _PLUGIN_ROOT / "skills" / "workflow" / "scripts"
_CANONICAL = _QUALITY_DIR / "axis_runner.py"

for _p in (_LEGACY_DIR, _QUALITY_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_spec = importlib.util.spec_from_file_location("axis_runner", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["axis_runner"] = _mod
_spec.loader.exec_module(_mod)
