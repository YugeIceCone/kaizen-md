---
name: surface
description: "MCP+hooks registry. `list` enumerates servers + hooks; `validate` flags drift between gateway / hooks.json / .mcp.json / plugin.json."
argument-hint: "[list|validate] [--kind mcp|hooks|both] [--json]"
---

# /kaizen:surface

Unified registry + validator for the kaizen plugin's extension surface (MCP tools + event hooks).

Closes audit-findings F-002 (orphan `karpathy-gate.sh`) and F-010 (Codex `hooks.json` mis-located) by giving every future audit a single command that surfaces drift between what's declared and what's on disk.

## Subcommands

### `list` — enumerate the surface

```
/kaizen:surface list                # both — 22 MCP servers + 18 hooks
/kaizen:surface list --kind mcp     # only MCP
/kaizen:surface list --kind hooks   # only hooks
/kaizen:surface list --json         # machine-readable
```

MCP entries show: name · tool_count · script path · ★ if any tool is in `CURATED_CORE`.

Hook entries show: event · matcher · script · timeout.

### `validate` — find drift

```
/kaizen:surface validate            # text report; exit 1 on errors
/kaizen:surface validate --json     # array of Finding objects
```

Rules checked:

| Rule id | Severity | What it catches |
|---|---|---|
| `orphan-hook-script` | warn | Script in `hooks/claude/` but not registered in `hooks.json` |
| `missing-hook-script` | error | Registered in `hooks.json` but missing from disk |
| `missing-mcp-module` | error | Listed in `gateway.py::SUBSERVERS` but the `_mcp.py` file is missing |
| `mcp-no-tools` | warn | `_mcp.py` declares zero `@mcp.tool()` decorators |
| `unmounted-mcp-server` | warn | `*_mcp.py` exists but isn't in `gateway.py::SUBSERVERS` |
| `empty-curated-core` | warn | `CURATED_CORE` parses as empty |
| `missing-permission` | warn | MCP module has no matching `plugin.json` permission (explicit OR wildcard) |
| `plugin-json-invalid` | error | `plugin.json` isn't valid JSON |

### `diff` / `install` (placeholder — not yet implemented)

Reserved for the future "regenerate hooks.json + permissions from canonical state" workflow. Current use: edit `hooks.json` + `gateway.py::SUBSERVERS` + `plugin.json` manually; re-run `validate` to confirm.

## Canonical sources of truth

| Surface | Source |
|---|---|
| MCP servers | `skills/workflow/scripts/gateway.py::SUBSERVERS` + per-module `*_mcp.py` |
| MCP register | `.mcp.json` (single entry: `kaizen` → `gateway.py`) |
| Hook scripts | `hooks/claude/*.sh` (excluding `_*`-prefixed helpers) |
| Hook register | `hooks/hooks.json` |
| Permissions | `.claude-plugin/plugin.json::permissions.allow[]` |

## Behind the scenes

`scripts/iron-laws/surface.py` is the entry point. Inventory primitives:

- `list_hook_entries() → list[HookEntry]` — parses `hooks/hooks.json`
- `list_hook_files() → list[str]` — scans `hooks/claude/`
- `list_mcp_servers() → list[McpServer]` — parses `gateway.py::SUBSERVERS` + counts `@mcp.tool()` decorators per module file

Adding a new validation rule: append a new finding-emitter to `validate()`. No schema needed; `Finding` is the canonical shape.

## Comparison

| Tool | What it covers |
|---|---|
| `/kaizen:gatekeeper` | Aggregates iron-laws + etu + karpathy + validator findings about CODE |
| `/kaizen:surface` | Drift in the EXTENSION REGISTRATION (hooks + MCP) — different layer |
| `/kaizen:iron-laws check` | One specific class of code findings — narrower than gatekeeper |
| `validate.py` | Plugin-development feature validator — different angle (feature shape) |

Three complementary lenses on plugin health.
