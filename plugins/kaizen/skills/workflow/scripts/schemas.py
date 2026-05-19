"""MIGRATION BRIDGE — schemas moved to scripts/workflow/schemas.py.

Bare ``import schemas`` still resolves here. Library module — module-import only.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_TARGET_DIR = _PLUGIN_ROOT / "scripts" / "workflow"
_CANONICAL = _TARGET_DIR / "schemas.py"

if str(_TARGET_DIR) not in sys.path:
    sys.path.insert(0, str(_TARGET_DIR))

_spec = importlib.util.spec_from_file_location("schemas", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["schemas"] = _mod
_spec.loader.exec_module(_mod)
