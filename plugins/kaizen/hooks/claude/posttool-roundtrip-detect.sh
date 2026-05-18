#!/usr/bin/env bash
# posttool-roundtrip-detect.sh — fires on PostToolUse for Read/Edit/Write.
# Detects Read+Edit (or Read+Write) on the same path within a window
# (default 30s) and nudges the agent to capture the friction via
# `kaizen-learn append --category roundtrips ...`.
#
# Iron-laws:
#   - bypass via KAIZEN_LEARNING_DETECT_DISABLE=1 (early return; no state touch)
#   - never blocks the host (exit 0 always)
#   - delegates to _roundtrip_detect.py — pure-function core; this wrapper
#     just plumbs stdin/stdout/state-path
set -uo pipefail

# Early bypass.
if [ "${KAIZEN_LEARNING_DETECT_DISABLE:-}" = "1" ]; then
    exit 0
fi

# Resolve hook dir (cross-platform).
_SCRIPT_REAL="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "${BASH_SOURCE[0]}")"
_HOOK_DIR="$(cd "$(dirname "$_SCRIPT_REAL")" && pwd)"

STATE_DIR="${KAIZEN_LEARNING_DIR:-$HOME/.claude/.kaizen/learning}"
mkdir -p "$STATE_DIR" 2>/dev/null || true
STATE_PATH="$STATE_DIR/detect-state.json"
WINDOW_SECONDS="${KAIZEN_LEARNING_DETECT_WINDOW:-30}"

# Stream stdin straight to python via subprocess. No string escaping —
# python reads stdin itself.
python3 -c "
import json, sys
from pathlib import Path
sys.path.insert(0, '$_HOOK_DIR')
from _roundtrip_detect import run_hook
stdin_text = sys.stdin.read()
out, _ = run_hook(stdin_text, state_path=Path('$STATE_PATH'),
                   window_seconds=$WINDOW_SECONDS)
if out:
    print(json.dumps(out))
" 2>/dev/null || true

# Fire trace event (consistent with other kaizen hooks).
"$_HOOK_DIR/_trace.sh" "PostToolUse-roundtrip-detect" "${CLAUDE_SESSION_ID:-}" 2>/dev/null || true

exit 0
