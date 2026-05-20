"""Add every plugins/kaizen/scripts/<cluster>/ dir to sys.path.

Production-code counterpart of tests/_kaizen_paths.py. Used by scripts
that import cross-cluster siblings (e.g. brain.py imports `flow` from
the workflow cluster, posttooluse_trace.py imports `trace` from the
observe cluster).

Usage:

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import _bootstrap  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path

The first line lets Python find this module (scripts/ isn't a package).
The import has the sys.path side-effect; idempotent + stdlib-only.

Replaces the pre-DOMAIN-shells idiom
    sys.path.insert(0, ... / "skills" / "workflow" / "scripts")
which relied on 116 MIGRATION BRIDGE shims now retired.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_ROOT = Path(__file__).resolve().parent

for _cluster in sorted(_SCRIPTS_ROOT.iterdir()):
    if not _cluster.is_dir() or _cluster.name == "__pycache__":
        continue
    _entry = str(_cluster)
    if _entry not in sys.path:
        sys.path.insert(0, _entry)
