"""MIGRATION BRIDGE — karpathy _loader moved to scripts/karpathy/_loader.py.

Application-layer loader migrated alongside the karpathy scanner scripts
(complexity_checker / diff_surgeon / etc.) per the v1.40+ consolidation.
Domain yaml stays at skills/karpathy/domain/.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_KARPATHY_DIR = _PLUGIN_ROOT / "scripts" / "karpathy"
_LEGACY_DIR = _PLUGIN_ROOT / "skills" / "karpathy" / "application"
_CANONICAL = _KARPATHY_DIR / "_loader.py"

for _p in (_LEGACY_DIR, _KARPATHY_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_spec = importlib.util.spec_from_file_location("_loader", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["_loader"] = _mod
_spec.loader.exec_module(_mod)
