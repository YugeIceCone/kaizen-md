#!/usr/bin/env bash
# Stop hook — gentle reminder if backlog has in_flight items at end-of-turn.
# Soft signal only — never blocks Claude from stopping by default.
#
# Enable hard-block via env: KAIZEN_STOP_BLOCK_INFLIGHT=1

set -uo pipefail

# Discard event JSON
cat >/dev/null

REPO=$(git rev-parse --show-toplevel 2>/dev/null) || { echo '{}'; exit 0; }
cd "$REPO" || { echo '{}'; exit 0; }

# Resolve backlog.json via .kaizen.toml
[ -f ".kaizen.toml" ] || { echo '{}'; exit 0; }
BACKLOG_MD=$(grep -E '^backlog_path' .kaizen.toml 2>/dev/null \
    | head -1 \
    | sed -E 's/^[^=]*=[[:space:]]*"?([^"]*)"?.*$/\1/')
[ -z "$BACKLOG_MD" ] && { echo '{}'; exit 0; }
BACKLOG_JSON="${BACKLOG_MD%.md}.json"
[ -f "$BACKLOG_JSON" ] || { echo '{}'; exit 0; }

# Count in_flight items
INFLIGHT=$(python3 - "$BACKLOG_JSON" <<'PY' 2>/dev/null
import json, sys
try:
    data = json.load(open(sys.argv[1]))
    n = sum(1 for it in data.get("items", []) if it.get("section") == "in_flight")
    print(n)
except Exception:
    print(0)
PY
)

[ "$INFLIGHT" = "0" ] && { echo '{}'; exit 0; }

# Get titles for the reminder
TITLES=$(python3 - "$BACKLOG_JSON" <<'PY' 2>/dev/null
import json, sys
data = json.load(open(sys.argv[1]))
for it in data.get("items", []):
    if it.get("section") == "in_flight":
        print(f'  - {it["id"]}: {it["title"]}')
PY
)

# Hard-block mode (opt-in)
if [ "${KAIZEN_STOP_BLOCK_INFLIGHT:-}" = "1" ]; then
    python3 -c "
import json
print(json.dumps({
    'decision': 'block',
    'reason': '''$INFLIGHT in_flight backlog item(s) remain:
$TITLES
Tick them via /kaizen:backlog tick BK-N --committed <sha>, or move back to next_up if not actually started.'''
}))"
else
    # Soft reminder via systemMessage (won't block stop)
    python3 -c "
import json
print(json.dumps({
    'systemMessage': '''⚠ kaizen: $INFLIGHT in_flight backlog item(s) pending:
$TITLES
(set KAIZEN_STOP_BLOCK_INFLIGHT=1 to make this a hard block)'''
}))"
fi
