"""MIGRATION BRIDGE — _reporter moved to scripts/audit/_reporter.py.

Domain yaml + JSON schemas stay with the skill; only the .py adapter
migrated as part of the v1.40+ scripts/<feature>/ consolidation.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_CANON_DIR = _PLUGIN_ROOT / "scripts/audit"
_LEGACY_DIR = Path(__file__).resolve().parent
_CANONICAL = _CANON_DIR / "_reporter.py"

for _p in (_LEGACY_DIR, _CANON_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_spec = importlib.util.spec_from_file_location("_reporter", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["_reporter"] = _mod
_spec.loader.exec_module(_mod)
