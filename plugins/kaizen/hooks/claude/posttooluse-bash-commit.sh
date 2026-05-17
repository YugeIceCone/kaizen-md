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
# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || { echo '{}'; exit 0; }

# Single python3 spawn — posttooluse_bash_commit.py reads stdin once,
# early-exits if not `git commit`, then matches in_flight backlog
# items against the latest commit message. Was 4 spawns + shell-side
# grep+sed of .kaizen.toml.
python3 "$PLUGIN_ROOT/skills/workflow/scripts/posttooluse_bash_commit.py"
