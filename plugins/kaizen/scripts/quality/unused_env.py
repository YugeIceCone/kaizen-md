#!/usr/bin/env python3
"""kaizen-unused-env — env-vars declared in .kaizen.toml (or env files)
but never referenced from any .py under skills/workflow/scripts/.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
# MIGRATION BRIDGE — legacy helpers still at skills/workflow/scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "workflow" / "scripts"))

import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-unused-env", tool_version="1.0.0")
_TOML_RE = re.compile(r'^\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*"([A-Z_][A-Z0-9_]+)"', re.MULTILINE)


def _plugin_root() -> Path:
    return _SCRIPT_DIR.parents[1]


def _declared_env_vars(repo_root: Path) -> set[str]:
    out: set[str] = set()
    toml = repo_root / ".kaizen.toml"
    if toml.is_file():
        try:
            out.update(_TOML_RE.findall(toml.read_text(encoding="utf-8")))
        except OSError:
            pass
    return out


def _all_python_blob(repo_root: Path) -> str:
    text = ""
    sd = repo_root / "skills/workflow/scripts"
    if sd.is_dir():
        for p in sd.glob("*.py"):
            try:
                text += p.read_text(encoding="utf-8")
            except OSError:
                pass
    return text


def scan(*, repo_root: Path) -> dict:
    declared = _declared_env_vars(repo_root)
    blob = _all_python_blob(repo_root)
    gaps = [{"env_var": v} for v in sorted(declared) if v not in blob]
    return {
        "declared_total": len(declared),
        "gaps":           gaps,
        "coverage_pct":   round(
            100.0 * (len(declared) - len(gaps)) / max(len(declared), 1), 2,
        ),
    }


def _run(args) -> int:
    rep = scan(repo_root=_plugin_root())
    n = len(rep["gaps"])
    verdict = "green" if n == 0 else ("yellow" if n <= 5 else "red")
    if args.cmd == "gaps" and not args.json:
        for g in rep["gaps"]:
            print(g["env_var"])
        return 0 if n == 0 else 1
    _emit(rep, verdict=verdict, counts={"gaps": n})
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kaizen-unused-env",
        description="Env-vars declared but never read.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("report", "gaps"):
        s = sub.add_parser(n)
        s.add_argument("--json", action="store_true")
        s.set_defaults(func=_run)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
