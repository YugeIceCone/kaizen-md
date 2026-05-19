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

# Bypass-knob iron-law compliance (also honored by sibling trace
# hooks via KAIZEN_TRACE_DISABLE).
[ "${KAIZEN_SUBAGENT_TRACE_DISABLE:-}" = "1" ] && { echo '{}'; exit 0; }

_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || exit 0

# Single python3 spawn — subagentstop_trace.py reads stdin once,
# emits both the generic SubagentStop event and the
# SubagentStop-detail event (when subagent identity is present).
# Was 5 spawns (trace.sh subprocess + EXTRA extract + AGENT extract
# + SID extract + final trace.py).
python3 "$PLUGIN_ROOT/scripts/handlers/subagentstop_trace.py" \
    >/dev/null 2>&1 || true

# Empty JSON envelope — never blocks, never injects context.
echo '{}'
