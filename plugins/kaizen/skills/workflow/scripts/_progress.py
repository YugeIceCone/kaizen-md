"""MIGRATION BRIDGE — _progress moved to scripts/io/_progress.py.

Pure progress-bar helper, no skill-specific knowledge — belongs with
the io utilities. Loads canonical via importlib + sys.modules alias.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_IO_DIR = _PLUGIN_ROOT / "scripts" / "io"
_LEGACY_DIR = _PLUGIN_ROOT / "skills" / "workflow" / "scripts"
_CANONICAL = _IO_DIR / "_progress.py"

for _p in (_LEGACY_DIR, _IO_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_spec = importlib.util.spec_from_file_location("_progress", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["_progress"] = _mod
_spec.loader.exec_module(_mod)
