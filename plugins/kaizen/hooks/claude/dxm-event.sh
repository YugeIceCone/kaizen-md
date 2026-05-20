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

# Fallback: CC's stdin payload for PreCompact, SessionEnd, SubagentStop,
# and Notification sometimes lacks session_id. Discover via
# _session_jsonl (one python3 spawn, only on these low-volume events —
# the hot-path PreToolUse/PostToolUse always have session_id in stdin
# and skip this branch).
if [ -z "$SID" ]; then
    SID=$(python3 -c "
import sys, os
root = os.environ.get('CLAUDE_PLUGIN_ROOT') or os.environ.get('KAIZEN_PLUGIN_ROOT')
if not root:
    here = os.path.realpath('${BASH_SOURCE[0]}')
    root = os.path.realpath(os.path.join(os.path.dirname(here), '..', '..'))
# Post-DOMAIN-shells: _session_jsonl lives at scripts/handoff/_session_jsonl.py.
# Use _bootstrap (adds every scripts/<cluster>/ to sys.path) so this stays
# resilient if the module relocates again.
sys.path.insert(0, os.path.join(root, 'scripts'))
try:
    import _bootstrap  # noqa: F401
    from _session_jsonl import discover_active_session_id
    sid = discover_active_session_id()
    if sid: print(sid)
except Exception: pass
" 2>/dev/null)
fi

if [ -z "$SID" ]; then echo '{}'; exit 0; fi

# Extractor helper — single regex per field. CC's event JSON uses
# snake_case for hook inputs (camelCase shows up only in the persisted
# attachment record, which we don't see here).
_extract_str() {
    printf '%s' "$INPUT" \
        | grep -oE "\"$1\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" \
        | head -n1 \
        | sed -E 's/.*:[[:space:]]*"([^"]*)".*/\1/'
}
_extract_num() {
    printf '%s' "$INPUT" \
        | grep -oE "\"$1\"[[:space:]]*:[[:space:]]*-?[0-9]+(\.[0-9]+)?" \
        | head -n1 \
        | sed -E 's/.*:[[:space:]]*(-?[0-9.]+).*/\1/'
}

TOOL=$(_extract_str tool_name)
TUID=$(_extract_str tool_use_id)
AGENTID=$(_extract_str agent_id)
DURMS=$(_extract_num duration_ms)
EXITCODE=$(_extract_num exit_code)

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
# embedding is fine. Optional fields conditionally appended; the
# resulting line is always valid JSON (verified by test).
EVENTS_FILE="$DXM_DIR/events-${SID}.jsonl"
LINE="{\"ts_unix\":$TS,\"session_id\":\"$SID\",\"evt_type\":\"$EVT\""
[ -n "$TOOL" ]     && LINE="$LINE,\"tool_name\":\"$TOOL\""
[ -n "$TUID" ]     && LINE="$LINE,\"tool_use_id\":\"$TUID\""
[ -n "$AGENTID" ]  && LINE="$LINE,\"agent_id\":\"$AGENTID\""
[ -n "$DURMS" ]    && LINE="$LINE,\"duration_ms\":$DURMS"
[ -n "$EXITCODE" ] && LINE="$LINE,\"exit_code\":$EXITCODE"
LINE="$LINE}"
printf '%s\n' "$LINE" >> "$EVENTS_FILE"

echo '{}'
exit 0
