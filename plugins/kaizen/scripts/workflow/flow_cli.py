"""kaizen-flow — consolidated flow-family parent.

Tier-2 commit C. Dispatches the four flow-shaped CLIs under one
bin wrapper:

::

   kaizen-flow demo   <args>  →  flow.py        (async Node+Flow reference pipeline)
   kaizen-flow docs   <args>  →  docs_flow.py   (per-package docs pipeline)
   kaizen-flow index  <args>  →  index_flow.py  (semantic-index orchestrator)
   kaizen-flow search <args>  →  search_flow.py (semantic-search orchestrator)

The four underlying scripts each declare
``# consolidated-cli-parent: flow`` so the iron-law
``bin-wrapper-per-cli`` is satisfied without separate
``kaizen-docs-flow`` / ``kaizen-index-flow`` / ``kaizen-search-flow``
wrappers (those were dropped in this commit).

``flow.py`` stays unchanged as a library — it's imported by ~20
consumer modules. Its ``__main__`` block (the demo pipeline) is
addressable via ``kaizen-flow demo`` here.

``index_flow.py`` and ``search_flow.py`` are PEP-723 ``uv run --script``
shebang scripts (heavy deps: sentence-transformers, torch). The
dispatcher routes them through ``uv run --script`` so first-run venv
provisioning works.

``os.execvp`` hands off cleanly; the child's exit code becomes ours.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent

# verb → (interpreter_argv_prefix, script path). The prefix is a
# tuple so `uv run --script <path>` can be expressed as multiple argv
# elements (the dispatcher concats: prefix + [str(script)] + rest).
# *_flow.py siblings live under scripts/index/ (post-DOMAIN-10).
_INDEX_DIR = _SCRIPT_DIR.parent / "index"

_DISPATCH: dict[str, tuple[tuple[str, ...], Path]] = {
    "demo":   (("python3",),                _SCRIPT_DIR / "flow.py"),
    "docs":   (("python3",),                _INDEX_DIR / "docs_flow.py"),
    "index":  (("uv", "run", "--script"),   _INDEX_DIR / "index_flow.py"),
    "search": (("uv", "run", "--script"),   _INDEX_DIR / "search_flow.py"),
}

_USAGE = """\
usage: kaizen-flow <verb> [args...]

Verbs:
  demo     async Node+Flow reference pipeline over a workspace
           (flow.py — the canonical engine example)
  docs     per-package documentation pipeline
           (docs_flow.py — pocketflow-shaped fan-out)
  index    semantic-index orchestrator
           (index_flow.py — sentence-transformers, uv-managed venv)
  search   semantic-search orchestrator
           (search_flow.py — sentence-transformers, uv-managed venv)

Each verb passes through unmodified to the underlying script's CLI.
For per-verb help, use:  kaizen-flow <verb> --help
"""

def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help"):
        sys.stdout.write(_USAGE)
        return 0 if argv else 2

    verb, *rest = argv
    if verb not in _DISPATCH:
        sys.stderr.write(
            f"kaizen-flow: unknown verb {verb!r}\n"
            f"  expected one of: {', '.join(_DISPATCH)}\n"
            f"  see `kaizen-flow --help`\n"
        )
        return 2

    prefix, script = _DISPATCH[verb]
    if not script.exists():
        sys.stderr.write(
            f"kaizen-flow: dispatch target missing: {script}\n"
            f"  (this is a packaging bug — file an issue)\n"
        )
        return 2

    # The first element is the interpreter binary for execvp lookup;
    # subsequent elements include any interpreter flags ("run", "--script"
    # for uv) plus the script path and forwarded args.
    interpreter = prefix[0]
    os.execvp(interpreter, [*prefix, str(script), *rest])
    # Unreachable; execvp either succeeds (no return) or raises.
    return 0  # pragma: no cover

if __name__ == "__main__":
    raise SystemExit(main())
