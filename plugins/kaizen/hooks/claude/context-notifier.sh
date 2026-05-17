#!/usr/bin/env bash
# kaizen context-notifier hook — fire on Stop to check context zone +
# emit dxm event on zone transition. ~50ms cost; never blocks.
# Bypass: KAIZEN_CONTEXT_NOTIFIER_DISABLE=1

set -uo pipefail
if [ "${KAIZEN_CONTEXT_NOTIFIER_DISABLE:-}" = "1" ]; then echo '{}'; exit 0; fi

_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || { echo '{}'; exit 0; }

python3 "$PLUGIN_ROOT/skills/workflow/scripts/context_notifier.py" check \
    >/dev/null 2>&1 || true
echo '{}'
exit 0
