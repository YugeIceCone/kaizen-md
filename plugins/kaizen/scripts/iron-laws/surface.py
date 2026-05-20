#!/usr/bin/env python3
"""kaizen surface — unified MCP + hook registry / validator.

One CLI to manage the kaizen plugin's extension surface (MCP tools +
event hooks). Fixes the audit's F-002 / F-010 (orphan / mis-located
hook configs) and gives future audits a single-shot health check.

## CLI

  surface.py list                    # enumerate MCP tools + hooks
  surface.py validate                # find orphans, drift, missing entries
  surface.py diff                    # what `install` would change
  surface.py install                 # regenerate hooks.json + .mcp.json
                                       from canonical state (DESTRUCTIVE
                                       — use --dry-run first)

  surface.py validate --json         # machine-readable verdict
  surface.py list --kind hooks       # filter to one surface
  surface.py list --kind mcp

## Exit

  0 — clean
  1 — validation failures
  2 — invocation error

## Canonical sources

  MCP tools     :  scripts/mcp/gateway.py::SUBSERVERS
                   + each {name}_mcp.py exporting `mcp` FastMCP server
  MCP register  :  .mcp.json (single entry: `kaizen` → gateway.py)
  Hook scripts  :  hooks/claude/*.sh (excluding _*-prefixed helpers)
  Hook register :  hooks/hooks.json
  Permissions   :  .claude-plugin/plugin.json::permissions.allow[]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PLUGIN_ROOT = _SCRIPT_DIR.parent.parent  # scripts/iron-laws → plugins/kaizen/

# ─── Surface inventory primitives ───────────────────────────────────────

@dataclass
class HookEntry:
    event: str
    matcher: str
    command: str          # full command string
    script: str           # extracted script path (relative to PLUGIN_ROOT)
    timeout: int | None = None

@dataclass
class McpServer:
    name: str             # e.g. "gatekeeper"
    module: str           # e.g. "gatekeeper_mcp"
    script_path: str      # e.g. "scripts/mcp/gatekeeper_mcp.py"
    tool_count: int       # # of @mcp.tool() decorators
    in_curated_core: list[str] = field(default_factory=list)  # tools from this server in CURATED_CORE

@dataclass
class Finding:
    severity: str         # error | warn | info
    surface: str          # hooks | mcp | both
    rule_id: str
    message: str
    path: str = ""

# ─── Hook surface ───────────────────────────────────────────────────────

def _hooks_json() -> dict:
    p = _PLUGIN_ROOT / "hooks" / "hooks.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text()).get("hooks", {})

def list_hook_entries() -> list[HookEntry]:
    """All hooks registered in hooks.json, in declaration order."""
    out = []
    for event, configs in _hooks_json().items():
        if not isinstance(configs, list):
            continue
        for cfg in configs:
            matcher = cfg.get("matcher", "*")
            for h in cfg.get("hooks", []):
                cmd = h.get("command", "")
                # extract the script path: anything matching .../hooks/claude/SCRIPT or .../scripts/SCRIPT
                m = re.search(r"\$\{CLAUDE_PLUGIN_ROOT\}/(\S+)", cmd)
                script = m.group(1) if m else cmd[:80]
                out.append(HookEntry(
                    event=event, matcher=matcher, command=cmd,
                    script=script, timeout=h.get("timeout"),
                ))
    return out

def list_hook_files() -> list[str]:
    """All shell + python scripts under hooks/claude/, excluding _*-prefixed."""
    d = _PLUGIN_ROOT / "hooks" / "claude"
    if not d.is_dir():
        return []
    return sorted(
        f.name for f in d.iterdir()
        if f.is_file()
        and not f.name.startswith("_")
        and f.suffix in (".sh", ".py")
    )

# ─── MCP surface ────────────────────────────────────────────────────────

def _gateway_subservers() -> list[tuple[str, str]]:
    """Parse SUBSERVERS list from gateway.py via lightweight regex.

    Reads the canonical at scripts/mcp/gateway.py."""
    gw = _PLUGIN_ROOT / "scripts" / "mcp" / "gateway.py"
    if not gw.exists():
        return []
    text = gw.read_text()
    m = re.search(
        r"SUBSERVERS\s*:\s*list\[tuple\[str, str\]\]\s*=\s*\[(.+?)\]",
        text, re.DOTALL,
    )
    if not m:
        return []
    return re.findall(r'\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)', m.group(1))

def _curated_core() -> list[str]:
    """Parse CURATED_CORE list from gateway.py (canonical at scripts/mcp/)."""
    gw = _PLUGIN_ROOT / "scripts" / "mcp" / "gateway.py"
    if not gw.exists():
        return []
    text = gw.read_text()
    m = re.search(
        r"CURATED_CORE\s*:\s*list\[str\]\s*=\s*\[(.+?)\n\]",
        text, re.DOTALL,
    )
    if not m:
        return []
    return re.findall(r'"([^"]+)"', m.group(1))

def _tool_count(script_path: Path) -> int:
    """Count @<name>.tool() decorators in an MCP module."""
    if not script_path.is_file():
        return 0
    text = script_path.read_text(errors="ignore")
    return len(re.findall(r"@\w+\.tool\(", text))

def list_mcp_servers() -> list[McpServer]:
    core = _curated_core()
    out = []
    # Post-DOMAIN-4: MCP scripts live at plugins/kaizen/scripts/mcp/
    _MCP_DIR = _PLUGIN_ROOT / "scripts" / "mcp"
    for name, module in _gateway_subservers():
        script_path = _MCP_DIR / f"{module}.py"
        if not script_path.is_file():
            # Fallback to legacy location for any not-yet-migrated MCP
            script_path = _SCRIPT_DIR / f"{module}.py"
        rel = str(script_path.relative_to(_PLUGIN_ROOT)) if script_path.exists() else f"scripts/mcp/{module}.py"
        count = _tool_count(script_path)
        in_core = []
        # Heuristic: a tool from this server is in core if the tool name
        # appears in CURATED_CORE — we can't introspect without running
        # FastMCP, so this is a best-effort filename match.
        prefix = name.replace("-", "_") + "_"
        in_core = [t for t in core if t.startswith(prefix) or t == prefix.rstrip("_")]
        out.append(McpServer(
            name=name, module=module, script_path=rel,
            tool_count=count, in_curated_core=in_core,
        ))
    return out

# ─── Validation ─────────────────────────────────────────────────────────

def _registered_hook_scripts() -> set[str]:
    """Set of script basenames (e.g. 'pretooluse-bash-gate.sh') that
    appear in hooks.json."""
    out = set()
    for h in list_hook_entries():
        out.add(Path(h.script).name)
    return out

def validate() -> list[Finding]:
    findings: list[Finding] = []

    # --- HOOKS: orphan scripts (on disk but not registered) ---
    on_disk = set(list_hook_files())
    registered = _registered_hook_scripts()
    # Filter out scripts not under hooks/claude/ (e.g. python3 ${...}/scripts/session_start.py)
    on_disk_in_claude = {n for n in on_disk if n.endswith((".sh", ".py"))}
    for orphan in sorted(on_disk_in_claude - registered):
        findings.append(Finding(
            severity="warn", surface="hooks", rule_id="orphan-hook-script",
            message=f"{orphan} exists in hooks/claude/ but isn't registered in hooks.json",
            path=f"hooks/claude/{orphan}",
        ))

    # --- HOOKS: registered scripts missing on disk ---
    on_disk_full = {f.name for f in (_PLUGIN_ROOT / "hooks" / "claude").iterdir()} \
        if (_PLUGIN_ROOT / "hooks" / "claude").is_dir() else set()
    for h in list_hook_entries():
        sname = Path(h.script).name
        if "/hooks/claude/" in h.script and sname not in on_disk_full:
            findings.append(Finding(
                severity="error", surface="hooks", rule_id="missing-hook-script",
                message=f"{h.event}/{h.matcher} references {sname} but the file is missing",
                path=h.script,
            ))

    # --- MCP: sub-server file missing ---
    for s in list_mcp_servers():
        script_full = _PLUGIN_ROOT / s.script_path
        if not script_full.exists():
            findings.append(Finding(
                severity="error", surface="mcp", rule_id="missing-mcp-module",
                message=f"gateway SUBSERVERS lists '{s.name}' → {s.module}.py but the file is missing",
                path=s.script_path,
            ))
        elif s.tool_count == 0:
            findings.append(Finding(
                severity="warn", surface="mcp", rule_id="mcp-no-tools",
                message=f"{s.name} ({s.module}.py) declares no @mcp.tool() functions",
                path=s.script_path,
            ))

    # --- MCP: sub-server NOT in gateway despite *_mcp.py existing ---
    declared_modules = {s.module for s in list_mcp_servers()}
    for mcp_file in (_PLUGIN_ROOT / "skills" / "workflow" / "scripts").glob("*_mcp.py"):
        if mcp_file.stem.startswith("test_"):
            continue
        if mcp_file.stem not in declared_modules:
            findings.append(Finding(
                severity="warn", surface="mcp", rule_id="unmounted-mcp-server",
                message=f"{mcp_file.name} exists but isn't mounted in gateway.py::SUBSERVERS",
                path=str(mcp_file.relative_to(_PLUGIN_ROOT)),
            ))

    # --- CURATED_CORE: members reference non-existent tools ---
    # (best effort — we can't import the gateway without dependencies, but
    # we can at least check the curated core has non-empty content)
    core = _curated_core()
    if not core:
        findings.append(Finding(
            severity="warn", surface="mcp", rule_id="empty-curated-core",
            message="CURATED_CORE in gateway.py parses as empty (regex miss?)",
            path="scripts/mcp/gateway.py",
        ))

    # --- PERMISSIONS: every script invocable via Bash should have an allow ---
    pj = _PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
    if pj.exists():
        try:
            allow = json.loads(pj.read_text()).get("permissions", {}).get("allow", [])
            blob = "\n".join(allow)
            # A wildcard `Bash(... scripts/*/*.py:*)` covers every
            # per-module *.py — recognize it before flagging individuals.
            has_wildcard_uv = "scripts/*/*.py" in blob and "uv run --script" in blob
            has_wildcard_py = "scripts/*/*.py" in blob and "python3" in blob
            for s in list_mcp_servers():
                module_name = Path(s.module + ".py").name
                if module_name in blob:
                    continue  # explicit entry
                if has_wildcard_uv or has_wildcard_py:
                    continue  # wildcard covers it
                findings.append(Finding(
                    severity="warn", surface="mcp", rule_id="missing-permission",
                    message=f"{module_name} has no matching plugin.json permission entry "
                            f"(no explicit + no wildcard)",
                    path=".claude-plugin/plugin.json",
                ))
        except json.JSONDecodeError:
            findings.append(Finding(
                severity="error", surface="both", rule_id="plugin-json-invalid",
                message="plugin.json is not valid JSON",
                path=".claude-plugin/plugin.json",
            ))

    return findings

# ─── Renderers ──────────────────────────────────────────────────────────

def render_list_text(servers: list[McpServer], hooks: list[HookEntry], kind: str = "both") -> str:
    out = []
    if kind in ("mcp", "both"):
        out.append("─── MCP sub-servers ───")
        total_tools = sum(s.tool_count for s in servers)
        for s in servers:
            core = " ★" if s.in_curated_core else ""
            out.append(f"  {s.name:14s} {s.tool_count:3d} tools  {s.script_path}{core}")
        out.append(f"  TOTAL: {len(servers)} servers, {total_tools} tools")
        out.append("")
    if kind in ("hooks", "both"):
        out.append("─── Hooks ───")
        for h in hooks:
            t = f" t={h.timeout}s" if h.timeout else ""
            out.append(f"  {h.event:18s} matcher={h.matcher:10s} {Path(h.script).name}{t}")
        out.append(f"  TOTAL: {len(hooks)} hook registrations")
    return "\n".join(out)

def render_validate_text(findings: list[Finding]) -> str:
    if not findings:
        return "kaizen surface: clean (no findings)"
    counts = {}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    summary = ", ".join(f"{s}={n}" for s, n in sorted(counts.items()))
    out = [f"kaizen surface: {len(findings)} finding(s) ({summary})\n"]
    for f in findings:
        out.append(f"  [{f.severity:5s}] {f.surface:5s} {f.rule_id}  {f.path}\n"
                   f"    {f.message}\n")
    return "".join(out)

# ─── CLI ────────────────────────────────────────────────────────────────

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="kaizen-surface")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="enumerate MCP servers + hooks")
    p_list.add_argument("--kind", choices=["mcp", "hooks", "both"], default="both")
    p_list.add_argument("--json", action="store_true")

    p_val = sub.add_parser("validate", help="find orphans, drift, missing entries")
    p_val.add_argument("--json", action="store_true")

    p_diff = sub.add_parser("diff", help="show what `install` would change (not yet implemented)")
    p_install = sub.add_parser("install", help="regenerate hooks.json/.mcp.json (not yet implemented)")
    p_install.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)

    _here = Path(__file__).resolve().parent
    sys.path.insert(0, str(_here))
    sys.path.insert(0, str(_here.parent / "io"))
    import _envelope  # peer module — must exist

    if args.cmd == "list":
        servers = list_mcp_servers()
        hooks = list_hook_entries()
        if args.json:
            _envelope.emit(
                tool="kaizen-surface", tool_version="1.0.0",
                data={
                    "mcp_servers": [asdict(s) for s in servers],
                    "hooks": [asdict(h) for h in hooks],
                },
                counts={"mcp_servers": len(servers), "hooks": len(hooks)},
                argv=argv,
            )
        else:
            print(render_list_text(servers, hooks, kind=args.kind))
        return 0

    if args.cmd == "validate":
        findings = validate()
        if args.json:
            counts: dict[str, int] = {}
            for f in findings:
                counts[f.severity] = counts.get(f.severity, 0) + 1
            verdict = "red" if counts.get("error") else (
                "yellow" if counts.get("warn") else "green"
            )
            _envelope.emit(
                tool="kaizen-surface", tool_version="1.0.0",
                data={"findings": [asdict(f) for f in findings]},
                verdict=verdict, counts=counts, argv=argv,
            )
        else:
            print(render_validate_text(findings))
        return 1 if any(f.severity == "error" for f in findings) else 0

    if args.cmd in ("diff", "install"):
        sys.stderr.write(f"surface.py {args.cmd}: not yet implemented — "
                         "use `validate` to see drift; edit hooks.json + gateway.py manually for now\n")
        return 2

    parser.print_help()
    return 2

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
