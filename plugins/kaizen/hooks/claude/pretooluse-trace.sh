#!/usr/bin/env bash
# Universal PreToolUse trace — fires for every tool (matcher '*' in hooks.json).
#
# Captures: tool_name, optional sub-identifier (skill name, file path,
# MCP tool name), session_id. Emits a `tool.invoke` event with the
# tool name as both the `evt` and `tool` field, plus a data subobject.
#
# Skips Bash (already traced by pretooluse-bash-gate.sh — avoids
# double-tracking). All other tools — Skill / Edit / Write / Read /
# Glob / Grep / mcp__*  / etc. — fire here.
#
# Bypass: KAIZEN_METRICS_DISABLE=1
#
# Output: always {} (this hook never blocks; it only traces).

set -uo pipefail

if [ "${KAIZEN_METRICS_DISABLE:-}" = "1" ]; then
    echo '{}'
    exit 0
fi

_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../scripts/util/_plugin_root.sh
source "$_HOOK_DIR/../../scripts/util/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || { echo '{}'; exit 0; }

# Single python3 spawn — pretooluse_trace.py does parse + per-tool
# ident extraction + trace.append_event in one process. Prior pattern
# spawned python3 four times per fire (~120ms × 1000 tool calls per
# session). The helper does the same work in ~30ms total.
python3 "$PLUGIN_ROOT/scripts/handlers/pretooluse_trace.py" \
    >/dev/null 2>&1 || true

echo '{}'
exit 0
