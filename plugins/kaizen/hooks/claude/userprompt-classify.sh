#!/usr/bin/env bash
# kaizen UserPromptSubmit hook — auto-classify the user prompt against
# the active workflow schema's rubric. Phase 7 of /kaizen:workflow
# full-automation.
#
# Gate: only fires when:
#   - KAIZEN_CLASSIFY_DISABLE is unset
#   - inside a git project
#   - .kaizen/workflow/state.json exists (a workflow run is active)
#
# Emits an additionalContext block like:
#
#   [kaizen workflow classify] task bucket: BUG_FIX (conf 1.00)
#     keep stages: classify, red-test, green-impl, refactor, compile-gate, verify
#     skip stages: audit, design, wire-flow, trace-wire
#
# Best-effort: any error in the chain (signal computer / rubric walker /
# state read) collapses to '{}' no-op. Tracing failures must not break
# the user's turn.
#
# Bypass: KAIZEN_CLASSIFY_DISABLE=1

set -uo pipefail

[ "${KAIZEN_CLASSIFY_DISABLE:-}" = "1" ] && { echo '{}'; exit 0; }

_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../scripts/util/_plugin_root.sh
source "$_HOOK_DIR/../../scripts/util/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || { echo '{}'; exit 0; }

# Trace firing (iron-law: every-hook-script-traces-its-firing).
EVENT_JSON="$(cat 2>/dev/null || echo '{}')"
printf '%s' "$EVENT_JSON" \
    | bash "$PLUGIN_ROOT/hooks/claude/_trace.sh" UserPromptSubmit-classify \
    2>/dev/null || true

# Gate: must be in a git repo with an active workflow run
REPO=$(git rev-parse --show-toplevel 2>/dev/null) || { echo '{}'; exit 0; }
[ -f "$REPO/.kaizen/workflow/state.json" ] || { echo '{}'; exit 0; }

# Extract the prompt + active schema name in one Python pass
RESOLVED=$(EVENT_JSON_RAW="$EVENT_JSON" REPO="$REPO" python3 -c "
import json, os, sys
try:
    ev = json.loads(os.environ.get('EVENT_JSON_RAW', '{}'))
    prompt = ev.get('prompt', '')
    state = json.load(open(os.path.join(os.environ['REPO'], '.kaizen/workflow/state.json')))
    schema = state.get('schema', '')
    if prompt and schema:
        print(json.dumps({'prompt': prompt, 'schema': schema}))
except Exception:
    pass
" 2>/dev/null)

[ -z "$RESOLVED" ] && { echo '{}'; exit 0; }

# Run dry-run via the kaizen-workflow-config CLI
VERDICT=$(cd "$REPO" && RESOLVED="$RESOLVED" python3 -c "
import json, os, subprocess
r = json.loads(os.environ['RESOLVED'])
cmd = [
    'python3', '${PLUGIN_ROOT}/scripts/workflow/workflow_config.py',
    'dry-run', '--schema', r['schema'], '--prompt', r['prompt'], '--json',
]
res = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
if res.returncode == 0:
    print(res.stdout)
" 2>/dev/null)

[ -z "$VERDICT" ] && { echo '{}'; exit 0; }

# Build additionalContext from verdict
VERDICT="$VERDICT" python3 -c "
import json, os
try:
    v = json.loads(os.environ['VERDICT'])
    keep = ', '.join(v.get('keep_stages') or []) or '(none)'
    skip = ', '.join(v.get('skip_stages') or []) or '(none)'
    body = (
        f\"[kaizen workflow classify] task bucket: {v.get('bucket','?')} \"
        f\"(conf {v.get('confidence',0):.2f})\n\"
        f'  keep stages: {keep}\n'
        f'  skip stages: {skip}\n'
        f'  signals:     {json.dumps(v.get(\"signals\",{}), separators=(\",\",\":\"))}\n'
    )
    print(json.dumps({
        'hookSpecificOutput': {
            'hookEventName': 'UserPromptSubmit',
            'additionalContext': body,
        }
    }))
except Exception:
    print('{}')
" 2>/dev/null || echo '{}'
