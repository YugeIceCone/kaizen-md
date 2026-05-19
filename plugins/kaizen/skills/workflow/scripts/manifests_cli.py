"""MIGRATION BRIDGE — manifests_cli moved to scripts/workflow/manifests_cli.py.

Bare ``import manifests_cli`` still resolves here. Direct script invocation
does NOT trigger ``__main__`` — script-style callers must point at
``scripts/workflow/manifests_cli.py`` directly (bin/kaizen-manifests does).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_TARGET_DIR = _PLUGIN_ROOT / "scripts" / "workflow"
_CANONICAL = _TARGET_DIR / "manifests_cli.py"

if str(_TARGET_DIR) not in sys.path:
    sys.path.insert(0, str(_TARGET_DIR))

_spec = importlib.util.spec_from_file_location("manifests_cli", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["manifests_cli"] = _mod
_spec.loader.exec_module(_mod)
