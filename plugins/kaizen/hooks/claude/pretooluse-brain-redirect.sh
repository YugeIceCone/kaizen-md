#!/usr/bin/env bash
# pretooluse-brain-redirect — auto-nudge Read on memory files →
# kaizen-brain show/edit. Per user 2026-05-19 — "automate it don't
# rely on skills." Reads PreToolUse event JSON on stdin; emits hook-
# decision JSON on stdout. Never blocks. Bypass:
# KAIZEN_BRAIN_REDIRECT_DISABLE=1
set -uo pipefail
if [ "${KAIZEN_BRAIN_REDIRECT_DISABLE:-}" = "1" ]; then echo '{}'; exit 0; fi
_SCRIPT_REAL="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "${BASH_SOURCE[0]}")"
_HOOK_DIR="$(cd "$(dirname "$_SCRIPT_REAL")" && pwd)"
EVENT=$(cat 2>/dev/null || echo '{}')
printf '%s' "$EVENT" | bash "$_HOOK_DIR/_trace.sh" PreToolUse-brain-redirect Read 2>/dev/null || true
printf '%s' "$EVENT" | python3 "$PLUGIN_ROOT/scripts/handlers/_brain_redirect.py" 2>/dev/null || echo '{}'
exit 0
