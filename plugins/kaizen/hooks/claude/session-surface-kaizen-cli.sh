#!/usr/bin/env bash
# kaizen SessionStart hook — surface the kaizen CLI cheat-sheet so agents
# default to `kaizen <sub>` instead of long-form `bash plugins/kaizen/...`
# invocations. Companion to the PreToolUse bash gate's long-form-nudge
# (which warns at command-write time); this hook trains the agent at
# session start so the warnings are pre-empted.
#
# Silent no-op when the kaizen dispatcher isn't on $PATH (consumer repo
# that never ran /kaizen:setup install, or KAIZEN_CLI_SURFACE_DISABLE=1).

set -u

_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || { echo "{}"; exit 0; }

# Bypass-knob iron-law compliance
[ "${KAIZEN_CLI_SURFACE_DISABLE:-}" = "1" ] && { echo "{}"; exit 0; }

EVENT=$(cat 2>/dev/null || echo "{}")
printf '%s' "$EVENT" | bash "$PLUGIN_ROOT/hooks/claude/_trace.sh" SessionStart

# Detect whether the dispatcher is reachable. Prefer $PATH; fall back to
# the absolute bin path inside the plugin (always present).
KAIZEN_BIN=""
if command -v kaizen >/dev/null 2>&1; then
    KAIZEN_BIN="kaizen"
elif [ -x "$PLUGIN_ROOT/bin/kaizen" ]; then
    KAIZEN_BIN="$PLUGIN_ROOT/bin/kaizen"
fi
[ -z "$KAIZEN_BIN" ] && { echo "{}"; exit 0; }

# Pull total subcommand + slash-command counts via the dispatcher
# (~50ms — fast enough for SessionStart's tight budget).
CLI_COUNT=$("$KAIZEN_BIN" list --json 2>/dev/null \
    | python3 -c 'import json,sys;d=json.load(sys.stdin);print(sum(len(v) for v in d.values()))' 2>/dev/null \
    || echo "?")
CMD_COUNT=$("$KAIZEN_BIN" commands list --json 2>/dev/null \
    | python3 -c 'import json,sys;print(len(json.load(sys.stdin)))' 2>/dev/null \
    || echo "?")

# Build the cheat-sheet additionalContext.
read -r -d '' CONTEXT <<EOF || true
## kaizen CLI surface (prefer over long-form paths)

\`kaizen\` is on \$PATH (resolves to ${KAIZEN_BIN}). Use it for bash
calls instead of \`bash plugins/kaizen/...\` long-form paths.

**Top-level surface:**

  kaizen                       — categorized listing of ${CLI_COUNT} CLI subcommands
  kaizen commands              — listing of ${CMD_COUNT} slash commands (/kaizen:<name>)
  kaizen list --json           — machine-readable inventory
  kaizen help <sub>            — full docstring per subcommand
  kaizen --time <sub> [args]   — dispatch + wall-clock timing
  kaizen --trace <sub> [args]  — dispatch + kaizen-trace events

**Hot-path examples (use these instead of long-form):**

  kaizen gatekeeper check --staged    # NOT: bash plugins/kaizen/.../gatekeeper.py check --staged
  kaizen iron-laws check              # NOT: python3 plugins/kaizen/.../iron_laws.py check
  kaizen surface validate             # NOT: python3 plugins/kaizen/.../surface.py validate
  kaizen backlog list                 # NOT: python3 plugins/kaizen/.../backlog.py list
  kaizen audit                        # NOT: bash plugins/kaizen/.../audit.sh

**Gate at PreToolUse:** the bash-gate hook nudges long-form paths and
blocks etu \`error\` anti-patterns (eval \$user_input, find /, rm -rf
\$unset, etc.) before they execute. Bypass: \`KAIZEN_ETU_GATE_DISABLE=1
<cmd>\` for a specific command, or add \`# noqa: etu\` on the line.

**MCP equivalents** (cleaner than bash for the agent — structured
return, no quoting hell):

  mcp__plugin_kaizen_kaizen__gatekeeper_check(scope='all')
  mcp__plugin_kaizen_kaizen__iron_laws_check(scope='staged')
  mcp__plugin_kaizen_kaizen__list_items()    # backlog items
EOF

# Emit as additionalContext via the v2 hooks JSON contract.
python3 - "$CONTEXT" <<'PY' 2>/dev/null
import json, sys
ctx = sys.argv[1]
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": ctx,
    }
}))
PY
