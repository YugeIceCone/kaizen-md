#!/usr/bin/env bash
# kaizen statusline — backlog + context + gate state in one line.
#
# Wire via user's ~/.claude/settings.json:
#
#   "statusLine": {
#     "type": "command",
#     "command": "bash ${CLAUDE_PLUGIN_ROOT}/scripts/ops/statusline.sh"
#   }
#
# Or use kaizen-statusline install for guided setup.
#
# Reads JSON event from stdin (Claude Code statusline schema). Writes
# one line to stdout. Designed to render in <50 ms.

set -uo pipefail

INPUT=$(cat 2>/dev/null || echo "")

SCRIPT_DIR="$(cd "$(dirname "$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")")" && pwd)"

# ─── Context window ──────────────────────────────────────────────────
# Single python3 spawn — context.py `line` returns the pre-formatted
# segment ("🟢 50k/200k (25%)") or empty when token count unknown.
# Replaces the prior 5-spawn pattern (1 json + 4 field extractions).
CTX_PART=$(echo "$INPUT" | python3 "$SCRIPT_DIR/context.py" line 2>/dev/null || echo "")

# ─── Backlog state ───────────────────────────────────────────────────
BACKLOG_PART=""
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "")
if [ -n "$REPO_ROOT" ]; then
    # Resolve backlog path via config.py (SSOT for .kaizen.toml parsing).
    BACKLOG_REL=$(cd "$REPO_ROOT" && python3 "$SCRIPT_DIR/config.py" backlog_path --default ".kaizen/workflow/backlog.md" 2>/dev/null)
    BACKLOG_REL="${BACKLOG_REL:-.kaizen/workflow/backlog.md}"
    BACKLOG_JSON_PATH="${REPO_ROOT}/${BACKLOG_REL%.md}.json"

    if [ -f "$BACKLOG_JSON_PATH" ]; then
        BACKLOG_PART=$(python3 -c "
import json,sys
try:
    d = json.load(open('$BACKLOG_JSON_PATH'))
    in_flight = sum(1 for i in d.get('items',[]) if i.get('section') == 'in_flight')
    next_up   = sum(1 for i in d.get('items',[]) if i.get('section') == 'next_up')
    if in_flight:
        print(f'🔵 {in_flight} in flight ({next_up}↑)')
    elif next_up:
        print(f'⚪ {next_up} next up')
except Exception:
    pass
" 2>/dev/null || echo "")
    fi
fi

# ─── Gate state ──────────────────────────────────────────────────────
GATE_PART=""
if [ -n "$REPO_ROOT" ]; then
    if [ -L "$REPO_ROOT/.kaizen/hooks/pre-commit" ]; then
        GATE_PART="🟢 gate"
        CACHE_DIR="$REPO_ROOT/.kaizen/cache"
        if [ -d "$CACHE_DIR" ]; then
            CACHE_COUNT=$(find "$CACHE_DIR" -maxdepth 1 -name '*.json' -type f 2>/dev/null | wc -l)
            if [ "${CACHE_COUNT:-0}" -gt 0 ]; then
                GATE_PART="💾 gate ($CACHE_COUNT cached)"
            fi
        fi
    fi
fi

# ─── dxm live segment ────────────────────────────────────────────────
# Skips itself when KAIZEN_DXM_DISABLE=1 or no events for cwd's session.
DXM_PART=$(python3 "$SCRIPT_DIR/statusline_dxm.py" --back 300 2>/dev/null || echo "")

# ─── intent live segment ─────────────────────────────────────────────
# Emits "intent: <id>" when an event_pattern intent matches the last
# 120s of dxm events. Empty when no match / no session / disabled.
INTENT_PART=$(python3 "$SCRIPT_DIR/statusline_intent.py" --back 120 2>/dev/null || echo "")

# ─── Compose ─────────────────────────────────────────────────────────
OUT=""
for part in "$CTX_PART" "$BACKLOG_PART" "$GATE_PART" "$DXM_PART" "$INTENT_PART"; do
    if [ -n "$part" ]; then
        if [ -z "$OUT" ]; then
            OUT="$part"
        else
            OUT="$OUT │ $part"
        fi
    fi
done

# Fallback: minimal non-empty string when nothing is wired
[ -z "$OUT" ] && OUT="kaizen"

echo "$OUT"
