#!/usr/bin/env bash
# posttool-keepalive.sh — fire kaizen-daemon systems-check every
# KAIZEN_KEEPALIVE_INTERVAL tool calls (default 25). Counter persisted
# in <KAIZEN_KEEPALIVE_DIR>/counter.txt; resets after each fire.
#
# Iron-laws: never blocks; bypass via KAIZEN_KEEPALIVE_DISABLE=1.
# Default interval (25) keeps the hook cheap (~1 fire per 25 tool calls).
set -uo pipefail

if [ "${KAIZEN_KEEPALIVE_DISABLE:-}" = "1" ]; then
    exit 0
fi

_SCRIPT_REAL="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "${BASH_SOURCE[0]}")"
_HOOK_DIR="$(cd "$(dirname "$_SCRIPT_REAL")" && pwd)"
_PLUGIN_ROOT="$(cd "$_HOOK_DIR/../.." && pwd)"

INTERVAL="${KAIZEN_KEEPALIVE_INTERVAL:-25}"
STATE_DIR="${KAIZEN_KEEPALIVE_DIR:-$HOME/.claude/.kaizen/keepalive}"
mkdir -p "$STATE_DIR" 2>/dev/null || true
COUNTER="$STATE_DIR/counter.txt"

# Read + increment counter
CURRENT=$(cat "$COUNTER" 2>/dev/null || echo 0)
CURRENT=$((CURRENT + 1))

if [ "$CURRENT" -ge "$INTERVAL" ]; then
    # Fire systems-check + reset counter
    uv run --script "$_PLUGIN_ROOT/scripts/daemon/daemon.py" systems-check >/dev/null 2>&1 || true
    echo 0 > "$COUNTER"
    "$_HOOK_DIR/_trace.sh" "PostToolUse-keepalive-fired" "${CLAUDE_SESSION_ID:-}" 2>/dev/null || true
else
    echo "$CURRENT" > "$COUNTER"
fi

exit 0
