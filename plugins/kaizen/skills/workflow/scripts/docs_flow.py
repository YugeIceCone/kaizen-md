"""MIGRATION BRIDGE — docs_flow moved to scripts/index/docs_flow.py.

Loads canonical + aliases sys.modules["docs_flow"] so legacy + canonical
imports return the SAME module object.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_INDEX_DIR = _PLUGIN_ROOT / "scripts" / "index"
_CANONICAL = _INDEX_DIR / "docs_flow.py"

if str(_INDEX_DIR) not in sys.path:
    sys.path.insert(0, str(_INDEX_DIR))

_spec = importlib.util.spec_from_file_location("docs_flow", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["docs_flow"] = _mod
_spec.loader.exec_module(_mod)
