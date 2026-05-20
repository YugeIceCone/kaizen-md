"""MIGRATION BRIDGE — codegen moved to scripts/self_improving/brain_codegen.py.

Flattened from the originally-migrated scripts/self_improving/brain/codegen.py
(no nested subdirs in scripts/<feature>/ per kaizen convention).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_CANON_DIR = _PLUGIN_ROOT / "scripts" / "self_improving"
_LEGACY_DIR = Path(__file__).resolve().parent
_CANONICAL = _CANON_DIR / "brain_codegen.py"

for _p in (_LEGACY_DIR, _CANON_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_spec = importlib.util.spec_from_file_location("codegen", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["codegen"] = _mod
_spec.loader.exec_module(_mod)
