"""MIGRATION BRIDGE — plugin_docs moved to scripts/index/plugin_docs.py.

Loads canonical + aliases sys.modules["plugin_docs"] so legacy + canonical
imports return the SAME module object.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_INDEX_DIR = _PLUGIN_ROOT / "scripts" / "index"
_CANONICAL = _INDEX_DIR / "plugin_docs.py"

if str(_INDEX_DIR) not in sys.path:
    sys.path.insert(0, str(_INDEX_DIR))

_spec = importlib.util.spec_from_file_location("plugin_docs", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["plugin_docs"] = _mod
_spec.loader.exec_module(_mod)
