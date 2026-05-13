#!/usr/bin/env bash
# SubagentStop hook — capture subagent dispatch verdicts to kaizen-trace.
#
# Fires when a Claude Code subagent (Agent tool dispatch) finishes —
# successful return, error, or stop-event. The hook body is additive:
# it writes one trace event and exits 0. No effect on the surrounding
# conversation; if PLUGIN_ROOT is unresolvable or trace.py is unavailable
# the hook silently no-ops (best-effort tracing).
#
# Cross-CLI compat: SubagentStop is a Claude-Code-specific event. Hosts
# that don't fire it (Codex, ad-hoc shell) simply never invoke this script.
# The script body itself is portable Python + bash.

set -uo pipefail

_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || exit 0

EVENT=$(cat 2>/dev/null || echo '{}')

printf '%s' "$EVENT" | bash "$PLUGIN_ROOT/hooks/claude/_trace.sh" SubagentStop

# Extract subagent identity + verdict for an extra-detailed trace event.
# Best-effort — every step swallows errors so trace failures don't
# disrupt the host conversation.
EXTRA=$(printf '%s' "$EVENT" | python3 - <<'PY' 2>/dev/null
import json, sys
try:
    e = json.load(sys.stdin)
except Exception:
    sys.exit(0)
agent = e.get("subagent_type") or e.get("subagent") or e.get("agent") or ""
desc = (e.get("description") or e.get("task") or "")[:80]
status = e.get("status") or e.get("result_type") or ""
sid = e.get("session_id") or ""
print(json.dumps({"agent": agent, "desc": desc, "status": status, "sid": sid}))
PY
)

if [ -n "${EXTRA:-}" ]; then
    AGENT=$(printf '%s' "$EXTRA" | python3 -c "import json,sys; print(json.load(sys.stdin).get('agent',''))" 2>/dev/null)
    SID=$(printf '%s' "$EXTRA" | python3 -c "import json,sys; print(json.load(sys.stdin).get('sid',''))" 2>/dev/null)
    if [ -n "$AGENT" ]; then
        # Pass the full subagent-detail JSON as --data so search can
        # surface it later. trace.py validates the JSON; on parse
        # failure the call is dropped silently.
        python3 "$PLUGIN_ROOT/skills/workflow/scripts/trace.py" event \
            --src hook --evt SubagentStop-detail \
            ${AGENT:+--tool "$AGENT"} \
            ${SID:+--sid "$SID"} \
            --data "$EXTRA" \
            >/dev/null 2>&1 || true
    fi
fi

# Empty JSON envelope — never blocks, never injects context.
echo '{}'
