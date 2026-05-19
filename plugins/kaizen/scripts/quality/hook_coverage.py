#!/usr/bin/env python3
"""kaizen-hook-coverage — every hooks/claude/*.sh MUST be referenced
in hooks/hooks.json so the runtime knows to fire it. Orphans (script
on disk, never wired) are dead code; missing scripts (wired but no
file) crash the hook system.

Stdlib only. Subcommands: report | gaps. Envelope output.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
# MIGRATION BRIDGE — legacy helpers still at skills/workflow/scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "workflow" / "scripts"))

import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-hook-coverage", tool_version="1.0.0")


def _plugin_root() -> Path:
    return _SCRIPT_DIR.parents[1]


def _hook_scripts_on_disk(hooks_dir: Path) -> list[Path]:
    return sorted(p for p in hooks_dir.glob("*.sh") if not p.name.startswith("_"))


def _hooks_wired(hooks_json: Path) -> set[str]:
    raw = json.loads(hooks_json.read_text(encoding="utf-8"))
    wired: set[str] = set()
    for _evt, entries in (raw.get("hooks") or {}).items():
        for e in entries:
            for h in (e.get("hooks") or []):
                cmd = h.get("command", "")
                for token in cmd.split():
                    if token.endswith(".sh"):
                        wired.add(Path(token).name)
    return wired


def scan(*, hooks_dir: Path, hooks_json: Path) -> dict:
    on_disk = _hook_scripts_on_disk(hooks_dir)
    wired = _hooks_wired(hooks_json)
    disk_names = {p.name for p in on_disk}
    orphans = sorted(disk_names - wired)
    missing = sorted(wired - disk_names)
    return {
        "scripts_on_disk": len(on_disk),
        "wired_entries":   len(wired),
        "orphans": [{"script": s} for s in orphans],
        "missing": [{"script": s} for s in missing],
        "gaps_total": len(orphans) + len(missing),
    }


def _run(args) -> int:
    rep = scan(hooks_dir=_plugin_root() / "hooks/claude",
                hooks_json=_plugin_root() / "hooks/hooks.json")
    gaps = rep["gaps_total"]
    verdict = "green" if gaps == 0 else ("yellow" if gaps <= 5 else "red")
    if args.cmd == "gaps" and not args.json:
        for o in rep["orphans"]:
            print(f"orphan {o['script']}")
        for m in rep["missing"]:
            print(f"missing {m['script']}")
        return 0 if gaps == 0 else 1
    _emit(rep, verdict=verdict, counts={"gaps": gaps})
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kaizen-hook-coverage",
        description="Audit hooks/hooks.json wiring of hooks/claude/*.sh.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("report", "gaps"):
        s = sub.add_parser(n)
        s.add_argument("--json", action="store_true")
        s.set_defaults(func=_run)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
