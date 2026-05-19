#!/usr/bin/env bash
# session-start-systems-check.sh — fire one kaizen-daemon systems-check
# at SessionStart to boot the keep-alive heartbeat for the 4 runtime systems
# (hooks/trace/dxm/observer). Per user 2026-05-18 — "all systems can start
# and be on a keep-alive timer on the claude code session start api."
#
# Iron-laws: never blocks (exit 0 always); bypass via KAIZEN_KEEPALIVE_DISABLE=1
set -uo pipefail

if [ "${KAIZEN_KEEPALIVE_DISABLE:-}" = "1" ]; then
    exit 0
fi

_SCRIPT_REAL="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "${BASH_SOURCE[0]}")"
_HOOK_DIR="$(cd "$(dirname "$_SCRIPT_REAL")" && pwd)"
_PLUGIN_ROOT="$(cd "$_HOOK_DIR/../.." && pwd)"

# Run as one-shot; daemon's systems-check appends a heartbeat row.
uv run --script "$_PLUGIN_ROOT/scripts/daemon/daemon.py" systems-check >/dev/null 2>&1 || true

"$_HOOK_DIR/_trace.sh" "SessionStart-systems-check" "${CLAUDE_SESSION_ID:-}" 2>/dev/null || true

exit 0
