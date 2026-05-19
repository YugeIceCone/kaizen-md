"""kaizen-migrate — consolidated data-migrator parent.

Tier-2 consolidation. Dispatches the two layout-version migrators
under one bin wrapper:

::

   kaizen-migrate path  <args>   →  path_migrate.py (v1.38 → v1.39 layout)
   kaizen-migrate legacy <args>  →  migrate_paths.sh (v1.21 → v1.22 layout)

Each underlying script declares ``# consolidated-cli-parent: migrate``
so the iron-law ``bin-wrapper-per-cli`` is satisfied without separate
``kaizen-path-migrate`` / ``kaizen-migrate-paths`` wrappers.

Brain data migration stays single-surface under ``kaizen-brain migrate``
(intentionally not exposed here — see commit answer 3 of the Tier-2
plan; the brain CLI is the canonical entry point for brain-scoped ops).

Code-lift (the X4 import-rewrite engine, formerly ``_migrate.py``)
moved to ``kaizen-code-lift`` in commit A — different concern.

The dispatcher uses ``os.execvp`` so the child process replaces this
one cleanly (no shell layer, no argv re-escaping, child's exit code
becomes our exit code).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent


# verb → (interpreter, script path) — the dispatch table.
_DISPATCH: dict[str, tuple[str, Path]] = {
    "path":   ("python3", _SCRIPT_DIR / "path_migrate.py"),
    "legacy": ("bash",    _SCRIPT_DIR / "migrate_paths.sh"),
}


_USAGE = """\
usage: kaizen-migrate <verb> [args...]

Verbs:
  path     v1.38 → v1.39 layout restructure (path_migrate.py)
           Subcommands: status | dry-run | apply | rollback

  legacy   v1.21 → v1.22 layout move (migrate_paths.sh)
           Flags: --dry-run | --force | --user-only | --project-only |
                  --project-root <path>

Notes:
  - For brain data migration, use `kaizen-brain migrate apply`.
  - For code-lift / import rewrites, use `kaizen-code-lift`.
"""


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help"):
        sys.stdout.write(_USAGE)
        return 0 if argv else 2

    verb, *rest = argv
    if verb not in _DISPATCH:
        sys.stderr.write(
            f"kaizen-migrate: unknown verb {verb!r}\n"
            f"  expected one of: {', '.join(_DISPATCH)}\n"
            f"  see `kaizen-migrate --help`\n"
        )
        return 2

    interpreter, script = _DISPATCH[verb]
    if not script.exists():
        sys.stderr.write(
            f"kaizen-migrate: dispatch target missing: {script}\n"
            f"  (this is a packaging bug — file an issue)\n"
        )
        return 2

    # execvp replaces this process; the child's exit code becomes ours.
    # rest may be empty (e.g. `kaizen-migrate path` for the path-migrate
    # default behavior); pass it through verbatim.
    os.execvp(interpreter, [interpreter, str(script), *rest])
    # Unreachable; execvp either succeeds (no return) or raises.
    return 0  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
