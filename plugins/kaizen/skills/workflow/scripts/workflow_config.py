"""MIGRATION BRIDGE — workflow_config moved to scripts/workflow/workflow_config.py.

Bare ``import workflow_config`` still resolves here when callers have only
``skills/workflow/scripts/`` on ``sys.path``. Loads the canonical and
aliases ``sys.modules["workflow_config"]`` so legacy + canonical imports
return the SAME module object.

NOTE: this stub is for module-import callers. Direct script invocation
(``python3 skills/workflow/scripts/workflow_config.py``) does NOT trigger
the canonical's ``__main__`` block — script-style callers must point at
``scripts/workflow/workflow_config.py`` directly (bin/kaizen-workflow-config
already does).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_TARGET_DIR = _PLUGIN_ROOT / "scripts" / "workflow"
_CANONICAL = _TARGET_DIR / "workflow_config.py"

if str(_TARGET_DIR) not in sys.path:
    sys.path.insert(0, str(_TARGET_DIR))

_spec = importlib.util.spec_from_file_location("workflow_config", _CANONICAL)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["workflow_config"] = _mod
_spec.loader.exec_module(_mod)
