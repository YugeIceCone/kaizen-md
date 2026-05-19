#!/usr/bin/env python3
"""kaizen-schema-load-coverage — every `*.schema.json` under
`skills/*/domain/schemas/` must be referenced by basename from at
least one `.py` under `skills/workflow/scripts/`. Orphans are dead
schemas (declared but never validated against).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
# MIGRATION BRIDGE — legacy helpers still at skills/workflow/scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "workflow" / "scripts"))

import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-schema-load-coverage", tool_version="1.0.0")


def _plugin_root_default() -> Path:
    return _SCRIPT_DIR.parents[1]


def scan(*, plugin_root: Path) -> dict:
    schemas = sorted(plugin_root.glob("skills/*/domain/schemas/*.json"))
    py_blob = ""
    scripts_dir = plugin_root / "skills/workflow/scripts"
    if scripts_dir.is_dir():
        for p in scripts_dir.glob("*.py"):
            try:
                py_blob += p.read_text(encoding="utf-8")
            except OSError:
                pass
    gaps = []
    for s in schemas:
        if s.name not in py_blob:
            gaps.append({"schema": s.name,
                          "path": str(s.relative_to(plugin_root))})
    return {
        "schemas_total": len(schemas),
        "gaps":          gaps,
        "coverage_pct":  round(
            100.0 * (len(schemas) - len(gaps)) / max(len(schemas), 1), 2,
        ),
    }


def _run(args) -> int:
    rep = scan(plugin_root=_plugin_root_default())
    n = len(rep["gaps"])
    verdict = "green" if n == 0 else ("yellow" if n <= 5 else "red")
    if args.cmd == "gaps" and not args.json:
        for g in rep["gaps"]:
            print(g["path"])
        return 0 if n == 0 else 1
    _emit(rep, verdict=verdict, counts={"gaps": n})
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kaizen-schema-load-coverage",
        description="Audit schema files referenced by loaders.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("report", "gaps"):
        s = sub.add_parser(n)
        s.add_argument("--json", action="store_true")
        s.set_defaults(func=_run)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
