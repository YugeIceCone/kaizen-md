"""MIGRATION BRIDGE — drift_cli moved to scripts/iron-laws/drift_cli.py."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_TARGET_DIR = _PLUGIN_ROOT / "scripts" / "iron-laws"
_CANONICAL = _TARGET_DIR / "drift_cli.py"

if str(_TARGET_DIR) not in sys.path:
    sys.path.insert(0, str(_TARGET_DIR))

_spec = importlib.util.spec_from_file_location("drift_cli", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["drift_cli"] = _mod
_spec.loader.exec_module(_mod)
