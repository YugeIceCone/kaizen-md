"""MIGRATION BRIDGE — _workflow_prefill moved to scripts/workflow/_workflow_prefill.py.

Bare ``import _workflow_prefill`` still resolves here. Direct script invocation
does NOT trigger ``__main__`` — script-style callers must point at
``scripts/workflow/_workflow_prefill.py`` directly.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_TARGET_DIR = _PLUGIN_ROOT / "scripts" / "workflow"
_CANONICAL = _TARGET_DIR / "_workflow_prefill.py"

if str(_TARGET_DIR) not in sys.path:
    sys.path.insert(0, str(_TARGET_DIR))

_spec = importlib.util.spec_from_file_location("_workflow_prefill", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["_workflow_prefill"] = _mod
_spec.loader.exec_module(_mod)
