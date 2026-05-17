#!/usr/bin/env bash
# deus-ex-machina event hook — sub-millisecond capture into the
# per-session dxm event log. Wired into PreToolUse / PostToolUse /
# UserPromptSubmit / SessionStart / SessionEnd via hooks.json with
# the event name passed as $1.
#
# Hot path: shell-only — NO python3 spawn. Reads event JSON from
# stdin, extracts session_id + tool_name via grep+sed, appends a tiny
# JSON line directly to the events file. Sub-millisecond per fire.
#
# Bypass: KAIZEN_DXM_DISABLE=1
#
# Output: always {} (this hook never blocks; pure capture).

set -uo pipefail

if [ "${KAIZEN_DXM_DISABLE:-}" = "1" ]; then echo '{}'; exit 0; fi

EVT="${1:-unknown}"

# Resolve dxm dir (env override → default under ~/.claude/.kaizen/dxm/)
DXM_DIR="${KAIZEN_DXM_DIR:-$HOME/.claude/.kaizen/dxm}"
mkdir -p "$DXM_DIR" 2>/dev/null || { echo '{}'; exit 0; }

INPUT=$(cat 2>/dev/null || echo '{}')

# Shell-native session_id + tool_name extraction (no python3 — same H2
# pattern as _trace.sh).
SID=$(printf '%s' "$INPUT" \
    | grep -oE '"session_id"[[:space:]]*:[[:space:]]*"[^"]*"' \
    | head -n1 \
    | sed -E 's/.*:[[:space:]]*"([^"]*)".*/\1/')

if [ -z "$SID" ]; then echo '{}'; exit 0; fi

TOOL=$(printf '%s' "$INPUT" \
    | grep -oE '"tool_name"[[:space:]]*:[[:space:]]*"[^"]*"' \
    | head -n1 \
    | sed -E 's/.*:[[:space:]]*"([^"]*)".*/\1/')

# Sub-millisecond timestamp via date %s.%N (GNU) with python3 fallback
# for BSD/macOS (date there doesn't support %N).
TS=$(date +%s.%N 2>/dev/null)
if [ -z "$TS" ] || [ "${TS#*N}" != "$TS" ]; then
    # date %N not supported → fall back to python (one spawn only when
    # date lacks the format; rare on Linux).
    TS=$(python3 -c 'import time; print(time.time())' 2>/dev/null || echo "0")
fi

# Build JSON line by hand — avoids the JSON-encode/spawn cost. The
# fields are bounded safe-strings (UUIDs, tool names) so direct
# embedding is fine.
EVENTS_FILE="$DXM_DIR/events-${SID}.jsonl"
if [ -n "$TOOL" ]; then
    printf '{"ts_unix":%s,"session_id":"%s","evt_type":"%s","tool_name":"%s"}\n' \
        "$TS" "$SID" "$EVT" "$TOOL" >> "$EVENTS_FILE"
else
    printf '{"ts_unix":%s,"session_id":"%s","evt_type":"%s"}\n' \
        "$TS" "$SID" "$EVT" >> "$EVENTS_FILE"
fi

echo '{}'
exit 0
