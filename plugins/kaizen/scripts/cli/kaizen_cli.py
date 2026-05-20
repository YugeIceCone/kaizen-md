#!/usr/bin/env python3
"""kaizen — unified CLI dispatcher (the "bash loop" runner).

Replaces the prior 65-line bash multiplexer in `bin/kaizen` with a
discoverable, machine-readable dispatcher. Subcommand resolution is
unchanged (still `bin/kaizen-<sub>` wrapper lookup) — what's new:

  - `kaizen list [--json]` — grouped + categorized subcommand catalog
  - `kaizen commands [list|show <name>] [--json]` — slash command inventory
    (the `/kaizen:<name>` surface Claude Code exposes — separate from
    the `bin/kaizen-*` CLI wrapper surface this dispatcher routes to)
  - `kaizen help <sub>` — full docstring pulled from the wrapper header
  - `kaizen patterns [--json]` — canonical CLI-patterns catalog
    (sourced from skills/plugin-development/domain/cli-patterns.yaml)
  - `kaizen --time <sub> [args]` — dispatch + wall-clock timing
  - `kaizen --trace <sub> [args]` — dispatch + kaizen-trace events
  - `kaizen <sub> [args]` — vanilla dispatch (execv, zero overhead)
  - `kaizen version` — plugin version + dispatcher version

## Subcommand categories

Subcommands are categorized by introspection of their wrapper script's
target (the `exec python3 ...skills/<X>/scripts/<Y>.py` line) plus a
small naming convention. See `_CATEGORIES` below.

## Design notes

- Default dispatch uses `os.execv` — zero extra fork, preserves exit
  code via OS-level replacement. Post-exec hooks (`--time`, `--trace`)
  fall back to `subprocess.run` so we get a result to act on.
- `bin/kaizen-<sub>` wrappers remain. Each is a thin shell that the
  Claude Code marketplace knows by name. Some users / tools call
  `kaizen-gatekeeper check` directly — those still work.
- Discovery via wrapper header — every wrapper's first comment line
  ("# kaizen-FOO — DESCRIPTION.") is the catalog entry.

## Exit codes

  0       — subcommand succeeded (or list/help/version printed)
  1       — subcommand failed (passthrough)
  2       — invocation error (unknown subcommand, missing arg)
  127     — wrapper not executable / not found (passthrough)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PLUGIN_ROOT = _SCRIPT_DIR.parent.parent  # plugins/kaizen/
_BIN_DIR = _PLUGIN_ROOT / "bin"
_COMMANDS_DIR = _PLUGIN_ROOT / "commands"

DISPATCHER_VERSION = "1.1.0"

# Category map: substring match against subcommand name → group label.
# Order matters — first match wins. "misc" is the fallback.
_CATEGORIES: list[tuple[str, str]] = [
    ("gatekeeper", "gate"),
    ("iron-laws",  "gate"),
    ("karpathy",   "gate"),
    ("audit",      "gate"),
    ("review",     "gate"),
    ("surface",    "discovery"),
    ("status",     "discovery"),
    ("menu",       "discovery"),
    ("observe",    "discovery"),
    ("metrics",    "discovery"),
    ("knowledge",  "search"),
    ("onboard",    "search"),
    ("trace",      "search"),
    ("claude-docs","search"),
    ("loc",        "search"),
    ("brain",      "brain"),
    ("handoff",    "brain"),
    ("remember",   "brain"),
    ("backlog",    "workflow"),
    ("roadmap",    "workflow"),
    ("workflow",   "workflow"),
    ("refactor",   "workflow"),
    ("setup",      "maintenance"),
    ("install",    "maintenance"),
    ("uninstall",  "maintenance"),
    ("bootstrap",  "maintenance"),
    ("daemon",     "maintenance"),
    ("hygiene",    "maintenance"),
    ("env",        "maintenance"),
    ("cache",      "maintenance"),
    ("export",     "dev"),
    ("scrape",     "dev"),
    ("browser",    "dev"),
    ("docs",       "dev"),
    ("loop",       "dev"),
    ("rule",       "config"),
    ("rules",      "config"),
    ("inbox",      "config"),
    ("context",    "config"),
    ("flow",       "config"),
    ("lint",       "lint"),
    ("drift",      "lint"),
    ("manifests",  "lint"),
]

def _list_wrappers() -> list[Path]:
    """All bin/kaizen-* executables (excluding `kaizen` itself)."""
    if not _BIN_DIR.is_dir():
        return []
    return sorted(
        p for p in _BIN_DIR.glob("kaizen-*")
        if p.is_file() and os.access(p, os.X_OK)
    )

def _wrapper_description(path: Path) -> str:
    """First non-shebang comment line of the wrapper, as the catalog entry."""
    try:
        for line in path.read_text(errors="ignore").splitlines()[:10]:
            line = line.strip()
            if line.startswith("#!"):
                continue
            if line.startswith("#"):
                desc = line.lstrip("#").strip()
                # Strip leading "kaizen-X — " prefix if present
                if " — " in desc:
                    desc = desc.split(" — ", 1)[1]
                return desc
            if line:  # first non-comment non-blank line — stop
                break
    except OSError:
        pass
    return ""

def _categorize(name: str) -> str:
    for substr, cat in _CATEGORIES:
        if substr in name:
            return cat
    return "misc"

# ─── Slash command inventory ────────────────────────────────────────────

_FRONTMATTER_RX = re.compile(r"^---\n(.*?)\n---", re.DOTALL)

def _parse_frontmatter(text: str) -> dict[str, str]:
    """Lightweight YAML-frontmatter parser — extracts top-level scalar
    keys only (sufficient for `name`, `description`, `argument-hint`).
    Avoids a PyYAML dep so the dispatcher stays stdlib-only."""
    m = _FRONTMATTER_RX.match(text)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" not in line or line.startswith(" "):
            continue
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out

def _list_slash_commands() -> list[dict[str, str]]:
    """Every commands/*.md file → {name, description, argument_hint,
    has_bash_body, bin_wrapper}.

    `has_bash_body`: True if the markdown body contains a `!`-prefixed
    bash invocation (Claude Code's syntax for "execute this on /cmd").
    `bin_wrapper`: name of the matching `bin/kaizen-<name>` if present
    (most bash-bodied commands have one; pure-prompt commands don't).
    """
    if not _COMMANDS_DIR.is_dir():
        return []
    out = []
    for p in sorted(_COMMANDS_DIR.glob("*.md")):
        try:
            text = p.read_text(errors="ignore")
        except OSError:
            continue
        fm = _parse_frontmatter(text)
        name = fm.get("name") or p.stem
        # Detect a bash body — Claude Code `!`-prefix or fenced ```bash
        has_bash = bool(re.search(r"^!`", text, re.MULTILINE)) or \
            "```bash" in text
        bin_wrapper = f"kaizen-{p.stem}" if (_BIN_DIR / f"kaizen-{p.stem}").is_file() else ""
        out.append({
            "name": name,
            "slug": p.stem,
            "description": fm.get("description", "")[:200],
            "argument_hint": fm.get("argument-hint", ""),
            "has_bash_body": str(has_bash).lower(),  # str for JSON friendliness
            "bin_wrapper": bin_wrapper,
        })
    return out

def _plugin_version() -> str:
    pj = _PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
    if not pj.is_file():
        return "?"
    try:
        return json.loads(pj.read_text()).get("version", "?")
    except json.JSONDecodeError:
        return "?"

def cmd_list(args: argparse.Namespace) -> int:
    wrappers = _list_wrappers()
    catalog: dict[str, list[tuple[str, str, str]]] = {}
    for w in wrappers:
        name = w.name[len("kaizen-"):]
        desc = _wrapper_description(w)
        cat = _categorize(name)
        catalog.setdefault(cat, []).append((name, desc, str(w)))

    if args.json:
        print(json.dumps({
            cat: [{"name": n, "description": d, "wrapper": w}
                  for n, d, w in items]
            for cat, items in sorted(catalog.items())
        }, indent=2))
        return 0

    print(f"kaizen v{_plugin_version()} (dispatcher v{DISPATCHER_VERSION})")
    print(f"  {len(wrappers)} subcommands across {len(catalog)} categories")
    print("")
    print(f"  usage: kaizen <subcommand> [args]")
    print(f"         kaizen list [--json]")
    print(f"         kaizen help <subcommand>")
    print(f"         kaizen commands [list|show <name>] [--json]")
    print(f"         kaizen --time <subcommand> [args]")
    print(f"         kaizen --trace <subcommand> [args]")
    print("")
    for cat in sorted(catalog):
        print(f"  {cat}:")
        for name, desc, _ in sorted(catalog[cat]):
            print(f"    {name:24s} {desc[:60]}")
        print("")
    # Also surface the slash-command count so users discover both surfaces.
    n_slash = len(_list_slash_commands())
    if n_slash:
        print(f"  See also: kaizen commands  ({n_slash} slash commands "
              f"in commands/*.md — invoke via /kaizen:<name> in Claude Code,")
        print(f"             or run `kaizen <name>` for any with a bin wrapper)")
        print("")
    print(f"  plugin root: {_PLUGIN_ROOT}")
    return 0

def cmd_help(args: argparse.Namespace) -> int:
    sub = args.subcommand
    wrapper = _BIN_DIR / f"kaizen-{sub}"
    if not wrapper.is_file():
        sys.stderr.write(f"kaizen: unknown subcommand '{sub}'\n")
        return 2
    # Print the wrapper header (all leading comment lines).
    lines = wrapper.read_text(errors="ignore").splitlines()
    print(f"=== kaizen-{sub} ===")
    for line in lines:
        if not line.strip():
            continue
        if line.startswith("#!"):
            continue
        if line.startswith("#"):
            print("  " + line.lstrip("#").strip())
        else:
            break  # first non-comment line — header is done
    # Also surface the wrapper's underlying script's --help if it has one.
    print("")
    print("=== wrapper --help (passthrough) ===")
    # Flush before subprocess — when stdout is piped, Python's prints
    # are fully-buffered and would otherwise land AFTER the subprocess
    # output, scrambling the order.
    sys.stdout.flush()
    try:
        subprocess.run([str(wrapper), "--help"], timeout=5)
    except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError):
        pass
    return 0

def cmd_commands(args: argparse.Namespace) -> int:
    """Inventory the slash commands at commands/*.md — discovery surface
    for the `/kaizen:<name>` menu Claude Code exposes. Separate from
    `cmd_list` which inventories the bin/kaizen-* CLI wrappers.

    Sub-modes:
      list           text inventory (default)
      list --json    machine-readable
      show <name>    print the .md body
    """
    sub = getattr(args, "subcmd", "list") or "list"
    cmds = _list_slash_commands()

    if sub == "show":
        target = args.name
        match = next((c for c in cmds if c["slug"] == target or c["name"] == target), None)
        if not match:
            sys.stderr.write(f"kaizen: unknown slash command '{target}'\n")
            return 2
        text = (_COMMANDS_DIR / f"{match['slug']}.md").read_text()
        print(text)
        return 0

    if args.json:
        print(json.dumps(cmds, indent=2))
        return 0

    bash_n = sum(1 for c in cmds if c["has_bash_body"] == "true")
    pure_n = len(cmds) - bash_n
    print(f"kaizen v{_plugin_version()} — slash commands ({len(cmds)} total: "
          f"{bash_n} executable, {pure_n} agent-only)")
    print(f"  invoke via Claude Code: /kaizen:<name>")
    print(f"  bash-bodied commands also have bin/kaizen-<name> wrappers (callable via "
          f"`kaizen <name>`)")
    print("")
    # Group: bash-bodied (callable both ways) vs pure-agent (only via /)
    bash_cmds = [c for c in cmds if c["has_bash_body"] == "true"]
    pure_cmds = [c for c in cmds if c["has_bash_body"] != "true"]

    if bash_cmds:
        print(f"  bash-bodied (callable from CLI + agent):")
        for c in bash_cmds:
            link = "" if c["bin_wrapper"] else "  (no bin wrapper)"
            print(f"    {c['slug']:24s} {c['description'][:60]}{link}")
        print("")
    if pure_cmds:
        print(f"  agent-only (invoke via /kaizen:<name> in Claude Code):")
        for c in pure_cmds:
            print(f"    {c['slug']:24s} {c['description'][:60]}")
        print("")
    return 0

def cmd_version(args: argparse.Namespace) -> int:
    print(f"kaizen v{_plugin_version()}")
    print(f"dispatcher v{DISPATCHER_VERSION}")
    return 0

# ─── kaizen patterns — canonical CLI-patterns catalog ────────────────

_PATTERNS_YAML = (Path(__file__).resolve().parents[2]
                    / "skills" / "plugin-development"
                    / "domain" / "cli-patterns.yaml")

def _load_patterns_catalog() -> dict:
    """Parse the cli-patterns.yaml SSOT. Stdlib-only via a tiny YAML
    subset reader — avoids forcing a pyyaml dep on the dispatcher."""
    if not _PATTERNS_YAML.is_file():
        return {"version": 0, "patterns": [], "error": f"missing {_PATTERNS_YAML}"}
    try:
        import yaml  # type: ignore
        return yaml.safe_load(_PATTERNS_YAML.read_text(encoding="utf-8"))
    except ImportError:
        # Fallback: regex-extract id/shape/count/why per item — KISS,
        # not a general YAML parser. Catalog shape is stable + flat.
        text = _PATTERNS_YAML.read_text(encoding="utf-8")
        out: list[dict] = []
        cur: dict = {}
        for line in text.splitlines():
            if line.startswith("  - id:"):
                if cur:
                    out.append(cur)
                cur = {"id": line.split(":", 1)[1].strip()}
            elif line.startswith("    shape:"):
                cur["shape"] = line.split(":", 1)[1].strip().strip('"')
            elif line.startswith("    count:"):
                cur["count"] = int(line.split(":", 1)[1].strip())
            elif line.startswith("    why:"):
                cur["why"] = line.split(":", 1)[1].strip().strip("|").strip()
            elif line.startswith("    iron_law:"):
                v = line.split(":", 1)[1].strip()
                cur["iron_law"] = None if v == "null" else v
        if cur:
            out.append(cur)
        return {"version": 1, "patterns": out}

def _find_repo_root() -> Path:
    """Walk up from this script until .git/ is found — the detect:
    recipes use repo-relative paths (plugins/kaizen/...)."""
    cur = Path(__file__).resolve()
    for _ in range(8):
        if (cur / ".git").is_dir():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return Path.cwd()

def _refresh_pattern_counts(dry_run: bool = False) -> int:
    """Re-run each pattern's detect: recipe and update its count: in
    place. Returns the number of patterns whose count changed."""
    import re as _re
    text = _PATTERNS_YAML.read_text(encoding="utf-8")
    ids = _re.findall(r"  - id:\s+(\S+)", text)
    detects = _re.findall(r"    detect:\s+(.+)", text)
    counts_before = {pid: int(m) for pid, m in
                       zip(ids, _re.findall(r"    count:\s+(\d+)", text))}
    repo_root = _find_repo_root()
    updates: dict[str, int] = {}
    for pid, dt in zip(ids, detects):
        dt = dt.strip().strip("'\"")
        full = "shopt -s globstar; " + dt + " 2>/dev/null | wc -l"
        r = subprocess.run(["bash", "-c", full], cwd=repo_root,
                            capture_output=True, text=True, timeout=30)
        try:
            n = int((r.stdout.strip() or "0").splitlines()[-1])
            updates[pid] = n
        except (ValueError, IndexError):
            continue

    changed = []
    for pid, new_n in updates.items():
        old_n = counts_before.get(pid, -1)
        if new_n != old_n:
            changed.append((pid, old_n, new_n))

    if not dry_run:
        # Patch counts in place — per-block regex replace
        def _replace(match):
            block = match.group(0)
            pid_m = _re.search(r"id:\s+(\S+)", block)
            if pid_m and pid_m.group(1) in updates:
                return _re.sub(r"(    count:\s+)\d+",
                                rf"\g<1>{updates[pid_m.group(1)]}", block)
            return block
        new_text = _re.sub(r"  - id:.*?(?=  - id:|$)", _replace, text,
                            flags=_re.DOTALL)
        if new_text != text:
            _PATTERNS_YAML.write_text(new_text, encoding="utf-8")

    return changed, len(updates)

def cmd_patterns(args: argparse.Namespace) -> int:
    if getattr(args, "refresh", False):
        changed, total = _refresh_pattern_counts(dry_run=args.dry_run)
        if args.dry_run:
            if not changed:
                print(f"kaizen patterns --refresh --dry-run: no change "
                      f"({total} patterns scanned)")
                return 0
            print(f"kaizen patterns --refresh --dry-run: would update "
                  f"{len(changed)}/{total} patterns:")
            for pid, old, new in changed:
                print(f"  {pid:<28}  {old} → {new}  ({new - old:+d})")
            return 0
        if not changed:
            print(f"kaizen patterns --refresh: no change "
                  f"({total} patterns at zero drift)")
            return 0
        print(f"kaizen patterns --refresh: updated {len(changed)}/{total} patterns")
        for pid, old, new in changed:
            print(f"  {pid:<28}  {old} → {new}  ({new - old:+d})")
        return 0

    catalog = _load_patterns_catalog()
    if args.json:
        print(json.dumps(catalog, indent=2, default=str))
        return 0
    patterns = catalog.get("patterns", [])
    print(f"kaizen CLI patterns — {len(patterns)} canonical entries"
          f"  (source: skills/plugin-development/domain/cli-patterns.yaml)")
    print()
    for p in patterns:
        law = f"  [law: {p['iron_law']}]" if p.get("iron_law") else ""
        print(f"  {p['id']:<28} (×{p.get('count', '?')})  {p.get('shape', '')}{law}")
    print()
    print("  json output:  kaizen patterns --json")
    return 0

# ─── kaizen agents scaffold — generate Claude subagent stubs ─────────

_AGENTS_DIR = _PLUGIN_ROOT / "agents"
_SKILLS_DIR = _PLUGIN_ROOT / "skills"

def _read_skill_frontmatter(skill_dir: Path) -> dict:
    """Read name / description / allowed-tools / version from a skill's
    SKILL.md frontmatter. Stdlib-only line scan — keeps the dispatcher
    zero-dep."""
    import re as _re
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return {}
    text = skill_md.read_text(encoding="utf-8")
    m = _re.match(r"---\n(.*?)\n---", text, _re.DOTALL)
    if not m:
        return {}
    fm: dict = {}
    for line in m.group(1).splitlines():
        mm = _re.match(r"^([\w-]+):\s*(.+)$", line)
        if mm:
            fm[mm.group(1)] = mm.group(2).strip()
    return fm

def _read_codex_short_description(skill_dir: Path) -> str:
    """Pull `short_description` from skills/<X>/agents/openai.yaml if
    present — Codex's 1-line agent label."""
    import re as _re
    oy = skill_dir / "agents" / "openai.yaml"
    if not oy.is_file():
        return ""
    text = oy.read_text(encoding="utf-8")
    m = _re.search(r'short_description:\s*"([^"]+)"', text)
    return m.group(1) if m else ""

def _default_tools_for(skill: str, skill_fm: dict) -> str:
    """Pick a sensible default tool surface based on skill family.

    Heuristic — author can edit after scaffolding. Conservative read-only
    default; expand to Write/Edit when the skill name signals mutation."""
    # Honor declared allowed-tools first (some Claude skills already have it)
    if "allowed-tools" in skill_fm:
        return skill_fm["allowed-tools"]
    mutating_signals = ("fix", "implement", "execute", "create", "write",
                        "extract", "edit", "refactor", "migrate")
    if any(sig in skill.lower() for sig in mutating_signals):
        return "[Read, Edit, Write, Glob, Grep, Bash]"
    research_signals = ("research", "claude-docs", "knowledge", "context7")
    if any(sig in skill.lower() for sig in research_signals):
        return "[Read, Grep, WebFetch, WebSearch]"
    return "[Read, Glob, Grep, Bash]"  # read-only default

def cmd_agents_scaffold(args: argparse.Namespace) -> int:
    """Generate a Claude subagent stub from a skill's metadata."""
    skill_dir = _SKILLS_DIR / args.skill
    if not skill_dir.is_dir():
        sys.stderr.write(f"kaizen agents scaffold: skill '{args.skill}' not found "
                          f"at {skill_dir}\n")
        return 2
    fm = _read_skill_frontmatter(skill_dir)
    codex_short = _read_codex_short_description(skill_dir)
    name = f"kaizen-{args.skill}"
    desc = fm.get("description", "(no description)")
    if codex_short:
        desc = f"{codex_short}. {desc}"
    tools = _default_tools_for(args.skill, fm)
    stub = (
        f"---\n"
        f"name: {name}\n"
        f"description: {desc}\n"
        f"tools: {tools}\n"
        f"model: inherit\n"
        f"---\n"
        f"\n"
        f"# {name}\n"
        f"\n"
        f"Spawned to perform the `{args.skill}` skill as an isolated subagent.\n"
        f"\n"
        f"## What you do\n"
        f"\n"
        f"<fill in from SKILL.md `## What this skill does` — see\n"
        f"`plugins/kaizen/skills/{args.skill}/SKILL.md`>\n"
        f"\n"
        f"## What you DON'T do\n"
        f"\n"
        f"- Don't operate outside the declared tool surface.\n"
        f"- Don't speculate — report what is, not what should be.\n"
        f"\n"
        f"## Pairing\n"
        f"\n"
        f"<list sibling agents that compose with this one>\n"
    )
    if args.out:
        Path(args.out).write_text(stub, encoding="utf-8")
        print(f"wrote agent stub → {args.out}", file=sys.stderr)
    else:
        print(stub, end="")
    return 0

def cmd_agents(args: argparse.Namespace) -> int:
    if args.subcmd == "scaffold":
        return cmd_agents_scaffold(args)
    # Default: list existing Claude subagents
    agents = sorted(_AGENTS_DIR.glob("*.md"))
    if args.json:
        import json as _json
        rows = []
        for a in agents:
            fm = _read_skill_frontmatter(a.parent)  # not exactly — let's parse inline
            rows.append({"name": a.stem, "path": str(a)})
        print(_json.dumps(rows, indent=2))
        return 0
    print(f"kaizen Claude subagents ({len(agents)} total)\n")
    for a in agents:
        print(f"  {a.stem}")
    return 0

def _dispatch(sub: str, sub_args: list[str], use_subprocess: bool = False) -> int:
    """Resolve sub → bin/kaizen-<sub> and exec/subprocess it."""
    wrapper = _BIN_DIR / f"kaizen-{sub}"
    if not wrapper.is_file() or not os.access(wrapper, os.X_OK):
        sys.stderr.write(f"kaizen: unknown subcommand '{sub}'\n")
        sys.stderr.write("Run 'kaizen list' to see available subcommands.\n")
        return 2
    argv = [str(wrapper), *sub_args]
    if use_subprocess:
        return subprocess.run(argv).returncode
    # execv: replace this process — preserves exit code via the OS.
    os.execv(str(wrapper), argv)
    return 0  # unreachable

def _emit_trace_event(phase: str, sub: str, sub_args: list[str],
                      duration_ms: int | None = None,
                      exit_code: int | None = None) -> None:
    """Best-effort: write a kaizen-trace event. Silent on any failure
    so the dispatcher never blocks on telemetry."""
    if not trace_py.is_file():
        return
    payload = {
        "phase": phase,
        "subcommand": sub,
        "args": sub_args[:10],  # cap to keep events small
    }
    if duration_ms is not None:
        payload["duration_ms"] = duration_ms
    if exit_code is not None:
        payload["exit_code"] = exit_code
    try:
        subprocess.run(
            [sys.executable, str(trace_py), "write", "kaizen-cli", json.dumps(payload)],
            timeout=2,
            capture_output=True,
        )
    except (subprocess.TimeoutExpired, OSError):
        pass

def main(argv: list[str]) -> int:
    # Top-level flags (--time, --trace) consumed before subcommand
    use_time = False
    use_trace = False
    while argv and argv[0] in ("--time", "--trace"):
        flag = argv.pop(0)
        if flag == "--time":
            use_time = True
        elif flag == "--trace":
            use_trace = True

    if not argv:
        return cmd_list(argparse.Namespace(json=False))

    # Built-in subcommands handled first
    cmd = argv[0]
    if cmd == "list":
        parser = argparse.ArgumentParser(prog="kaizen list")
        parser.add_argument("--json", action="store_true")
        ns = parser.parse_args(argv[1:])
        return cmd_list(ns)
    if cmd == "help":
        parser = argparse.ArgumentParser(prog="kaizen help")
        parser.add_argument("subcommand")
        ns = parser.parse_args(argv[1:])
        return cmd_help(ns)
    if cmd == "commands":
        parser = argparse.ArgumentParser(prog="kaizen commands")
        parser.add_argument("subcmd", nargs="?", default="list",
                            choices=["list", "show"])
        parser.add_argument("name", nargs="?", default=None,
                            help="slash command name (for `show`)")
        parser.add_argument("--json", action="store_true")
        ns = parser.parse_args(argv[1:])
        if ns.subcmd == "show" and not ns.name:
            sys.stderr.write("kaizen commands show: needs <name>\n")
            return 2
        return cmd_commands(ns)
    if cmd in ("version", "--version", "-v"):
        return cmd_version(argparse.Namespace())
    if cmd == "agents":
        parser = argparse.ArgumentParser(prog="kaizen agents")
        parser.add_argument("subcmd", nargs="?", default="list",
                             choices=["list", "scaffold"])
        parser.add_argument("skill", nargs="?", default=None,
                             help="skill name (for scaffold)")
        parser.add_argument("--out", metavar="FILE",
                             help="write the stub to FILE (default: stdout)")
        parser.add_argument("--json", action="store_true")
        ns = parser.parse_args(argv[1:])
        if ns.subcmd == "scaffold" and not ns.skill:
            sys.stderr.write("kaizen agents scaffold: needs <skill>\n")
            return 2
        return cmd_agents(ns)
    if cmd == "patterns":
        parser = argparse.ArgumentParser(prog="kaizen patterns")
        parser.add_argument("--json", action="store_true",
                             help="machine-readable catalog dump")
        parser.add_argument("--refresh", action="store_true",
                             help="re-run detect: recipes + update count fields in cli-patterns.yaml")
        parser.add_argument("--dry-run", action="store_true",
                             help="with --refresh: report drift without writing")
        ns = parser.parse_args(argv[1:])
        return cmd_patterns(ns)
    if cmd in ("-h", "--help"):
        sys.stderr.write(__doc__ or "")
        return 0

    # Subcommand dispatch
    sub = cmd
    sub_args = argv[1:]

    if use_time or use_trace:
        # Subprocess path — need a return code post-exec
        if use_trace:
            _emit_trace_event("start", sub, sub_args)
        t0 = time.monotonic()
        rc = _dispatch(sub, sub_args, use_subprocess=True)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if use_time:
            sys.stderr.write(
                f"\nkaizen-cli: '{sub}' completed in {elapsed_ms}ms (exit={rc})\n"
            )
        if use_trace:
            _emit_trace_event("end", sub, sub_args,
                              duration_ms=elapsed_ms, exit_code=rc)
        return rc

    # Vanilla dispatch — execv replaces this process
    return _dispatch(sub, sub_args, use_subprocess=False)

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
