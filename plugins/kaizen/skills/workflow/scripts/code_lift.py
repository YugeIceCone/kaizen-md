"""MIGRATION BRIDGE — code_lift moved to scripts/util/code_lift.py."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_TARGET_DIR = _PLUGIN_ROOT / "scripts" / "util"
_CANONICAL = _TARGET_DIR / "code_lift.py"

if str(_TARGET_DIR) not in sys.path:
    sys.path.insert(0, str(_TARGET_DIR))

_spec = importlib.util.spec_from_file_location("code_lift", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["code_lift"] = _mod
_spec.loader.exec_module(_mod)
