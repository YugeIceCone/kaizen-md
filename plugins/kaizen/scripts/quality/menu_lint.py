#!/usr/bin/env python3
"""kaizen menu-lint — quality gate for AskUserQuestion-driven menu
slash commands.

Enforces the AskUserQuestion contract (max 4 questions per call; max 4
options per question) and the wiring contract (allowed-tools must
include "AskUserQuestion" when the body declares a wizard).

Non-menu commands (no AskUserQuestion mention) are skipped silently —
not every slash is a menu.

CLI:
  menu_lint.py check [--commands-dir DIR] [--json]
  menu_lint.py path
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


_FM_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
_ALLOWED_TOOLS_RE = re.compile(r"^allowed-tools:\s*(.+?)\s*$", re.MULTILINE)
# Each `question:` line inside a ```code block``` counts as one question.
_QUESTION_RE = re.compile(r"^\s*question\s*:\s*", re.MULTILINE)
# Each `- label:` line inside a ```code block``` counts as one option.
_OPTION_RE = re.compile(r"^\s*-\s+label\s*:\s*", re.MULTILINE)


def _split_fm(text: str) -> tuple[str, str]:
    """Return (frontmatter, body). Empty frontmatter when missing."""
    m = _FM_RE.match(text)
    if not m:
        return "", text
    return m.group(1), m.group(2)


def _is_menu(fm: str, body: str) -> bool:
    """Heuristic: a slash is a 'menu' if it has any of these signals —

    1. `AskUserQuestion` mentioned (in frontmatter `allowed-tools` or body).
    2. Body contains the wizard markup (`question:` AND `options:` in a
       fenced code block) — catches menus whose frontmatter forgot
       AskUserQuestion (which is exactly what we want to flag).

    Non-menu commands fall through silently — not every slash is a menu."""
    if ("AskUserQuestion" in fm) or ("AskUserQuestion" in body):
        return True
    # Wizard-markup heuristic: a fenced block with both `question:` and
    # `- label:` lines is the canonical AskUserQuestion payload shape.
    return bool(_QUESTION_RE.search(body) and _OPTION_RE.search(body))


def _has_askuserquestion_perm(fm: str) -> bool:
    """`allowed-tools` must list AskUserQuestion as a top-level entry."""
    m = _ALLOWED_TOOLS_RE.search(fm)
    if not m:
        return False
    # `allowed-tools: ["AskUserQuestion", ...]` — substring check is
    # enough; the surrounding `[...]` syntax + quoting is checked by CC
    # itself when it loads the slash.
    return "AskUserQuestion" in m.group(1)


def _count_questions_and_options(body: str) -> tuple[int, list[int]]:
    """Count `question:` and per-question `- label:` lines inside the
    body's fenced code blocks. Returns (max_per_call, options_per_q).

    The AskUserQuestion contract caps at 4 questions PER CALL. Each
    fenced YAML block represents one rendered call (the convention
    across kaizen menus); a wizard may make multiple sequential calls
    (e.g. master picker → branch picker) and that's fine. So we report
    the MAX questions in any single fence — not the body total —
    to avoid false-flagging multi-call menus."""
    fences = re.findall(r"```(?:[a-zA-Z0-9_-]*)\n(.*?)```", body, re.DOTALL)
    max_per_call = 0
    options_per_q: list[int] = []
    for fence in fences:
        q_offsets = [m.start() for m in _QUESTION_RE.finditer(fence)]
        if not q_offsets:
            continue
        if len(q_offsets) > max_per_call:
            max_per_call = len(q_offsets)
        # Slice the fence between consecutive question markers.
        boundaries = q_offsets + [len(fence)]
        for i in range(len(q_offsets)):
            chunk = fence[boundaries[i]:boundaries[i + 1]]
            options_per_q.append(len(_OPTION_RE.findall(chunk)))
    return max_per_call, options_per_q


def lint_menu(text: str, path: str) -> list[dict]:
    """Pure-function lint of a single slash-command file's source text.
    Returns a list of finding dicts. Empty list = clean OR non-menu."""
    fm, body = _split_fm(text)
    if not _is_menu(fm, body):
        return []

    findings: list[dict] = []

    if not _has_askuserquestion_perm(fm):
        findings.append({
            "rule_id": "missing-askuserquestion-perm",
            "severity": "error",
            "path": path,
            "msg": "menu body declares AskUserQuestion but frontmatter "
                    "`allowed-tools` does not list it",
        })

    max_per_call, options_per_q = _count_questions_and_options(body)

    if max_per_call > 4:
        findings.append({
            "rule_id": "too-many-questions",
            "severity": "warn",
            "path": path,
            "msg": f"single call has {max_per_call} questions — "
                    "AskUserQuestion caps at 4 per call",
        })

    for i, n_opts in enumerate(options_per_q, start=1):
        if n_opts > 4:
            findings.append({
                "rule_id": "too-many-options",
                "severity": "warn",
                "path": path,
                "msg": f"Q{i} has {n_opts} options — AskUserQuestion "
                        "caps at 4 per question (use Other + drill-down)",
            })

    return findings


def _commands_dir(arg: str | None) -> Path:
    if arg:
        return Path(arg)
    # __file__ lives at <plugin>/scripts/quality/menu_lint.py
    # so parents[3] is the plugin root.
    return Path(__file__).resolve().parents[3] / "commands"


def _cmd_check(args: argparse.Namespace) -> int:
    cdir = _commands_dir(args.commands_dir)
    if not cdir.is_dir():
        sys.stderr.write(f"menu-lint: commands dir not found: {cdir}\n")
        return 2
    all_findings: list[dict] = []
    for p in sorted(cdir.rglob("*.md")):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        all_findings.extend(lint_menu(text, str(p)))

    if args.json:
        print(json.dumps({"findings": all_findings,
                            "count": len(all_findings)}, indent=2))
    else:
        for f in all_findings:
            print(f"[{f['severity']}] {f['rule_id']}: "
                  f"{f['path']}\n  {f['msg']}")
        if all_findings:
            print(f"\nmenu-lint: {len(all_findings)} finding(s)")
        else:
            print(f"menu-lint: clean ({sum(1 for _ in cdir.rglob('*.md'))} files scanned)")

    # Error severity → exit 1 (hard fail); warn only → exit 0 (advisory).
    has_error = any(f["severity"] == "error" for f in all_findings)
    return 1 if has_error else 0


def _cmd_path(args: argparse.Namespace) -> int:
    print(_commands_dir(args.commands_dir))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="menu-lint",
        description="Quality gate for AskUserQuestion-driven menu slash commands.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("check", help="lint every slash command for menu contract")
    pc.add_argument("--commands-dir", default=None,
                     help="Override commands/ dir (default: <plugin>/commands/)")
    pc.add_argument("--json", action="store_true",
                     help="Emit findings as JSON")
    pc.set_defaults(func=_cmd_check)

    pp = sub.add_parser("path", help="print resolved commands dir")
    pp.add_argument("--commands-dir", default=None)
    pp.set_defaults(func=_cmd_path)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
