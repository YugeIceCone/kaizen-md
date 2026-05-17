#!/usr/bin/env bash
# kaizen statusline — backlog + context + gate state in one line.
#
# Wire via user's ~/.claude/settings.json:
#
#   "statusLine": {
#     "type": "command",
#     "command": "bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/statusline.sh"
#   }
#
# Or use /kaizen:statusline install for guided setup.
#
# Reads JSON event from stdin (Claude Code statusline schema). Writes
# one line to stdout. Designed to render in <50 ms.

set -uo pipefail

INPUT=$(cat 2>/dev/null || echo "")

SCRIPT_DIR="$(cd "$(dirname "$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")")" && pwd)"

# ─── Context window ──────────────────────────────────────────────────
CTX_JSON=$(echo "$INPUT" | python3 "$SCRIPT_DIR/context.py" json 2>/dev/null || echo "{}")
CTX_TOKENS=$(echo "$CTX_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('tokens') or '')" 2>/dev/null || echo "")
CTX_LIMIT=$(echo "$CTX_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('limit') or 200000)" 2>/dev/null || echo "200000")
CTX_PCT=$(echo "$CTX_JSON"   | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('pct') if d.get('pct') is not None else '')" 2>/dev/null || echo "")
CTX_ZONE=$(echo "$CTX_JSON"  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('zone','unknown'))" 2>/dev/null || echo "unknown")

CTX_PART=""
if [ -n "$CTX_TOKENS" ] && [ "$CTX_TOKENS" != "None" ]; then
    case "$CTX_ZONE" in
        green)  ICON="🟢" ;;
        yellow) ICON="🟡" ;;
        red)    ICON="🔴" ;;
        *)      ICON="⚪" ;;
    esac
    CTX_K=$(( CTX_TOKENS / 1000 ))
    LIMIT_K=$(( CTX_LIMIT / 1000 ))
    CTX_PART="${ICON} ${CTX_K}k/${LIMIT_K}k"
    [ -n "$CTX_PCT" ] && CTX_PART="${CTX_PART} (${CTX_PCT}%)"
fi

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

# ─── Compose ─────────────────────────────────────────────────────────
OUT=""
for part in "$CTX_PART" "$BACKLOG_PART" "$GATE_PART" "$DXM_PART"; do
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
