"""Add every plugins/kaizen/scripts/<cluster>/ dir to sys.path.

Test helper. Replaces the pre-DOMAIN-shells idiom
    sys.path.insert(0, str(plugin_root / "skills/workflow/scripts"))
which relied on 116 MIGRATION BRIDGE shims to forward bare imports to
the canonical scripts/<cluster>/ locations. With this helper on
sys.path, `import <name>` resolves directly to the canonical module
without any bridge.

Usage in a test file (replaces the old `sys.path.insert(skills/workflow/scripts)`):

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _kaizen_paths  # noqa: F401, E402 — adds scripts/<cluster>/ to sys.path

The first line lets Python find this module (tests/ isn't a package).
The import has the sys.path side-effect; it is idempotent + stdlib-only.
"""
from __future__ import annotations

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_PLUGIN_ROOT = _TESTS_DIR.parent
_SCRIPTS_ROOT = _PLUGIN_ROOT / "scripts"

if not _SCRIPTS_ROOT.is_dir():  # pragma: no cover — install-time invariant
    raise RuntimeError(f"_kaizen_paths: scripts root not found at {_SCRIPTS_ROOT}")

for _cluster in sorted(_SCRIPTS_ROOT.iterdir()):
    if not _cluster.is_dir() or _cluster.name == "__pycache__":
        continue
    _entry = str(_cluster)
    if _entry not in sys.path:
        sys.path.insert(0, _entry)
