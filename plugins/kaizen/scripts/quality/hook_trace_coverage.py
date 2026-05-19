#!/usr/bin/env python3
"""kaizen-hook-trace-coverage — every hooks/claude/*.sh script MUST
reference `_trace.sh` so each fire is observable in the trace log.

Iron-law `every_hook_script_traces_its_firing` covers this at pre-commit
for net-new scripts; this audits the historical surface.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
# MIGRATION BRIDGE — legacy helpers still at skills/workflow/scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "io"))

import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-hook-trace-coverage", tool_version="1.0.0")


def _plugin_root() -> Path:
    return _SCRIPT_DIR.parents[1]


def scan(*, hooks_dir: Path) -> dict:
    if not hooks_dir.is_dir():
        return {"hooks_total": 0, "gaps": [], "coverage_pct": 100.0}
    scripts = sorted(p for p in hooks_dir.glob("*.sh") if not p.name.startswith("_"))
    gaps = []
    for s in scripts:
        try:
            text = s.read_text(encoding="utf-8")
        except OSError:
            continue
        if "_trace.sh" not in text:
            gaps.append({"script": s.name})
    return {
        "hooks_total":  len(scripts),
        "gaps":         gaps,
        "coverage_pct": round(
            100.0 * (len(scripts) - len(gaps)) / max(len(scripts), 1), 2,
        ),
    }


def _run(args) -> int:
    rep = scan(hooks_dir=_plugin_root() / "hooks/claude")
    n = len(rep["gaps"])
    verdict = "green" if n == 0 else ("yellow" if n <= 5 else "red")
    if args.cmd == "gaps" and not args.json:
        for g in rep["gaps"]:
            print(g["script"])
        return 0 if n == 0 else 1
    _emit(rep, verdict=verdict, counts={"gaps": n})
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kaizen-hook-trace-coverage",
        description="Audit hooks/claude/*.sh for _trace.sh emission.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("report", "gaps"):
        s = sub.add_parser(n)
        s.add_argument("--json", action="store_true")
        s.set_defaults(func=_run)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
