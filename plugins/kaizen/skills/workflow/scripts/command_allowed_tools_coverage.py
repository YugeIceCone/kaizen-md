#!/usr/bin/env python3
"""kaizen-command-allowed-tools-coverage — every commands/*.md that
invokes tools (bash, AskUserQuestion, MCP) should declare them in
frontmatter `allowed-tools:` so Claude Code knows the surface.

Heuristics — a command "invokes tools" when its body OR frontmatter
mentions any of:
  - `bash` / `Bash(...)` / argparse references
  - `AskUserQuestion`
  - `mcp__` (MCP tool prefix)
  - `kaizen-*` bin invocations
  - `python3 ${CLAUDE_PLUGIN_ROOT}/...`

If the command invokes tools but has no `allowed-tools:` key, that's
a gap. Stdlib only.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-command-allowed-tools-coverage",
                              tool_version="1.0.0")
_FM_RE = re.compile(r"\A---\n(.*?)\n---", re.DOTALL)
_ALLOWED_RE = re.compile(r"^allowed-tools:", re.MULTILINE)
_TOOL_SIGNALS = (
    re.compile(r"\bBash\(", re.IGNORECASE),
    re.compile(r"AskUserQuestion"),
    re.compile(r"\bmcp__"),
    re.compile(r"kaizen-[a-z][a-z0-9-]*", re.IGNORECASE),
    re.compile(r"python3 \$\{CLAUDE_PLUGIN_ROOT\}"),
)


def _plugin_root() -> Path:
    return _SCRIPT_DIR.parents[2]


def _invokes_tools(body: str) -> bool:
    return any(p.search(body) for p in _TOOL_SIGNALS)


def _has_allowed_tools(frontmatter: str) -> bool:
    return bool(_ALLOWED_RE.search(frontmatter))


def scan(*, commands_dir: Path) -> dict:
    if not commands_dir.is_dir():
        return {"commands_total": 0, "gaps": [], "coverage_pct": 100.0}
    cmds = sorted(commands_dir.glob("*.md"))
    gaps = []
    for c in cmds:
        text = c.read_text(encoding="utf-8")
        m = _FM_RE.search(text)
        if not m:
            continue  # no frontmatter — separate concern (frontmatter-coverage)
        fm = m.group(1)
        body = text[m.end():]
        if _invokes_tools(body + "\n" + fm) and not _has_allowed_tools(fm):
            gaps.append({"command": c.name})
    return {
        "commands_total": len(cmds),
        "gaps":           gaps,
        "coverage_pct":   round(
            100.0 * (len(cmds) - len(gaps)) / max(len(cmds), 1), 2,
        ),
    }


def _run(args) -> int:
    rep = scan(commands_dir=_plugin_root() / "commands")
    gaps = len(rep["gaps"])
    verdict = "green" if gaps == 0 else ("yellow" if gaps <= 5 else "red")
    if args.cmd == "gaps" and not args.json:
        for g in rep["gaps"]:
            print(g["command"])
        return 0 if gaps == 0 else 1
    _emit(rep, verdict=verdict, counts={"gaps": gaps})
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kaizen-command-allowed-tools-coverage",
        description="Audit commands/*.md for allowed-tools frontmatter coverage.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("report", "gaps"):
        s = sub.add_parser(n)
        s.add_argument("--json", action="store_true")
        s.set_defaults(func=_run)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
