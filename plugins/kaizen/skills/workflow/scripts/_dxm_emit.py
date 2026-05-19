"""MIGRATION BRIDGE — _dxm_emit moved to scripts/observe/_dxm_emit.py."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_TARGET_DIR = _PLUGIN_ROOT / "scripts" / "observe"
_CANONICAL = _TARGET_DIR / "_dxm_emit.py"

if str(_TARGET_DIR) not in sys.path:
    sys.path.insert(0, str(_TARGET_DIR))

_spec = importlib.util.spec_from_file_location("_dxm_emit", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["_dxm_emit"] = _mod
_spec.loader.exec_module(_mod)
