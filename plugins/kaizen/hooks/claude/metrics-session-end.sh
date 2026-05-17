#!/usr/bin/env bash
# metrics-session-end — SessionEnd skip-detection hook.
#
# Runs `kaizen-metrics skips` at end-of-session. If any skill-skip
# candidates are detected (touched files that should have triggered
# a skill load, but the skill was never loaded), writes a draft
# entry to brain/Inbox/ for the user to review next session.
#
# This implements the self-correction signal the user asked for:
# "if you skip something or something never gets used."
#
# Bypass: KAIZEN_METRICS_DISABLE=1
#
# Output: nothing visible (the artifact is the Inbox draft).
# Errors: silent — hook must not block session exit.

set -uo pipefail

if [ "${KAIZEN_METRICS_DISABLE:-}" = "1" ]; then
    exit 0
fi

_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || exit 0

# Trace this hook's own firing — universal trace covers tool calls;
# hook-internal lifecycle events get explicit logging.
echo '{}' | bash "$PLUGIN_ROOT/hooks/claude/_trace.sh" \
    SessionEnd-metrics-skip-check 2>/dev/null || true

# Resolve brain root via the kaizen SSOT (post v1.38.0 — KAIZEN_BRAIN_DIR
# is the ONLY resolver; legacy envs no longer consulted).
# shellcheck source=../../skills/workflow/scripts/_paths.sh
source "$PLUGIN_ROOT/skills/workflow/scripts/_paths.sh"
BRAIN_ROOT="$KAIZEN_BRAIN_DIR"
[ -d "$BRAIN_ROOT" ] || exit 0

# Run skip-detection on the latest session.
SKIPS_JSON=$(python3 "$PLUGIN_ROOT/skills/workflow/scripts/metrics.py" \
    skips --json 2>/dev/null || echo '{}')

# Extract the count of skip candidates
SKIP_COUNT=$(printf '%s' "$SKIPS_JSON" | python3 -c "
import json, sys
try:
    d = json.loads(sys.stdin.read() or '{}')
    print(len(d.get('skips', [])))
except Exception:
    print(0)
" 2>/dev/null)

[ "${SKIP_COUNT:-0}" -eq 0 ] && exit 0

# Write a draft Inbox entry for review next session.
TODAY=$(date -u +%Y-%m-%d)
INBOX="$BRAIN_ROOT/Inbox"
mkdir -p "$INBOX"
DRAFT="$INBOX/skip-detection-$TODAY-$RANDOM.md"

printf '%s' "$SKIPS_JSON" | python3 -c "
import json, sys, os
data = json.loads(sys.stdin.read() or '{}')
skips = data.get('skips', [])
sid = data.get('sid', '')
out = ['---']
out.append(f'name: skip-detection-{os.environ.get(\"TODAY\",\"unknown\")}')
out.append('description: Skill-skip candidates detected at SessionEnd. Review + decide whether to load + retry, or accept the skip with rationale.')
out.append('type: experience')
out.append(f'session_id: {sid}')
out.append('---')
out.append('')
out.append('# Skip-detection report')
out.append('')
out.append(f'Detected {len(skips)} skill-skip(s) in this session.')
out.append('')
for s in skips:
    out.append(f'## Skill: \`{s[\"skill\"]}\`')
    out.append('')
    out.append(f'**Rationale:** {s[\"rationale\"]}')
    out.append('')
    out.append(f'**Touched {s[\"touched_count\"]} file(s):**')
    for p in s['touched_files']:
        out.append(f'- \`{p}\`')
    out.append('')
print('\n'.join(out))
" TODAY="$TODAY" > "$DRAFT" 2>/dev/null || true

exit 0
