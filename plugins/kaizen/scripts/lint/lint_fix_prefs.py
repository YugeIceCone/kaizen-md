"""lint_fix_prefs — per-repo persistence of the chosen dispatch strategy.

Once the user picks subagent vs local_llm (+ optional model + base_url),
this writes `.kaizen/lint_dispatch_prefs.json` under the repo root. Any
subsequent `auto_fix_lint(...)` call inside the same repo honors the
saved choice unless the caller passes `strategy=` explicitly.

Schema (current = 1):
    {
      "schema_version": 1,
      "strategy":  "subagent" | "local_llm",
      "model":     str   (optional — local_llm only),
      "base_url":  str   (optional — local_llm only),
      "updated_at": <ISO-8601 UTC>
    }

Pure I/O — no LLM calls. Atomic write via tempfile + os.replace so a
crashing writer never leaves a partial JSON file.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PREFS_DIR_NAME  = ".kaizen"
PREFS_FILE_NAME = "lint_dispatch_prefs.json"
SCHEMA_VERSION  = 1
_VALID_STRATEGIES = ("subagent", "local_llm")

def _prefs_path(repo_root: str | Path) -> Path:
    return Path(repo_root) / PREFS_DIR_NAME / PREFS_FILE_NAME

def load_prefs(repo_root: str | Path) -> dict[str, Any]:
    """Return the saved prefs dict, or {} when the file doesn't exist /
    is unparseable. Never raises."""
    p = _prefs_path(repo_root)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

def save_prefs(repo_root: str | Path, data: dict[str, Any]) -> None:
    """Atomically write `data` (with schema_version + updated_at
    stamped) to the prefs file. Creates `.kaizen/` if missing."""
    dir_ = Path(repo_root) / PREFS_DIR_NAME
    dir_.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    body = json.dumps(payload, indent=2, sort_keys=True)

    # Atomic write: tempfile in same dir + os.replace
    fd, tmp = tempfile.mkstemp(prefix=".lint_dispatch_prefs.", suffix=".tmp",
                                  dir=str(dir_))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.replace(tmp, _prefs_path(repo_root))
    except Exception:
        # Best-effort cleanup; re-raise so the caller knows the write failed.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

def get_strategy(repo_root: str | Path, *, default: str = "subagent") -> str:
    data = load_prefs(repo_root)
    val = data.get("strategy")
    if val in _VALID_STRATEGIES:
        return val
    return default

def set_strategy(repo_root: str | Path, strategy: str) -> None:
    if strategy not in _VALID_STRATEGIES:
        raise ValueError(
            f"unknown strategy {strategy!r}; must be one of {_VALID_STRATEGIES}"
        )
    data = load_prefs(repo_root)
    data["strategy"] = strategy
    save_prefs(repo_root, data)

__all__ = [
    "load_prefs", "save_prefs", "get_strategy", "set_strategy",
    "PREFS_DIR_NAME", "PREFS_FILE_NAME", "SCHEMA_VERSION",
]
