#!/usr/bin/env python3
"""kaizen-bin-coverage — every argparse-main script under
skills/workflow/scripts/ MUST have a matching bin/ wrapper (symlink
or shell stub). Mirrors the iron-law `bin-wrapper-per-cli` as a
standalone audit for the existing surface.

Naming convention: `kaizen-<name>` where <name> is the script name
without `.py` and with `_` → `-`. `kaizen-foo` may symlink to either
foo.py OR _foo.py (consolidated-cli-parent pattern). Stdlib only.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
# MIGRATION BRIDGE — legacy helpers still at skills/workflow/scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "io"))

import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-bin-coverage", tool_version="1.0.0")
_ARGPARSE_RE = re.compile(r"\bargparse\.ArgumentParser\b|\bimport argparse\b")


def _plugin_root() -> Path:
    return _SCRIPT_DIR.parents[1]


def _argparse_main_scripts(scripts_dir: Path) -> list[Path]:
    out: list[Path] = []
    for p in sorted(scripts_dir.glob("*.py")):
        if p.name.startswith("_"):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        if "__main__" in text and _ARGPARSE_RE.search(text):
            out.append(p)
    return out


def _bin_names(bin_dir: Path) -> set[str]:
    if not bin_dir.is_dir():
        return set()
    return {p.name for p in bin_dir.iterdir()}


def _expected_bin(script_name: str) -> str:
    return "kaizen-" + script_name.removesuffix(".py").replace("_", "-")


def scan(*, scripts_dir: Path, bin_dir: Path) -> dict:
    scripts = _argparse_main_scripts(scripts_dir)
    bins = _bin_names(bin_dir)
    gaps = []
    for s in scripts:
        expected = _expected_bin(s.name)
        if expected not in bins:
            gaps.append({"script": s.name, "expected_bin": expected})
    return {
        "scripts_total": len(scripts),
        "bin_entries":   len(bins),
        "gaps":          gaps,
        "coverage_pct":  round(
            100.0 * (len(scripts) - len(gaps)) / max(len(scripts), 1), 2,
        ),
    }


def _run(args) -> int:
    rep = scan(scripts_dir=_plugin_root() / "skills/workflow/scripts",
                bin_dir=_plugin_root() / "bin")
    verdict = "green" if not rep["gaps"] else ("yellow" if len(rep["gaps"]) <= 5 else "red")
    if args.cmd == "gaps" and not args.json:
        for g in rep["gaps"]:
            print(f"{g['script']} → expected bin/{g['expected_bin']}")
        return 0 if not rep["gaps"] else 1
    _emit(rep, verdict=verdict, counts={"gaps": len(rep["gaps"])})
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kaizen-bin-coverage",
        description="Audit bin/ wrapper coverage of argparse-main scripts.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("report", "gaps"):
        s = sub.add_parser(n)
        s.add_argument("--json", action="store_true")
        s.set_defaults(func=_run)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
