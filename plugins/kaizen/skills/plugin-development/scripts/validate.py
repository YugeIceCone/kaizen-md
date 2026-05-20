"""MIGRATION BRIDGE — validate moved to scripts/plugin_development/validate.py.

Domain yaml (intake-checklist.yaml, iron-laws.yaml refs, schemas/)
stays with the skill at ``skills/plugin-development/``; only the
Python adapter migrated to ``scripts/plugin_development/`` as part of
the v1.40+ consolidation that drains skills/<feature>/scripts/.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_PD_DIR = _PLUGIN_ROOT / "scripts" / "plugin_development"
_LEGACY_DIR = _PLUGIN_ROOT / "skills" / "plugin-development" / "scripts"
_CANONICAL = _PD_DIR / "validate.py"

for _p in (_LEGACY_DIR, _PD_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_spec = importlib.util.spec_from_file_location("validate", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["validate"] = _mod
_spec.loader.exec_module(_mod)

# Allow `python3 skills/plugin-development/scripts/validate.py ...` to
# still work — when invoked as __main__, hand off to the canonical's main.
if __name__ == "__main__":
    if hasattr(_mod, "main"):
        raise SystemExit(_mod.main())
