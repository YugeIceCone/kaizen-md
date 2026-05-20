# consolidated-cli-parent: export
"""kaizen-export — port the plugin's skills / commands / agents / MCPs
to a sibling AI-CLI's expected layout.

Usage:
    python3 export_target.py --target codex --out ~/.codex
    python3 export_target.py --target codex --out /tmp/out --dry-run

Current targets:
    codex   — Codex CLI (~/.codex/{skills,commands,agents,config.toml})

Future targets sketched in the docstring but not implemented yet:
    cursor, continue, aider — Cursor / Continue / Aider variants.

Substitution rules applied to every emitted file:
    ${CLAUDE_PLUGIN_ROOT}  →  ${KAIZEN_PLUGIN_ROOT}

The exporter never mutates the source plugin — it reads + writes to
``--out``. Each emitted file ends with a one-line provenance footer
identifying the source path under the kaizen plugin tree.

## Codex layout produced

    <out>/
        skills/<name>.md          # CC progressive-disclosure markdown
        commands/<name>.md        # slash-command bodies
        agents/<name>.toml        # YAML frontmatter → TOML
        config.toml               # mcp_servers block + plugin_root hint
        README.md                 # install instructions for the target
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

# Optional dep: PyYAML for frontmatter parsing. We mirror _yaml.py's
# graceful-degradation behavior — fail loudly on import so the user
# sees the missing dep.
try:
    import yaml
except ImportError:  # pragma: no cover — exercised manually
    sys.stderr.write("kaizen-export: PyYAML required (pip install pyyaml)\n")
    sys.exit(1)

# Public for tests.
PLUGIN_VAR_FROM = "${CLAUDE_PLUGIN_ROOT}"
PLUGIN_VAR_TO = "${KAIZEN_PLUGIN_ROOT}"
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
PROVENANCE_PREFIX = "<!-- kaizen-export source:"

# ─── Frontmatter + path substitution ─────────────────────────────────

@dataclass
class Frontmatter:
    """Parsed YAML frontmatter + the trailing body."""

    data: dict
    body: str

def parse_frontmatter(text: str) -> Frontmatter:
    """Split ``---\\n…\\n---\\n<body>`` into ``(data, body)``.

    Files without frontmatter — or with malformed YAML inside the
    fence — return ``Frontmatter({}, text)`` so callers can treat them
    uniformly. The ``validate_bundle`` step distinguishes the two cases
    by checking whether the source text starts with ``---``.
    """
    m = FRONTMATTER_RE.match(text)
    if not m:
        return Frontmatter(data={}, body=text)
    raw, body = m.group(1), m.group(2)
    try:
        parsed = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        return Frontmatter(data={}, body=text)
    if not isinstance(parsed, dict):
        return Frontmatter(data={}, body=text)
    return Frontmatter(data=parsed, body=body)

def substitute_plugin_root(text: str) -> str:
    """Replace ``${CLAUDE_PLUGIN_ROOT}`` with ``${KAIZEN_PLUGIN_ROOT}``."""
    return text.replace(PLUGIN_VAR_FROM, PLUGIN_VAR_TO)

def render_frontmatter(data: dict, body: str) -> str:
    """Re-emit a YAML-frontmatter markdown file."""
    if not data:
        return body
    rendered = yaml.safe_dump(data, sort_keys=False, default_flow_style=False).rstrip()
    return f"---\n{rendered}\n---\n{body}"

# ─── TOML mini-emitter (Codex agent + MCP shape) ─────────────────────
# Codex configs are flat tables; hand-rolling avoids pulling tomli_w
# in as a new dep. Restricted to: str, int, float, bool, list[str].

def _toml_escape_string(value: str) -> str:
    """Emit a TOML basic-string literal. Multi-line strings use ``\"\"\"``."""
    if "\n" in value:
        # Multi-line basic string: escape backslashes + closing-triple-quote.
        escaped = value.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
        return f'"""\n{escaped}\n"""'
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'

def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return _toml_escape_string(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise TypeError(f"unsupported TOML value type: {type(value).__name__}")

def emit_toml_table(table_name: str | None, fields: dict) -> str:
    """Render a single TOML table (header + ``key = value`` lines)."""
    lines: list[str] = []
    if table_name:
        lines.append(f"[{table_name}]")
    for key, value in fields.items():
        if value is None:
            continue
        lines.append(f"{key} = {_toml_value(value)}")
    return "\n".join(lines)

# ─── Codex shape converters ──────────────────────────────────────────

def agent_md_to_toml(md_text: str) -> str:
    """Convert a kaizen agent's YAML-frontmatter markdown to a Codex
    agent TOML file.

    Mapping:
        name        → nickname
        description → description (multi-line basic string)
        tools       → tools  (preserved as list)
        model       → model  (preserved if present)
    All other frontmatter keys pass through under their original name.
    The markdown body after the frontmatter is dropped — Codex agents
    only consume the frontmatter; the body is documentation for humans
    and gets reattached as a TOML comment block.
    """
    fm = parse_frontmatter(md_text)
    fields: dict = {}

    name = fm.data.pop("name", None)
    if name:
        fields["nickname"] = name

    desc = fm.data.pop("description", None)
    if desc:
        fields["description"] = desc.strip() if isinstance(desc, str) else str(desc)

    # Pass through known keys explicitly so they appear in a predictable order.
    for key in ("model", "tools", "sandbox_mode", "model_reasoning_effort"):
        if key in fm.data:
            fields[key] = fm.data.pop(key)

    # Anything else passes through unchanged.
    for k, v in fm.data.items():
        fields[k] = v

    body = emit_toml_table(None, fields)

    if fm.body.strip():
        # Reattach the original body as a TOML comment block for human readers.
        commented = "\n".join("# " + line if line else "#" for line in fm.body.splitlines())
        return f"{body}\n\n# ─── source body ─────────────────────────────────────────\n{commented}\n"
    return body + "\n"

def mcp_servers_to_toml(mcp_json: dict) -> str:
    """Render ``.mcp.json`` as Codex-compatible TOML.

    Codex shape:
        [mcp_servers.<name>]
        command = "..."
        args = [...]
    """
    servers = mcp_json.get("mcpServers", {})
    tables: list[str] = []
    for name, cfg in servers.items():
        fields: dict = {"command": cfg.get("command", "")}
        if cfg.get("args"):
            fields["args"] = [substitute_plugin_root(a) for a in cfg["args"]]
        if cfg.get("env"):
            fields["env"] = cfg["env"]
        tables.append(emit_toml_table(f"mcp_servers.{name}", fields))
    return "\n\n".join(tables) + "\n"

# ─── Exporter ────────────────────────────────────────────────────────

@dataclass
class ExportResult:
    """What ``run()`` produced — useful for the CLI summary + tests."""

    skills: list[Path]
    commands: list[Path]
    agents: list[Path]
    config_toml: Path | None
    readme: Path | None

class CodexExporter:
    """Walk the kaizen plugin and emit Codex-shaped layout under ``out_dir``."""

    def __init__(self, plugin_root: Path, out_dir: Path, dry_run: bool = False):
        self.plugin_root = plugin_root
        self.out_dir = out_dir
        self.dry_run = dry_run

    # — file IO with dry-run support —

    def _write(self, dest: Path, text: str) -> Path:
        if self.dry_run:
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        return dest

    def _provenance(self, source: Path, comment_prefix: str = "<!--") -> str:
        rel = source.relative_to(self.plugin_root)
        close = "-->" if comment_prefix == "<!--" else ""
        return f"\n\n{comment_prefix} kaizen-export source: {rel} {close}\n".rstrip() + "\n"

    # — per-asset-class —

    def export_skills(self) -> list[Path]:
        out: list[Path] = []
        skills_dir = self.plugin_root / "skills"
        if not skills_dir.is_dir():
            return out
        for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
            text = skill_md.read_text(encoding="utf-8")
            transformed = substitute_plugin_root(text)
            name = skill_md.parent.name
            dest = self.out_dir / "skills" / f"{name}.md"
            out.append(self._write(dest, transformed + self._provenance(skill_md)))
        return out

    def export_commands(self) -> list[Path]:
        out: list[Path] = []
        commands_dir = self.plugin_root / "commands"
        if not commands_dir.is_dir():
            return out
        for cmd_md in sorted(commands_dir.glob("*.md")):
            text = cmd_md.read_text(encoding="utf-8")
            transformed = substitute_plugin_root(text)
            dest = self.out_dir / "commands" / cmd_md.name
            out.append(self._write(dest, transformed + self._provenance(cmd_md)))
        return out

    def export_agents(self) -> list[Path]:
        out: list[Path] = []
        agents_dir = self.plugin_root / "agents"
        if not agents_dir.is_dir():
            return out
        for agent_md in sorted(agents_dir.glob("*.md")):
            text = agent_md.read_text(encoding="utf-8")
            transformed_md = substitute_plugin_root(text)
            toml_body = agent_md_to_toml(transformed_md)
            rel = agent_md.relative_to(self.plugin_root)
            dest = self.out_dir / "agents" / f"{agent_md.stem}.toml"
            footer = f"\n# kaizen-export source: {rel}\n"
            out.append(self._write(dest, toml_body + footer))
        return out

    def export_mcp(self) -> Path | None:
        mcp_path = self.plugin_root / ".mcp.json"
        if not mcp_path.is_file():
            return None
        import json
        data = json.loads(mcp_path.read_text(encoding="utf-8"))
        body = mcp_servers_to_toml(data)
        dest = self.out_dir / "config.toml"
        return self._write(dest, body + "\n# kaizen-export source: .mcp.json\n")

    def export_readme(self) -> Path:
        body = self._readme_text()
        return self._write(self.out_dir / "README.md", body)

    def _readme_text(self) -> str:
        return (
            "# kaizen-export — Codex CLI bundle\n\n"
            "Generated by `bin/kaizen-export --target codex`. Drop the\n"
            "directory contents into your Codex CLI config location (typically\n"
            "`~/.codex/`):\n\n"
            "```bash\n"
            "cp -r skills    ~/.codex/skills/\n"
            "cp -r commands  ~/.codex/commands/\n"
            "cp -r agents    ~/.codex/agents/\n"
            "# config.toml: merge the [mcp_servers.*] tables into ~/.codex/config.toml\n"
            "```\n\n"
            "## Required env\n\n"
            "Set `KAIZEN_PLUGIN_ROOT` to your kaizen plugin install path. All\n"
            "paths inside skills / commands / agents reference this var (the\n"
            "exporter rewrites `${CLAUDE_PLUGIN_ROOT}` → `${KAIZEN_PLUGIN_ROOT}`).\n\n"
            "```bash\n"
            "export KAIZEN_PLUGIN_ROOT=\"$HOME/.claude/local-marketplaces/kaizen-md/plugins/kaizen\"\n"
            "```\n\n"
            "## Source\n\n"
            f"kaizen plugin: `{self.plugin_root}`\n"
        )

    # — orchestrator —

    def run(self) -> ExportResult:
        return ExportResult(
            skills=self.export_skills(),
            commands=self.export_commands(),
            agents=self.export_agents(),
            config_toml=self.export_mcp(),
            readme=self.export_readme(),
        )

# ─── CLI ─────────────────────────────────────────────────────────────

TARGETS = {"codex": CodexExporter}

# ─── Validate (re-parse the emitted bundle) ──────────────────────────

@dataclass
class ValidationReport:
    """Result of re-parsing an emitted bundle.

    TOML errors are encoder regressions — the exporter generated bad
    output. They count as failures (``ok`` becomes False).

    Frontmatter "warnings" cover *source* YAML quirks (e.g. unquoted
    colons in description text). The exporter passes frontmatter
    through verbatim, so these are pre-existing source issues, not
    exporter bugs — surfaced but non-fatal.
    """

    toml_files: int
    toml_errors: list[tuple[Path, str]]
    md_files: int
    md_frontmatter_warnings: list[tuple[Path, str]]

    @property
    def ok(self) -> bool:
        return not self.toml_errors

    def render(self, out_dir: Path) -> str:
        lines = [
            f"validate: {out_dir}",
            f"  toml files       = {self.toml_files} "
            f"({len(self.toml_errors)} errors)",
            f"  md  files        = {self.md_files} "
            f"({len(self.md_frontmatter_warnings)} frontmatter warnings)",
        ]
        for path, err in self.toml_errors:
            lines.append(f"    ! TOML   {path}: {err}")
        for path, err in self.md_frontmatter_warnings:
            lines.append(f"    ~ YAML   {path}: {err}")
        lines.append("  → " + ("PASS" if self.ok else "FAIL"))
        return "\n".join(lines)

def validate_bundle(out_dir: Path) -> ValidationReport:
    """Re-parse every .toml + every .md frontmatter under ``out_dir``.

    Catches encoder bugs where the exporter would have produced
    well-shaped-looking-but-invalid output (multi-line strings that
    escape incorrectly, lists that contain unsupported types, etc.).
    """
    try:
        import tomllib  # py3.11+
    except ImportError:  # pragma: no cover — tomllib bundled since 3.11
        tomllib = None  # type: ignore[assignment]

    toml_errors: list[tuple[Path, str]] = []
    md_warnings: list[tuple[Path, str]] = []
    toml_count = md_count = 0

    for path in sorted(out_dir.rglob("*.toml")):
        toml_count += 1
        if tomllib is None:
            continue
        try:
            with path.open("rb") as fh:
                tomllib.load(fh)
        except Exception as e:  # noqa: BLE001 — surface every parse error
            toml_errors.append((path.relative_to(out_dir), str(e)))

    for path in sorted(out_dir.rglob("*.md")):
        md_count += 1
        text = path.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(text)
        # Frontmatter is optional; we only flag *malformed* YAML, not
        # missing-frontmatter (already tolerant by design). Warning,
        # not error — the exporter passes frontmatter through verbatim
        # and isn't responsible for source-file YAML quality.
        if not fm.data and text.startswith("---"):
            md_warnings.append((path.relative_to(out_dir), "frontmatter present but unparseable"))

    return ValidationReport(toml_count, toml_errors, md_count, md_warnings)

# ─── CLI ─────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kaizen-export",
        description="Port kaizen skills/commands/agents/MCPs to a sibling AI-CLI's layout.",
    )
    p.add_argument(
        "--target",
        default="codex",
        choices=sorted(TARGETS),
        help="Which sibling CLI's layout to emit (default: codex).",
    )
    p.add_argument(
        "--out",
        type=Path,
        help="Output directory (will be created if missing). Required "
             "unless --validate is used standalone.",
    )
    p.add_argument(
        "--plugin-root",
        type=Path,
        default=None,
        help="Override source plugin root (defaults to the kaizen plugin "
             "containing this script).",
    )
    p.add_argument(
        "--clean",
        action="store_true",
        help="Remove existing files in --out before exporting.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Walk the plugin but write nothing — print the destination "
             "list to stdout.",
    )
    p.add_argument(
        "--validate",
        action="store_true",
        help="After (or instead of) exporting, re-parse the emitted "
             "bundle. Exit 1 if any TOML or YAML frontmatter is broken.",
    )
    return p

def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.out is None:
        sys.stderr.write("kaizen-export: --out is required\n")
        return 2

    # Resolve plugin root via the shared resolver.
    if args.plugin_root:
        plugin_root = args.plugin_root.resolve()
    else:
        _here = Path(__file__).resolve().parent
        sys.path.insert(0, str(_here))
        # _plugin_root.py deferred at legacy skills/workflow/scripts/.
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        import _bootstrap  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
        from _plugin_root import plugin_root as resolve  # noqa: E402
        plugin_root = resolve()

    if not (plugin_root / ".claude-plugin" / "plugin.json").is_file():
        sys.stderr.write(f"kaizen-export: not a kaizen plugin root: {plugin_root}\n")
        return 2

    out_dir = args.out.resolve()
    if args.clean and not args.dry_run and out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    exporter_cls = TARGETS[args.target]
    exporter = exporter_cls(plugin_root, out_dir, dry_run=args.dry_run)
    result = exporter.run()

    print(f"kaizen-export: target={args.target} plugin_root={plugin_root}")
    print(f"  → out_dir   = {out_dir}")
    print(f"  → skills    = {len(result.skills)}")
    print(f"  → commands  = {len(result.commands)}")
    print(f"  → agents    = {len(result.agents)}")
    print(f"  → config    = {'yes' if result.config_toml else 'no'}")
    print(f"  → readme    = {'yes' if result.readme else 'no'}")
    if args.dry_run:
        print("  (dry-run: nothing written)")

    if args.validate and not args.dry_run:
        report = validate_bundle(out_dir)
        print(report.render(out_dir))
        if not report.ok:
            return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())
