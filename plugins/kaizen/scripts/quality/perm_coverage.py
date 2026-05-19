#!/usr/bin/env python3
"""kaizen-perm-coverage — every argparse-main script under
skills/workflow/scripts/ MUST have a matching plugin.json
`permissions.allow` entry, else `Bash(python3 ... <script>:*)` will
trigger a runtime prompt for the user.

This audits existing coverage. The iron-law `plugin-manifest-permissions`
catches the gap for net-new scripts in pre-commit; this catches the
historical gaps a one-time audit needs.

Subcommands: report | gaps. Stdlib only. Output: canonical envelope.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
# MIGRATION BRIDGE — legacy helpers still at skills/workflow/scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "workflow" / "scripts"))

import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-perm-coverage", tool_version="1.0.0")


def _plugin_root() -> Path:
    return _SCRIPT_DIR.parents[1]


_ARGPARSE_RE = re.compile(r"\bargparse\.ArgumentParser\b|\bimport argparse\b")


def _argparse_main_scripts(scripts_dir: Path) -> list[Path]:
    """Scan scripts_dir (skills/workflow/scripts/) AND the post-DOMAIN
    scripts/ tree recursively for argparse-main scripts."""
    candidates: list[Path] = []
    if scripts_dir.is_dir():
        candidates += sorted(scripts_dir.glob("*.py"))
    # Post-DOMAIN scripts/ — recursive walk for nested subdirs.
    new_scripts = scripts_dir.parents[2] / "scripts"
    if new_scripts.is_dir():
        candidates += sorted(p for p in new_scripts.rglob("*.py")
                              if "__pycache__" not in p.parts)
    out: list[Path] = []
    for p in candidates:
        if p.name.startswith("_"):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        if "__main__" in text and _ARGPARSE_RE.search(text):
            out.append(p)
    return out


def _perm_index(plugin_json: Path) -> list[str]:
    raw = json.loads(plugin_json.read_text(encoding="utf-8"))
    return list(raw.get("permissions", {}).get("allow", []))


def _has_perm(script_name: str, perm_index: list[str]) -> bool:
    bin_name = "kaizen-" + script_name.removesuffix(".py").replace("_", "-")
    for entry in perm_index:
        if script_name in entry or bin_name in entry:
            return True
    return False


def scan(*, scripts_dir: Path, plugin_json: Path) -> dict:
    scripts = _argparse_main_scripts(scripts_dir)
    idx = _perm_index(plugin_json)
    gaps = [
        {"script": s.name, "path": str(s.relative_to(_plugin_root()))}
        for s in scripts if not _has_perm(s.name, idx)
    ]
    return {
        "scripts_total": len(scripts),
        "perm_entries":  len(idx),
        "gaps":          gaps,
        "coverage_pct":  round(
            100.0 * (len(scripts) - len(gaps)) / max(len(scripts), 1), 2,
        ),
    }


def _cmd_report(args) -> int:
    rep = scan(scripts_dir=_plugin_root() / "skills/workflow/scripts",
                plugin_json=_plugin_root() / ".claude-plugin/plugin.json")
    verdict = "green" if not rep["gaps"] else ("yellow" if len(rep["gaps"]) <= 5 else "red")
    _emit(rep, verdict=verdict, counts={"gaps": len(rep["gaps"])})
    return 0


def _cmd_gaps(args) -> int:
    rep = scan(scripts_dir=_plugin_root() / "skills/workflow/scripts",
                plugin_json=_plugin_root() / ".claude-plugin/plugin.json")
    if args.json:
        _emit({"gaps": rep["gaps"]},
              verdict="green" if not rep["gaps"] else "yellow",
              counts={"gaps": len(rep["gaps"])})
    else:
        for g in rep["gaps"]:
            print(g["path"])
    return 0 if not rep["gaps"] else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kaizen-perm-coverage",
        description="Audit plugin.json perm coverage of argparse-main scripts.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report", help="Full report (envelope).")
    r.set_defaults(func=_cmd_report)
    g = sub.add_parser("gaps", help="List scripts missing perm entries.")
    g.add_argument("--json", action="store_true")
    g.set_defaults(func=_cmd_gaps)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
