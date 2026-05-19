"""MIGRATION BRIDGE — _search moved to scripts/index/_search.py.

Loads canonical + aliases sys.modules["_search"] so legacy + canonical
imports return the SAME module object.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_INDEX_DIR = _PLUGIN_ROOT / "scripts" / "index"
_CANONICAL = _INDEX_DIR / "_search.py"

if str(_INDEX_DIR) not in sys.path:
    sys.path.insert(0, str(_INDEX_DIR))

_spec = importlib.util.spec_from_file_location("_search", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["_search"] = _mod
_spec.loader.exec_module(_mod)
