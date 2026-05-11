#!/usr/bin/env bash
# kaizen hook trace helper — single source of `trace.py event --src hook` calls.
#
# Usage from any hook:
#
#   printf '%s' "$EVENT" | bash "${CLAUDE_PLUGIN_ROOT}/hooks/_trace.sh" <evt-name> [tool-name]
#
# Reads event JSON from stdin, extracts only `session_id` (never the full
# payload — see CHANGELOG v1.6.1 fix), and emits a `--src hook` trace
# event. Non-blocking; swallows all errors. Tracing must never break the
# host hook flow.
#
# Eliminates the 3-line copy/paste that lived in all 7 kaizen hooks
# pre-v1.6.2.

set -uo pipefail

EVT="${1:-unknown}"
TOOL="${2:-}"

INPUT=$(cat 2>/dev/null || echo "{}")
SID=$(printf '%s' "$INPUT" | python3 -c "import json,sys; print(json.loads(sys.stdin.read() or '{}').get('session_id',''))" 2>/dev/null)

python3 "${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/trace.py" event \
    --src hook --evt "$EVT" \
    ${TOOL:+--tool "$TOOL"} ${SID:+--sid "$SID"} \
    >/dev/null 2>&1 || true
