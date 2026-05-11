#!/usr/bin/env bash
# PostToolUse(Bash) hook — when Claude runs `git commit`, suggest ticking
# backlog items mentioned in the commit message.
#
# Emits additionalContext only (soft suggestion). Never blocks.

set -uo pipefail

EVENT=$(cat 2>/dev/null || echo '{}')

# Extract command + exit info
COMMAND_INFO=$(printf '%s' "$EVENT" | python3 - <<'PY' 2>/dev/null
import json, sys
try:
    e = json.load(sys.stdin)
    cmd = e.get("tool_input", {}).get("command", "")
    result = e.get("tool_result", {})
    rtype = result.get("type", "")
    content = result.get("content", "") if isinstance(result.get("content"), str) else json.dumps(result.get("content", ""))
    print(cmd)
    print(rtype)
    print(content[:2000])
except Exception:
    pass
PY
)

CMD=$(echo "$COMMAND_INFO" | sed -n '1p')
RTYPE=$(echo "$COMMAND_INFO" | sed -n '2p')

# Only interested in `git commit` invocations
if ! echo "$CMD" | grep -qE '(^|[^a-zA-Z])git[[:space:]]+commit'; then
    echo '{}'
    exit 0
fi
# Tool errored → no suggestion
[ "$RTYPE" = "error" ] && { echo '{}'; exit 0; }

REPO=$(git rev-parse --show-toplevel 2>/dev/null) || { echo '{}'; exit 0; }
cd "$REPO" || { echo '{}'; exit 0; }

# Resolve backlog.json
[ -f ".kaizen.toml" ] || { echo '{}'; exit 0; }
BACKLOG_MD=$(grep -E '^backlog_path' .kaizen.toml 2>/dev/null \
    | head -1 \
    | sed -E 's/^[^=]*=[[:space:]]*"?([^"]*)"?.*$/\1/')
BACKLOG_JSON="${BACKLOG_MD%.md}.json"
[ -f "$BACKLOG_JSON" ] || { echo '{}'; exit 0; }

# Get the just-landed commit message
COMMIT_MSG=$(git log -1 --format="%B" 2>/dev/null)
[ -z "$COMMIT_MSG" ] && { echo '{}'; exit 0; }

# Match in_flight item ids (BK-NNN) or title fragments against the commit
SUGGESTION=$(python3 - "$BACKLOG_JSON" <<PY 2>/dev/null
import json, re, sys
data = json.load(open(sys.argv[1]))
commit = """$COMMIT_MSG"""
matches = []
for it in data.get("items", []):
    if it.get("section") != "in_flight":
        continue
    item_id = it["id"]
    # Strong signal: id explicitly mentioned
    if re.search(rf'\b{re.escape(item_id)}\b', commit):
        matches.append((item_id, it["title"], "id"))
        continue
    # Weaker signal: first 4+ words of title appear in commit
    title_words = it["title"].split()[:4]
    title_frag = " ".join(title_words)
    if len(title_frag) >= 16 and title_frag.lower() in commit.lower():
        matches.append((item_id, it["title"], "title"))
if matches:
    short_sha = ""
    print(f"⚙ kaizen: commit landed; in_flight backlog item(s) likely tied:")
    for mid, title, kind in matches:
        print(f"  - {mid} ({kind}-match): {title}")
    print(f"  Tick: /kaizen:backlog tick <id> --committed <short-sha>")
PY
)

if [ -z "$SUGGESTION" ]; then
    echo '{}'
    exit 0
fi

python3 -c "
import json
print(json.dumps({
    'hookSpecificOutput': {
        'hookEventName': 'PostToolUse',
        'additionalContext': '''$SUGGESTION''',
    }
}))
"
