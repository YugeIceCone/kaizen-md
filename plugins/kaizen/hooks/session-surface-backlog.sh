#!/usr/bin/env bash
# kaizen SessionStart hook — surface active backlog at session start.
# Reads <workflow_dir>/backlog.json (resolved via .kaizen.toml) and
# emits the In flight + Next up items as additionalContext so the agent
# sees pending work without manual probing.
#
# Silent no-op when:
#   - not in a git repo
#   - no .kaizen.toml
#   - no backlog.json exists yet
#   - the in_flight + next_up sections are both empty

set -u

# Repo root
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
    echo "{}"
    exit 0
}
cd "$REPO_ROOT" 2>/dev/null || { echo "{}"; exit 0; }

# Resolve backlog_path from .kaizen.toml
CONFIG="$REPO_ROOT/.kaizen.toml"
BACKLOG_MD=""
if [ -f "$CONFIG" ]; then
    BACKLOG_MD=$(grep -E '^backlog_path' "$CONFIG" 2>/dev/null \
        | head -1 \
        | sed -E 's/^[^=]*=[[:space:]]*"?([^"]*)"?.*$/\1/')
fi
[ -z "$BACKLOG_MD" ] && { echo "{}"; exit 0; }

BACKLOG_JSON="${BACKLOG_MD%.md}.json"
BACKLOG_JSON_ABS="$REPO_ROOT/$BACKLOG_JSON"
[ -f "$BACKLOG_JSON_ABS" ] || { echo "{}"; exit 0; }

# Use python3 to extract the active items.
SUMMARY=$(python3 - "$BACKLOG_JSON_ABS" 2>/dev/null <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
items = data.get("items", [])
sections = {"in_flight": [], "next_up": []}
for it in items:
    s = it.get("section")
    if s in sections:
        sections[s].append(it)

if not sections["in_flight"] and not sections["next_up"]:
    sys.exit(0)

lines = ["**kaizen backlog (active):**", ""]
if sections["in_flight"]:
    lines.append("## In flight")
    for it in sections["in_flight"]:
        line = f"- **{it['id']}** {it['title']}"
        if it.get("verify"):
            line += f"  — verify: `{it['verify']}`"
        lines.append(line)
    lines.append("")
if sections["next_up"]:
    lines.append("## Next up (top 5)")
    for it in sections["next_up"][:5]:
        line = f"- **{it['id']}** {it['title']}"
        if it.get("probe"):
            line += f"  — probe: `{it['probe']}`"
        lines.append(line)
    lines.append("")
print("\n".join(lines).rstrip())
PY
)

if [ -z "$SUMMARY" ]; then
    echo "{}"
    exit 0
fi

# Emit JSON for Claude Code hook protocol
python3 - <<PY
import json
ctx = """$SUMMARY"""
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": ctx
    }
}))
PY
