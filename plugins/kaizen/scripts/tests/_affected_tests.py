#!/usr/bin/env python3
"""kaizen _affected_tests — derive affected test modules from staged files.

Powers pre-commit.sh's optional test-gate. Pure-function core + thin
stdin CLI; bash reads one line from stdout — either comma-separated
`tests.<stem>` module names, the literal `FULL` (run everything via
discovery), or empty (no Python impact — skip).

Subset rule:
  - Test files staged → those tests themselves.
  - Script `scripts/<x>.py` with matching `tests/test_<x>.py` → direct map.
  - Script with NO paired test → FULL (no safe subset).
  - Private helper (`_<x>.py`) → FULL (fan-out unknown).
  - No `.py` files staged → empty (skip).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

def _resolve_plugin_root() -> Path:
    """`KAIZEN_AFFECTED_PLUGIN_ROOT` overrides (used by tests); otherwise
    walk up from this script — it lives at <plugin>/scripts/tests/."""
    env = os.environ.get("KAIZEN_AFFECTED_PLUGIN_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2]

def derive_modules(staged_files: list[str], repo_root: Path,
                     plugin_root: Path) -> tuple[list[str], str]:
    """Derive affected test modules from a list of staged paths.

    Returns (modules, reason) where modules is either ["tests.test_*"]
    direct-mapped names, ["FULL"] (full-suite sentinel), or [] (skip).
    """
    if not staged_files:
        return [], "no files staged"

    py_files = [f for f in staged_files if f.endswith(".py")]
    if not py_files:
        return [], "no python files staged"

    tests_dir = plugin_root / "tests"
    modules: set[str] = set()

    for f in py_files:
        path = Path(f)
        stem = path.stem
        parts = path.parts

        # 1) A staged test file → run itself.
        if stem.startswith("test_") and "tests" in parts:
            modules.add(f"tests.{stem}")
            continue

        # 2) Private helper (filename begins with `_`) → fan-out unknown.
        if stem.startswith("_"):
            return ["FULL"], f"private helper changed ({path.name}) — full suite"

        # 3) Direct map: scripts/<x>.py → tests/test_<x>.py if it exists.
        candidate = tests_dir / f"test_{stem}.py"
        if candidate.is_file():
            modules.add(f"tests.test_{stem}")
            continue

        # 4) Unmapped script → no safe subset.
        return ["FULL"], f"no paired test for {path.name} — full suite"

    if not modules:
        return [], "no test impact derived"
    return sorted(modules), f"direct map ({len(modules)} module(s))"

def _read_staged() -> list[str]:
    """One path per line on stdin; CLI args also accepted as a convenience."""
    if len(sys.argv) > 1:
        return [a for a in sys.argv[1:] if a.strip()]
    return [line.strip() for line in sys.stdin if line.strip()]

def main() -> int:
    staged = _read_staged()
    plugin_root = _resolve_plugin_root()
    modules, reason = derive_modules(
        staged_files=staged,
        repo_root=Path.cwd(),
        plugin_root=plugin_root,
    )
    if modules:
        # Single line, comma-sep — bash splits on it directly.
        sys.stdout.write(",".join(modules) + "\n")
    # Reason goes to stderr so bash can surface it without contaminating
    # the parseable stdout.
    sys.stderr.write(f"[_affected_tests] {reason}\n")
    return 0

if __name__ == "__main__":
    sys.exit(main())
