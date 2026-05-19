"""kaizen-better-memory — auto-memory MEMORY.md index management.

The auto-memory dir at ``~/.claude/projects/<slug>/memory/`` accumulates
captured ``project_*.md`` + ``feedback_*.md`` entries over time. Claude
Code auto-loads the first 200 lines / 25KB of ``MEMORY.md`` at every
session start, but it does NOT keep MEMORY.md in sync with the captured
files — orphan entries are loaded only on-demand (Claude reads them
when relevant). ``kaizen-better-memory regen`` rebuilds MEMORY.md from the
frontmatter of every sibling so all captures become reachable at
session start.

## Subcommands

    kaizen-better-memory regen [--dir PATH] [--json]
        Rebuild MEMORY.md from the dir's *.md files.

    kaizen-better-memory path [--dir PATH]
        Print the resolved auto-memory dir for the current cwd.

## Frontmatter normalization

Real-world captures have escape leakage (``\\u2014`` instead of ``—``)
and broken YAML (unterminated double-quoted strings from buggy
auto-capture writers). ``regen`` normalizes both — JSON-decode handles
the escapes; an unterminated-string fallback strips the leading ``"``.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


def _yaml_unescape(s: str) -> str:
    """Decode a YAML scalar value to its raw string.

    Handles:
    - Properly-quoted double-quoted: ``"foo"`` via json.loads
    - Single-quoted with YAML doubling: ``'it''s'`` -> ``it's``
    - Unterminated double-quoted (broken auto-capture): ``"foo`` -> ``foo``
    """
    s = s.strip()
    if not s:
        return s
    if s.startswith('"') and s.endswith('"') and len(s) >= 2:
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            # Unterminated / malformed — strip leading + trailing if matched
            s = s[1:]
            if s.endswith('"'):
                s = s[:-1]
            return s
    if s.startswith('"') and not s.endswith('"'):
        return s[1:]
    if s.startswith("'") and s.endswith("'") and len(s) >= 2:
        return s[1:-1].replace("''", "'")
    return s


def _trim(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


_NAME_RE = re.compile(r"^name:\s*(.+?)$", re.M)
_DESC_RE = re.compile(r"^description:\s*(.+?)$", re.M)


def _entry_for(path: Path) -> tuple[str, str]:
    """Return (name, description) for a memory file, with normalization."""
    body = path.read_text(encoding="utf-8", errors="replace")
    name_m = _NAME_RE.search(body)
    desc_m = _DESC_RE.search(body)
    name = _yaml_unescape(name_m.group(1)) if name_m else path.stem
    desc = _yaml_unescape(desc_m.group(1)) if desc_m else ""
    return name, desc


def regen_index(memory_dir: Path) -> int:
    """Rebuild MEMORY.md from *.md siblings. Returns count of indexed files."""
    memory_dir = Path(memory_dir)
    memory_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in memory_dir.glob("*.md") if p.name != "MEMORY.md")

    out: list[str] = [
        "# Project memory index",
        "",
        f"> {len(files)} captured entries. Auto-loaded into context at "
        f"session start (first 200 lines / 25KB).",
        "",
    ]
    groups: dict[str, list[str]] = {"feedback": [], "project": [], "other": []}
    for p in files:
        name, desc = _entry_for(p)
        line = f"- [{_trim(name, 80)}]({p.name}) — {_trim(desc, 110)}"
        if p.name.startswith("feedback_"):
            groups["feedback"].append(line)
        elif p.name.startswith("project_"):
            groups["project"].append(line)
        else:
            groups["other"].append(line)

    for label, key in [
        ("Feedback (corrections + preferences)", "feedback"),
        ("Project state + decisions", "project"),
        ("Other", "other"),
    ]:
        if groups[key]:
            out.append(f"## {label}")
            out.append("")
            out.extend(groups[key])
            out.append("")

    (memory_dir / "MEMORY.md").write_text("\n".join(out), encoding="utf-8")
    return len(files)


def _default_memory_dir() -> Path:
    """Resolve the auto-memory dir for the current cwd.

    Resolution order (high → low precedence):
    1. ``KAIZEN_BETTER_MEMORY_DIR`` env (sandbox override; matches the
       kaizen per-feature env convention).
    2. Git repo root slug — per the Claude Code memory doc: "The
       <project> path is derived from the git repository, so all
       worktrees and subdirectories within the same repo share one
       auto memory directory."
    3. cwd slug — fallback outside a git repo.
    """
    env = os.environ.get("KAIZEN_BETTER_MEMORY_DIR")
    if env:
        return Path(env).expanduser()
    import subprocess
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=2, check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            root = Path(result.stdout.strip())
        else:
            root = Path.cwd().resolve()
    except (OSError, subprocess.SubprocessError):
        root = Path.cwd().resolve()
    slug = str(root).replace("/", "-")
    return Path.home() / ".claude" / "projects" / slug / "memory"


def _cmd_regen(args) -> int:
    d = Path(args.dir) if args.dir else _default_memory_dir()
    count = regen_index(d)
    if args.json:
        print(json.dumps({"data": {"dir": str(d), "indexed": count}}))
    else:
        print(f"kaizen-better-memory regen: indexed {count} entries -> {d / 'MEMORY.md'}")
    return 0


def _cmd_path(args) -> int:
    d = Path(args.dir) if args.dir else _default_memory_dir()
    print(d)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="kaizen-better-memory",
                                 description="Auto-memory index management.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sr = sub.add_parser("regen", help="rebuild MEMORY.md from sibling *.md files")
    sr.add_argument("--dir", help="memory dir (default: ~/.claude/projects/<cwd-slug>/memory/)")
    sr.add_argument("--json", action="store_true")
    sr.set_defaults(func=_cmd_regen)

    sp = sub.add_parser("path", help="print the resolved memory dir")
    sp.add_argument("--dir", help="override dir (echoes the resolved value)")
    sp.set_defaults(func=_cmd_path)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
