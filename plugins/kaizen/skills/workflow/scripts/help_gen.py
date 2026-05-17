#!/usr/bin/env python3
"""kaizen-help-gen — regenerate commands/help.md from live command files.

Walks plugins/kaizen/commands/*.md, extracts name + description from each
frontmatter, classifies into the 9 domain clusters via the mapping
below, and rewrites the help.md body. Idempotent.

## Why

The static help body MUST stay current with the actual command surface.
Hand-maintained drift is real (we shipped 4 new commands this session
that aren't in the table). Regenerating from the source of truth means
the body never lies.

## Zero-token-cost path for users

The body still costs ~1 read when the agent invokes /kaizen:help, BUT:
  - Users can run `kaizen commands` directly in their shell → no agent
    involvement at all (true zero-cost)
  - Or `! kaizen commands` in CC's shell-mode → local-command-caveat
    prevents the agent from acting on it (the harness still includes
    it in context but the cost is "read once, ignore")
  - The auto-generator runs ONCE on commit (or manual `kaizen-help-gen`)
    so /kaizen:help renders fresh without per-invocation work

## CLI

  help_gen.py render         # rewrite commands/help.md (atomic)
  help_gen.py check          # exit 1 if help.md is stale vs live commands
  help_gen.py print          # print body to stdout (don't write)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


_SCRIPT_DIR = Path(__file__).resolve().parent


def _plugin_root() -> Path:
    return _SCRIPT_DIR.parents[2]


# Cluster mapping: command-stem → cluster. Hand-maintained per the
# CLAUDE.md "Slash commands by cluster" taxonomy. Unknown commands fall
# into "uncategorized" — gen flags them so the human adds the mapping.
CLUSTERS: list[tuple[str, list[str]]] = [
    ("audit/quality", [
        "audit", "audit:axis", "gatekeeper", "gate", "precommit", "review",
        "coverage", "iron-laws", "karpathy-check", "vibe-check",
        "self-audit", "agent-self-audit", "ci-gate",
    ]),
    ("observability", [
        "trace", "trace-search", "trace-proxy", "metrics", "observe",
        "context", "statusline",
    ]),
    ("brain/memory", [
        "brain", "self-improving", "gold",
    ]),
    ("workflow", [
        "backlog", "handoff", "loop", "flow", "workflow", "mode",
        "session-mode", "migrate", "migrate-paths",
    ]),
    ("plugin-meta", [
        "setup", "bootstrap", "update", "refresh-cache", "daemon",
        "hygiene", "backup", "publish", "env", "health", "status",
        "surface", "disable-dupes", "plugin-development",
    ]),
    ("discovery/search", [
        "discovery", "onboard", "knowledge", "claude-docs", "code-tour",
        "scrape", "models", "browser", "docs",
    ]),
    ("intent/session", [
        "intent", "session-mode", "skill-suggest",
    ]),
    ("dev-aids", [
        "rule", "rules", "schema", "inbox", "test", "help",
    ]),
]

# Cluster picker QA: 4 visible options in the AskUserQuestion call
# (within the 4-options-per-question contract); the rest go to "Other"
# overflow. Picked by usage-importance, not raw command count.
QA_CLUSTER_PICKS = ("audit/quality", "workflow", "observability", "brain/memory")


_FM_RE   = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
_NAME_RE = re.compile(r"^name:\s*(\S+)\s*$", re.MULTILINE)
_DESC_RE = re.compile(r"^description:\s*(.+?)$", re.MULTILINE)


def _short_desc(raw: str) -> str:
    """Compact a frontmatter description to one ~80-char line.
    Strips trigger-phrase tail + trailing 'Triggers on...' clause."""
    raw = raw.strip().strip('"\'')
    # Drop "Triggers on ..." tail
    raw = re.split(r"\s*Triggers on\b", raw, maxsplit=1)[0]
    raw = re.split(r"\s*Triggers\b", raw, maxsplit=1)[0]
    # Compress whitespace
    raw = re.sub(r"\s+", " ", raw)
    # Truncate
    if len(raw) > 85:
        raw = raw[:82] + "..."
    return raw.rstrip(".")


def _read_command(p: Path) -> dict | None:
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return None
    fm = _FM_RE.match(text)
    if not fm:
        return None
    name_m = _NAME_RE.search(fm.group(1))
    desc_m = _DESC_RE.search(fm.group(1))
    name = (name_m.group(1) if name_m else p.stem).strip()
    desc = _short_desc(desc_m.group(1)) if desc_m else "(no description)"
    return {"name": name, "stem": p.stem, "desc": desc}


def discover_commands(root: Path | None = None) -> list[dict]:
    """Walk commands/ recursively (CC's slash convention: `commands/foo/bar.md`
    → `/kaizen:foo:bar`). Subdirectory commands surface as `<dir>:<file>`
    so the help table shows them under their cluster correctly."""
    root = root or _plugin_root()
    cmds_dir = root / "commands"
    out = []
    for p in sorted(cmds_dir.rglob("*.md")):
        c = _read_command(p)
        if not c:
            continue
        # Nested: rewrite display name + stem to `<parent>:<stem>` so
        # both cluster matching (uses stem) and table render (uses
        # stem) show the colon-namespace correctly.
        rel = p.relative_to(cmds_dir)
        if len(rel.parts) > 1:
            qualified = ":".join(rel.with_suffix("").parts)
            c["name"] = qualified
            c["stem"] = qualified
        out.append(c)
    return out


def cluster_assignments(commands: list[dict]) -> dict[str, list[dict]]:
    """Bucket commands by cluster. Unknown → 'uncategorized'."""
    by_stem = {c["stem"]: c for c in commands}
    buckets: dict[str, list[dict]] = {name: [] for name, _ in CLUSTERS}
    buckets["uncategorized"] = []
    assigned: set[str] = set()
    for cluster_name, members in CLUSTERS:
        for stem in members:
            if stem in by_stem and stem not in assigned:
                buckets[cluster_name].append(by_stem[stem])
                assigned.add(stem)
    for stem, c in by_stem.items():
        if stem not in assigned:
            buckets["uncategorized"].append(c)
    return buckets


def _qa_preamble(buckets: dict[str, list[dict]]) -> list[str]:
    """The cluster-picker QA contract — instructions the agent follows
    when /kaizen:help is invoked with no arguments. Output goes near
    the top of the rendered body."""
    overflow = [c for c, _ in CLUSTERS if c not in QA_CLUSTER_PICKS
                 and buckets.get(c)]
    lines = [
        "## Interactive cluster wizard (no-args mode)",
        "",
        "When `/kaizen:help` is invoked with **no arguments**, run the",
        "`AskUserQuestion` cluster picker below before anything else.",
        "With explicit args (`all`, a cluster name, or `<command>`), skip",
        "the wizard and emit the corresponding slice directly.",
        "",
        "**Q1 — Which domain?** (single-select; 4 options + Other)",
        "",
    ]
    for name in QA_CLUSTER_PICKS:
        count = len(buckets.get(name, []))
        lines.append(f"- `{name}` ({count})")
    lines.append(f"- Other (overflow: {' / '.join(overflow)})")
    lines.extend([
        "",
        "After the user picks, dispatch:",
        "",
        "  `kaizen-help-gen cluster <picked-name>`",
        "",
        "to render just that cluster's sub-table. For `Other`, run a",
        "follow-up `AskUserQuestion` over the overflow clusters, then",
        "dispatch the same way.",
        "",
    ])
    return lines


def render_body(commands: list[dict]) -> str:
    buckets = cluster_assignments(commands)
    total = len(commands)
    lines = [
        f"# /kaizen:help",
        f"",
        f"Static taxonomy of all {total} `/kaizen:*` commands. **One screen, zero bash",
        f"execution.** For full per-command docs use `kaizen help <name>`. Auto-",
        f"generated from `commands/*.md` frontmatter via `kaizen-help-gen`.",
        f"",
    ]
    lines.extend(_qa_preamble(buckets))
    for cluster_name, _ in CLUSTERS:
        cmds = buckets[cluster_name]
        if not cmds:
            continue
        # Compute column width for `name` alignment
        max_name = max(len(c["stem"]) for c in cmds)
        lines.append(f"## {cluster_name} ({len(cmds)})")
        lines.append(f"")
        lines.append(f"| Command | Does |")
        lines.append(f"|---|---|")
        for c in cmds:
            lines.append(f"| `{c['stem']}` | {c['desc']} |")
        lines.append(f"")
    if buckets["uncategorized"]:
        lines.append(f"## uncategorized ({len(buckets['uncategorized'])}) — add to CLUSTERS")
        lines.append(f"")
        lines.append(f"| Command | Does |")
        lines.append(f"|---|---|")
        for c in buckets["uncategorized"]:
            lines.append(f"| `{c['stem']}` | {c['desc']} |")
        lines.append(f"")
    lines.extend([
        "## Drill-down (single CLI roundtrip)",
        "",
        "- `kaizen help <name>` — full per-command docstring",
        "- `kaizen list --json` — machine-readable inventory",
        "- `kaizen <bin> --help` — per-bin usage",
        "- `/kaizen:status` — kaizen install health snapshot",
        "",
        "## Zero-token-cost view (for user, not agent)",
        "",
        "Run in your own shell to get this list with no agent involvement:",
        "",
        "  `kaizen commands`        # full with descriptions",
        "  `kaizen list --json`     # machine-readable",
        "  `kaizen help <name>`     # one command's full docstring",
        "",
    ])
    return "\n".join(lines)


def render_full_help_md(commands: list[dict]) -> str:
    """Render the entire help.md (frontmatter + body) atomically."""
    body = render_body(commands)
    front = """---
name: help
description: Show kaizen surface — auto-generated by kaizen-help-gen from `commands/*.md`. Triggers on "kaizen help", "what kaizen commands", "list kaizen", "what does /kaizen:X do", "kaizen surface", "show me kaizen". No-args → interactive cluster-picker wizard; with args → static table.
argument-hint: "(none = cluster wizard) | all | <cluster> | <command-name>"
allowed-tools: ["AskUserQuestion", "Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-help-gen:*)", "Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/help_gen.py:*)"]
---

"""
    return front + body


def _atomic_write(path: Path, content: str) -> None:
    try:
        sys.path.insert(0, str(_SCRIPT_DIR))
        import _atomic
        _atomic.atomic_write(path, content)
    except (OSError, ImportError):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _help_md_path() -> Path:
    return _plugin_root() / "commands" / "help.md"


def _cmd_render(args) -> int:
    commands = discover_commands()
    out = render_full_help_md(commands)
    _atomic_write(_help_md_path(), out)
    print(f"[kaizen-help-gen] rendered {len(commands)} commands → {_help_md_path()}")
    return 0


def _cmd_check(args) -> int:
    """Exit 1 if help.md is stale vs live commands."""
    commands = discover_commands()
    expected = render_full_help_md(commands)
    actual = _help_md_path().read_text(encoding="utf-8") if _help_md_path().is_file() else ""
    if expected == actual:
        print(f"[kaizen-help-gen] check: help.md is fresh ({len(commands)} commands)")
        return 0
    sys.stderr.write(
        f"[kaizen-help-gen] check: help.md is STALE "
        f"(re-run `kaizen-help-gen render` — {len(commands)} commands)\n")
    return 1


def _cmd_print(args) -> int:
    commands = discover_commands()
    print(render_body(commands))
    return 0


def _render_one_cluster(commands: list[dict], cluster_name: str) -> str:
    """Emit a single cluster's sub-table (header + rows). Backs the
    /kaizen:help QA wizard drill-down."""
    buckets = cluster_assignments(commands)
    cmds = buckets.get(cluster_name, [])
    out = [f"## {cluster_name} ({len(cmds)})", ""]
    if not cmds:
        out.append("(no commands in this cluster yet)")
        return "\n".join(out) + "\n"
    out.append("| Command | Does |")
    out.append("|---|---|")
    for c in cmds:
        out.append(f"| `{c['stem']}` | {c['desc']} |")
    return "\n".join(out) + "\n"


def _cmd_cluster(args) -> int:
    """Render one cluster's sub-table (drill-down from /kaizen:help QA)."""
    if args.list:
        for name, _ in CLUSTERS:
            print(name)
        return 0
    if not args.name:
        sys.stderr.write(
            "[kaizen-help-gen] cluster: provide a cluster name or --list\n")
        return 2
    known = {name for name, _ in CLUSTERS}
    if args.name not in known:
        sys.stderr.write(
            f"[kaizen-help-gen] cluster: unknown cluster '{args.name}'. "
            f"Known: {', '.join(sorted(known))}\n")
        return 2
    commands = discover_commands()
    sys.stdout.write(_render_one_cluster(commands, args.name))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-help-gen",
        description="Auto-generate commands/help.md from live command frontmatter.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("render", help="atomic write commands/help.md")
    pr.set_defaults(func=_cmd_render)

    pc = sub.add_parser("check", help="exit 1 if help.md is stale")
    pc.set_defaults(func=_cmd_check)

    pp = sub.add_parser("print", help="print body to stdout (don't write)")
    pp.set_defaults(func=_cmd_print)

    pcl = sub.add_parser("cluster", help="render one cluster's sub-table")
    pcl.add_argument("name", nargs="?", help="cluster name (e.g. audit/quality)")
    pcl.add_argument("--list", action="store_true",
                      help="list known cluster names instead of rendering")
    pcl.set_defaults(func=_cmd_cluster)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
