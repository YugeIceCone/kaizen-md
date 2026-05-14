#!/usr/bin/env bash
# Universal PostToolUse trace — fires for every tool (matcher '*').
#
# Companion to pretooluse-trace.sh. Captures tool completion +
# (when available) duration_ms. Same skip-Bash rule.
#
# Bypass: KAIZEN_METRICS_DISABLE=1

set -uo pipefail

if [ "${KAIZEN_METRICS_DISABLE:-}" = "1" ]; then
    echo '{}'
    exit 0
fi

_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || { echo '{}'; exit 0; }

INPUT="$(cat 2>/dev/null || echo '{}')"

PARSED=$(printf '%s' "$INPUT" | python3 -c "
import json, sys
try:
    e = json.load(sys.stdin)
except Exception:
    print('|||')
    sys.exit(0)
tool_name = e.get('tool_name', '')
# Duration: PostToolUse events may carry a 'duration_ms' or similar
ms = e.get('duration_ms') or e.get('tool_response', {}).get('duration_ms') if isinstance(e.get('tool_response'), dict) else None
ms_str = str(int(ms)) if ms else ''
# Success/failure
tool_response = e.get('tool_response', {})
ok = ''
if isinstance(tool_response, dict):
    if 'error' in tool_response or tool_response.get('isError'):
        ok = 'err'
    else:
        ok = 'ok'
print(f'{tool_name}|{ms_str}|{ok}')
" 2>/dev/null)

TOOL_NAME="${PARSED%%|*}"
REST="${PARSED#*|}"
MS="${REST%%|*}"
OK="${REST#*|}"

if [ -z "$TOOL_NAME" ] || [ "$TOOL_NAME" = "Bash" ]; then
    echo '{}'
    exit 0
fi

SID=$(printf '%s' "$INPUT" | python3 -c "
import json, sys
try: print(json.loads(sys.stdin.read() or '{}').get('session_id', ''))
except: pass
" 2>/dev/null)

DATA="{}"
if [ -n "$OK" ]; then
    DATA=$(python3 -c "import json; print(json.dumps({'result': '$OK'}))")
fi

python3 "$PLUGIN_ROOT/skills/workflow/scripts/trace.py" event \
    --src hook --evt "PostToolUse-${TOOL_NAME}" --tool "$TOOL_NAME" \
    ${SID:+--sid "$SID"} ${MS:+--ms "$MS"} \
    --data "$DATA" \
    >/dev/null 2>&1 || true

echo '{}'
exit 0
