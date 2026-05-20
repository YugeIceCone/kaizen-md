"""MIGRATION BRIDGE — intake moved to scripts/plugin_development/intake.py.

See [[validate.py]] for the full migration rationale.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_PD_DIR = _PLUGIN_ROOT / "scripts" / "plugin_development"
_LEGACY_DIR = _PLUGIN_ROOT / "skills" / "plugin-development" / "scripts"
_CANONICAL = _PD_DIR / "intake.py"

for _p in (_LEGACY_DIR, _PD_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_spec = importlib.util.spec_from_file_location("intake", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["intake"] = _mod
_spec.loader.exec_module(_mod)

if __name__ == "__main__":
    if hasattr(_mod, "main"):
        raise SystemExit(_mod.main())
