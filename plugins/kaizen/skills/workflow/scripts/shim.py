"""MIGRATION BRIDGE — shim moved to scripts/iron-laws/shim.py."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_TARGET_DIR = _PLUGIN_ROOT / "scripts" / "iron-laws"
_CANONICAL = _TARGET_DIR / "shim.py"

if str(_TARGET_DIR) not in sys.path:
    sys.path.insert(0, str(_TARGET_DIR))

_spec = importlib.util.spec_from_file_location("shim", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["shim"] = _mod
_spec.loader.exec_module(_mod)
