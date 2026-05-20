#!/usr/bin/env bash
# PostCompact hook — refresh daemon-built auto-load.md before Claude
# re-injects CLAUDE.md.
#
# Per the Claude Code memory doc: after /compact, project-root
# CLAUDE.md is re-read from disk + re-injected. CLAUDE.md @imports
# our auto-load.md; the import expands to whatever's on disk RIGHT
# THEN. If the daemon hasn't ticked since the last Persona edit,
# the agent gets a stale auto-load.
#
# Fix: this hook fires kaizen-auto-load (the bin) to rebuild auto-
# load.md + cluster gates IMMEDIATELY at PostCompact, so re-injection
# sees fresh content.
#
# Side-effects:
#   1. _trace.sh → kaizen-trace "postcompact-refresh" event
#   2. exec kaizen-auto-load (writes ~/.claude/.kaizen/auto-load.md +
#      cluster gate files)
#
# Bypass: KAIZEN_POSTCOMPACT_REFRESH_DISABLE=1
# Non-blocking: exit 0 always (PostCompact must not stall the session).
#
# Design contract:
#   ADDITIVE     — new hook entry; no existing chain touched
#   NON-BLOCKING — backgrounds the daemon op via `&` with disown
#   FAST         — main body returns in < 10ms (the daemon work runs async)
#   IDEMPOTENT   — re-firing is safe; daemon writes are atomic

set -uo pipefail

[ "${KAIZEN_POSTCOMPACT_REFRESH_DISABLE:-}" = "1" ] && exit 0

INPUT="$(cat 2>/dev/null || true)"

_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Trace fire — composes the standard kaizen-trace event.
printf '%s' "$INPUT" | bash "$_HOOK_DIR/_trace.sh" postcompact-refresh 2>/dev/null || true

# Resolve plugin root via the shared helper.
# shellcheck source=../../scripts/util/_plugin_root.sh
source "$_HOOK_DIR/../../scripts/util/_plugin_root.sh" 2>/dev/null || exit 0
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || exit 0

# Fire the bin (which writes auto-load.md + cluster gates atomically).
# Background + disown so PostCompact returns instantly. The next file
# Read of auto-load.md will see fresh content; if the daemon happens
# to be already running, the atomic-write contract handles the race.
"$PLUGIN_ROOT/bin/kaizen-auto-load" > /dev/null 2>&1 &
disown 2>/dev/null || true

exit 0
