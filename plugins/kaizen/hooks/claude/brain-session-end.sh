#!/usr/bin/env bash
# brain-session-end — auto-fire the brain audit at end-of-session.
#
# Implements pref-session-discovery-log: scan recent activity for
# non-obvious learnings, surface candidates to brain/Inbox/ as drafts.
# Default is APPLY (writes drafts) so the user finds them next session.
#
# Bypass: KAIZEN_BRAIN_AUDIT_DISABLE=1 (skip the audit entirely).
#
# Fires on SessionEnd. Timeout 30s — bounded so a slow audit doesn't
# block session exit.

set -uo pipefail

if [ "${KAIZEN_BRAIN_AUDIT_DISABLE:-}" = "1" ]; then
    exit 0
fi

# Resolve plugin root via the standard helper (same shape as other
# kaizen hooks).
_SCRIPT_REAL="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null \
  || python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "${BASH_SOURCE[0]}")"
_HOOK_DIR="$(cd "$(dirname "$_SCRIPT_REAL")" && pwd)"
# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || exit 0

# Trace this hook's own firing — the universal trace covers tool calls,
# but hook-internal lifecycle events benefit from explicit logging too.
# Best-effort: never block on trace failures.
echo '{}' | bash "$PLUGIN_ROOT/hooks/claude/_trace.sh" \
    SessionEnd-brain-audit 2>/dev/null || true

# Run with apply=true so candidates land as drafts. Suppress stdout
# (hook output is noisy in the user's terminal); errors go to stderr.
python3 "$PLUGIN_ROOT/skills/workflow/scripts/brain_audit.py" \
    --apply --json >/dev/null 2>&1 || true

exit 0
