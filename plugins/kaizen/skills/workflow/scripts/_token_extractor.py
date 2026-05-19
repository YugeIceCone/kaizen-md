"""MIGRATION BRIDGE — _token_extractor moved to scripts/index/_token_extractor.py.

Loads canonical + aliases sys.modules["_token_extractor"] so legacy + canonical
imports return the SAME module object.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_INDEX_DIR = _PLUGIN_ROOT / "scripts" / "index"
_CANONICAL = _INDEX_DIR / "_token_extractor.py"

if str(_INDEX_DIR) not in sys.path:
    sys.path.insert(0, str(_INDEX_DIR))

_spec = importlib.util.spec_from_file_location("_token_extractor", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["_token_extractor"] = _mod
_spec.loader.exec_module(_mod)
