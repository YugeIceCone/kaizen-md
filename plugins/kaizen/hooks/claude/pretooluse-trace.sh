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
# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || { echo '{}'; exit 0; }

INPUT="$(cat 2>/dev/null || echo '{}')"

# Extract tool_name + identifier via python3. Different tools have
# different tool_input shapes; the python here handles each kind.
TOOL_INFO=$(printf '%s' "$INPUT" | python3 -c "
import json, sys
try:
    e = json.load(sys.stdin)
except Exception:
    print('||')
    sys.exit(0)
tool_name = e.get('tool_name', '')
tool_input = e.get('tool_input', {}) or {}
# Per-tool identifier (the most-useful single string)
ident = ''
if tool_name == 'Skill':
    ident = str(tool_input.get('skill', ''))
elif tool_name in {'Edit', 'Write', 'Read', 'NotebookEdit'}:
    ident = str(tool_input.get('file_path', ''))[:120]
elif tool_name == 'Glob':
    ident = str(tool_input.get('pattern', ''))[:120]
elif tool_name == 'Grep':
    ident = str(tool_input.get('pattern', ''))[:120]
elif tool_name == 'Agent':
    ident = str(tool_input.get('subagent_type', tool_input.get('description', '')))[:120]
elif tool_name == 'TaskCreate':
    ident = str(tool_input.get('subject', ''))[:120]
elif tool_name.startswith('mcp__'):
    ident = tool_name  # whole mcp__server__tool string IS the identifier
elif tool_name == 'WebFetch':
    ident = str(tool_input.get('url', ''))[:120]
print(f'{tool_name}||{ident}')
" 2>/dev/null)

TOOL_NAME="${TOOL_INFO%%||*}"
IDENT="${TOOL_INFO#*||}"

# Skip Bash — pretooluse-bash-gate.sh already traces it.
# Skip empty tool_name (malformed event; nothing to trace).
if [ -z "$TOOL_NAME" ] || [ "$TOOL_NAME" = "Bash" ]; then
    echo '{}'
    exit 0
fi

# Build a small data blob with the identifier (only when present).
DATA="{}"
if [ -n "$IDENT" ]; then
    DATA=$(python3 -c "import json; print(json.dumps({'ident': '''$IDENT'''}))")
fi

SID=$(printf '%s' "$INPUT" | python3 -c "
import json, sys
try: print(json.loads(sys.stdin.read() or '{}').get('session_id', ''))
except: pass
" 2>/dev/null)

# Fire the trace via trace.py (NOT _trace.sh — we want to pass --data).
python3 "$PLUGIN_ROOT/skills/workflow/scripts/trace.py" event \
    --src hook --evt "PreToolUse-${TOOL_NAME}" --tool "$TOOL_NAME" \
    ${SID:+--sid "$SID"} \
    --data "$DATA" \
    >/dev/null 2>&1 || true

echo '{}'
exit 0
