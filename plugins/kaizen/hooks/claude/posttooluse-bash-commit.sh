#!/usr/bin/env bash
# PostToolUse(Bash) hook — when Claude runs `git commit`, suggest ticking
# backlog items mentioned in the commit message.
#
# Emits additionalContext only (soft suggestion). Never blocks.

set -uo pipefail

# Bypass-knob iron-law compliance
[ "${KAIZEN_BACKLOG_COMMIT_DISABLE:-}" = "1" ] && { echo '{}'; exit 0; }

# Resolve plugin root (CLAUDE_PLUGIN_ROOT → KAIZEN_PLUGIN_ROOT → derived).
_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../scripts/util/_plugin_root.sh
source "$_HOOK_DIR/../../scripts/util/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || { echo '{}'; exit 0; }

# Trace firing (iron-law: every-hook-script-traces-its-firing). Read
# stdin once + tee so the helper still sees it.
EVENT_JSON="$(cat 2>/dev/null || echo '{}')"
printf '%s' "$EVENT_JSON" | bash "$PLUGIN_ROOT/hooks/claude/_trace.sh" PostToolUse-bash-commit Bash 2>/dev/null || true

# Single python3 spawn — posttooluse_bash_commit.py reads stdin once,
# early-exits if not `git commit`, then matches in_flight backlog
# items against the latest commit message. Was 4 spawns + shell-side
# grep+sed of .kaizen.toml.
printf '%s' "$EVENT_JSON" | python3 "$PLUGIN_ROOT/scripts/handlers/posttooluse_bash_commit.py"
