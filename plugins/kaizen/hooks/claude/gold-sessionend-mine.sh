#!/usr/bin/env bash
# gold-sessionend-mine — fire the gold auto-miner at end-of-session.
#
# Scans dxm events since the last cursor, mechanically filters
# signal-bearing events, optionally scores via local Ollama (when
# KAIZEN_GOLD_MINE_ENABLE=1), and writes proposals + auto-captures per
# the threshold contract (PROPOSAL=0.75 / AUTO_CAPTURE=0.85).
#
# Bypass: KAIZEN_GOLD_DISABLE=1 — same knob the rest of the gold surface
# honors (capture/promote/precompact). Reused intentionally; do NOT add
# a per-hook bypass knob.
#
# Bounded: timeout 10s (configured in hooks.json) so a slow Ollama call
# can't block session exit.

set -uo pipefail

if [ "${KAIZEN_GOLD_DISABLE:-}" = "1" ]; then
    exit 0
fi

# Resolve plugin root via the standard helper (cross-platform).
_SCRIPT_REAL="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null \
  || python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "${BASH_SOURCE[0]}")"
_HOOK_DIR="$(cd "$(dirname "$_SCRIPT_REAL")" && pwd)"
# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || exit 0

# Trace this hook's own firing — iron-law every_hook_script_traces_its_firing.
echo '{}' | bash "$PLUGIN_ROOT/hooks/claude/_trace.sh" \
    SessionEnd-gold-mine 2>/dev/null || true

# Run the mine. Suppress stdout (hook output is noisy in the terminal);
# best-effort: never block on errors.
python3 "$PLUGIN_ROOT/scripts/gold/gold.py" mine \
    >/dev/null 2>&1 || true

exit 0
