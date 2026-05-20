#!/usr/bin/env bash
# Notification hook — surface kaizen state when Claude Code notifies
# the user (e.g. permission request, attention prompt).
#
# Additive: appends a one-line kaizen status (in-flight backlog count,
# gate health) to the Notification event's additionalContext so the
# user sees current state alongside whatever CC is notifying about.
#
# Cross-CLI compat: Notification is Claude-Code-specific. Hosts that
# don't fire it never invoke this script.
#
# Disable via env: KAIZEN_NOTIFY_QUIET=1.

set -uo pipefail

if [ "${KAIZEN_NOTIFY_QUIET:-0}" = "1" ] || [ "${KAIZEN_NOTIFICATION_DISABLE:-0}" = "1" ]; then
    echo '{}'
    exit 0
fi

_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../scripts/util/_plugin_root.sh
source "$_HOOK_DIR/../../scripts/util/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || { echo '{}'; exit 0; }

EVENT=$(cat 2>/dev/null || echo '{}')
printf '%s' "$EVENT" | bash "$PLUGIN_ROOT/hooks/claude/_trace.sh" Notification

REPO=$(git rev-parse --show-toplevel 2>/dev/null || echo "")
[ -z "$REPO" ] && { echo '{}'; exit 0; }
[ ! -f "$REPO/.kaizen.toml" ] && { echo '{}'; exit 0; }

# Resolve backlog
BACKLOG_MD=$(grep -E '^backlog_path' "$REPO/.kaizen.toml" 2>/dev/null \
    | head -1 \
    | sed -E 's/^[^=]*=[[:space:]]*"?([^"]*)"?.*$/\1/')
BACKLOG_MD="${BACKLOG_MD:-.kaizen/workflow/backlog.md}"
BACKLOG_JSON="$REPO/${BACKLOG_MD%.md}.json"

INFLIGHT=0
NEXTUP=0
if [ -f "$BACKLOG_JSON" ]; then
    COUNTS=$(python3 - "$BACKLOG_JSON" <<'PY' 2>/dev/null
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    items = d.get("items", [])
    inflight = sum(1 for i in items if i.get("section") == "in_flight")
    nextup = sum(1 for i in items if i.get("section") == "next_up")
    print(f"{inflight} {nextup}")
except Exception:
    pass
PY
)
    if [ -n "${COUNTS:-}" ]; then
        INFLIGHT=$(echo "$COUNTS" | awk '{print $1}')
        NEXTUP=$(echo "$COUNTS" | awk '{print $2}')
    fi
fi

# Gate state — symlink present means kaizen install is live
GATE=""
if [ -L "$REPO/.kaizen/hooks/pre-commit" ]; then
    GATE="🟢 gate"
fi

# Compose. Only surface a non-empty message when there's something
# worth showing; otherwise stay silent.
PARTS=""
if [ "$INFLIGHT" != "0" ]; then
    PARTS="🔵 $INFLIGHT in flight"
fi
if [ "$NEXTUP" != "0" ]; then
    if [ -n "$PARTS" ]; then PARTS="$PARTS · "; fi
    PARTS="${PARTS}⚪ $NEXTUP next up"
fi
if [ -n "$GATE" ]; then
    if [ -n "$PARTS" ]; then PARTS="$PARTS · "; fi
    PARTS="${PARTS}${GATE}"
fi

if [ -z "$PARTS" ]; then
    echo '{}'
    exit 0
fi

PARTS_ENV="$PARTS" python3 - <<'PY'
import json, os
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "Notification",
        "additionalContext": f"kaizen: {os.environ['PARTS_ENV']}",
    }
}))
PY
