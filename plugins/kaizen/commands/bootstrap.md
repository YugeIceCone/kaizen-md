---
name: bootstrap
description: "Pre-warm uv-managed Python venvs for the plugin (loc, onboard, daemon, MCP servers) so first invocation is not a cold download. --check verifies uv."
argument-hint: "[--check|--list]"
---

# kaizen bootstrap

The kaizen plugin's Python scripts are PEP-723 `uv run --script` files —
each declares its dependencies in a `# /// script` block and uv builds
a per-script venv on first run. This is the explicit "set everything
up" entry point: it pre-warms those venvs ahead of time.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/bootstrap.sh $ARGUMENTS`

Exit 0 = uv present (pre-warm attempted); non-zero = uv missing (with
an install hint). `--check` verifies uv only (no pre-warm, no network);
`--list` enumerates the uv-script files. `KAIZEN_BOOTSTRAP_DISABLE=1`
skips the pre-warm. Also runs as part of `/kaizen:setup --enable-all`.
