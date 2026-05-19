#!/usr/bin/env bash
# CwdChanged hook — sync auto-memory + auto-load for the NEW project.
#
# Per the Claude Code memory doc, CwdChanged fires when the working
# directory changes (cd / --add-dir / worktree switch). At that moment:
#
# - Auto-memory dir flips to the new git-root's slug (~/.claude/
#   projects/<new-slug>/memory/) — but MEMORY.md there may be stale.
# - Project CLAUDE.md flips to the new repo — but our auto-load.md
#   @import expansion fires on next access; if Persona has changed
#   since the last daemon tick, the agent sees stale content.
# - Project .claude/rules/ + .claude/rules/note-*.md may need refresh
#   too.
#
# Fix: this hook fires kaizen-auto-load + kaizen-better-memory regen
# (both backgrounded + disowned) for the NEW cwd so subsequent reads
# see fresh content.
#
# Side-effects:
#   1. _trace.sh → "cwdchanged-sync" event
#   2. kaizen-auto-load (bg) — rebuilds auto-load.md + gates + project rules
#   3. kaizen-better-memory regen (bg) — refreshes MEMORY.md for new slug
#
# Bypass: KAIZEN_CWDCHANGED_SYNC_DISABLE=1
# Non-blocking: exits 0 instantly; the daemon work runs async.

set -uo pipefail

[ "${KAIZEN_CWDCHANGED_SYNC_DISABLE:-}" = "1" ] && exit 0

INPUT="$(cat 2>/dev/null || true)"

_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
printf '%s' "$INPUT" | bash "$_HOOK_DIR/_trace.sh" cwdchanged-sync 2>/dev/null || true

# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh" 2>/dev/null || exit 0
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || exit 0

# Fire both refreshes in parallel, disowned. The bins resolve git-root
# from the (new) cwd internally — so the kaizen subprocess inherits
# the post-Cd cwd and picks up the right project.
"$PLUGIN_ROOT/bin/kaizen-auto-load" > /dev/null 2>&1 &
disown 2>/dev/null || true
"$PLUGIN_ROOT/bin/kaizen-better-memory" regen > /dev/null 2>&1 &
disown 2>/dev/null || true

exit 0
