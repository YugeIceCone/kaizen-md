"""MIGRATION BRIDGE — _manifests moved to scripts/workflow/_manifests.py.

Bare ``import _manifests`` still resolves here. This is a library module
(no __main__), so the shim is module-import only.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_TARGET_DIR = _PLUGIN_ROOT / "scripts" / "workflow"
_CANONICAL = _TARGET_DIR / "_manifests.py"

if str(_TARGET_DIR) not in sys.path:
    sys.path.insert(0, str(_TARGET_DIR))

_spec = importlib.util.spec_from_file_location("_manifests", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["_manifests"] = _mod
_spec.loader.exec_module(_mod)
