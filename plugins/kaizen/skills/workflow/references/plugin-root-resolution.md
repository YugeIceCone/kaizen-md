# Plugin-root resolution

How any kaizen script — bash or Python — locates the plugin's own
files. Single source of truth for cross-CLI portability.

## Resolution order

The resolver tries each strategy in order and returns the first hit:

1. **`$CLAUDE_PLUGIN_ROOT`** — set by Claude Code at hook-fire time and
   in any tool that substitutes `${CLAUDE_PLUGIN_ROOT}` in its launch
   command (MCP servers via `.mcp.json`, hook commands in `hooks.json`,
   slash commands in `commands/*.md`).
2. **`$KAIZEN_PLUGIN_ROOT`** — explicit env var for hosts that don't
   speak the Claude Code substitution protocol (Codex CLI, Cursor,
   Continue, Aider, ad-hoc shell invocations).
3. **Script-derived** — walk up from the resolver script's own
   location until a directory containing `.claude-plugin/plugin.json`
   is found. This is the last-ditch fallback for invocations where
   neither env var is set but the script lives inside an installed
   plugin tree.

A "kaizen plugin dir" is identified by the marker file
`.claude-plugin/plugin.json`. Same marker, both helpers — keep
synced when one changes.

## Helpers

### Bash — `scripts/util/_plugin_root.sh`

```bash
# From plugins/kaizen/hooks/claude/<HOOK>.sh:
_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_HOOK_DIR/../../scripts/util/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root)" || exit 0
```

Adjust the `..` depth for callers at other locations (e.g. `../util/`
from a sibling `scripts/git-hooks/X.sh`).

`kaizen_plugin_root` prints the path on stdout and returns 0; on
failure it prints nothing and returns 1. Hook scripts should `exit 0`
on unresolved root (best-effort — never block the host).

### Python — `scripts/io/_plugin_root.py`

```python
from _plugin_root import plugin_root
root = plugin_root()                # raises PluginRootNotFound on miss
root = plugin_root(strict=False)    # returns None instead
```

`plugin_root()` returns a `pathlib.Path`. `MARKER` and `ENV_VARS` are
exported as public constants so tests can lock the contract.

## Why two env vars

`$CLAUDE_PLUGIN_ROOT` is provided by Claude Code's plugin runtime; we
prefer it when present because CC populates it with the canonical
installed path. `$KAIZEN_PLUGIN_ROOT` is a kaizen-owned name that
non-CC hosts can set without claiming the CC namespace — used by
`bin/kaizen-export` to seed a working environment for Codex CLI and
other targets.

If both are set, `$CLAUDE_PLUGIN_ROOT` wins. This matches the
"current host's native protocol takes precedence" rule.

## Where this matters

| Surface | Current state | After R2 |
|---|---|---|
| `hooks/*.sh` | hard-coded `${CLAUDE_PLUGIN_ROOT}` | resolve via `kaizen_plugin_root` |
| `lib.sh::find_sibling` | inlined `${CLAUDE_PLUGIN_ROOT:-/__unset__}` | calls `kaizen_plugin_root` |
| `.mcp.json` | hard-coded `${CLAUDE_PLUGIN_ROOT}` substitution | (unchanged — CC-managed; for Codex use `bin/kaizen-export`) |
| `commands/*.md` | hard-coded `${CLAUDE_PLUGIN_ROOT}` | (unchanged — CC-managed) |
| `bin/*` wrappers | (none today) | future: source `_plugin_root.sh` |

JSON files (`.mcp.json`, `hooks.json`, command frontmatter) can't
express a fallback chain — Claude Code substitutes the value before
the shell ever sees it. For non-CC hosts we generate fresh
configuration via the exporter rather than try to make the JSON
self-resolving.

## Tests

- `tests/test_plugin_root.py` — Python unit tests (env, marker, walk-up, strict mode, contract).
- `tests/test_plugin_root.sh` — bash unit tests mirroring the Python suite 1:1.

Both suites scrub `CLAUDE_PLUGIN_ROOT` + `KAIZEN_PLUGIN_ROOT` between
cases to guarantee independence.
