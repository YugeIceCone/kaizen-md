#!/usr/bin/env bash
# posttool-observer-capture.sh — captures every PostToolUse event into
# the observer sink (~/.claude/.kaizen/observer/events.jsonl).
# Phase 1.5 of the custom-observer build (spec at
# .kaizen/superpowers/specs/2026-05-18-custom-observer-design.md).
#
# Iron-laws (same family as posttool-roundtrip-detect.sh):
#   - bypass via KAIZEN_OBSERVER_DISABLE=1
#   - never blocks the host (exit 0 always)
#   - delegates to _observer_capture.py — pure-function core; this
#     wrapper just plumbs stdin/now/event_kind
set -uo pipefail

if [ "${KAIZEN_OBSERVER_DISABLE:-}" = "1" ]; then
    exit 0
fi

_SCRIPT_REAL="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "${BASH_SOURCE[0]}")"
_HOOK_DIR="$(cd "$(dirname "$_SCRIPT_REAL")" && pwd)"

NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

python3 -c "
import sys
from pathlib import Path
sys.path.insert(0, '$_HOOK_DIR')
from _observer_capture import capture
stdin_text = sys.stdin.read()
capture(stdin_text, event_kind='post_tool_use', now='$NOW')
" 2>/dev/null || true

"$_HOOK_DIR/_trace.sh" "PostToolUse-observer-capture" "${CLAUDE_SESSION_ID:-}" 2>/dev/null || true

exit 0
