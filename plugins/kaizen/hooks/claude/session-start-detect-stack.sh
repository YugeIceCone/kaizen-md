#!/usr/bin/env bash
# session-start-detect-stack — auto-regen .agents/stack-context.md on
# session start if missing or stale, then inject the artifact contents
# as additionalContext so the agent sees the stack from prompt 1.
#
# Bypass: KAIZEN_DETECT_STACK_DISABLE=1
# Iron-law: fires _trace.sh + reads stdin defensively.

set -uo pipefail

if [ "${KAIZEN_DETECT_STACK_DISABLE:-}" = "1" ]; then echo '{}'; exit 0; fi

_SCRIPT_REAL="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null \
  || python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "${BASH_SOURCE[0]}")"
_HOOK_DIR="$(cd "$(dirname "$_SCRIPT_REAL")" && pwd)"
# shellcheck source=../../scripts/util/_plugin_root.sh
source "$_HOOK_DIR/../../scripts/util/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || { echo '{}'; exit 0; }

EVENT=$(cat 2>/dev/null || echo '{}')
printf '%s' "$EVENT" | bash "$PLUGIN_ROOT/hooks/claude/_trace.sh" \
    SessionStart-detect-stack 2>/dev/null || true

DETECT="$PLUGIN_ROOT/scripts/util/detect_stack.py"

# Resolve repo root (where .agents/ lives). Skip silently if we're
# not inside a project (no git, no manifest).
REPO=$(git rev-parse --show-toplevel 2>/dev/null) || REPO="$(pwd)"
# JSON is the system of record; .md is the derived view. We inject
# the markdown (denser, agent-friendlier than raw JSON) but persist
# both files.
JSON_ARTIFACT="$REPO/.agents/stack-context.json"
MD_ARTIFACT="$REPO/.agents/stack-context.md"

# Regen if JSON is missing or stale (>30 days).
if [ ! -f "$JSON_ARTIFACT" ]; then
    cd "$REPO" && python3 "$DETECT" scan >/dev/null 2>&1 || {
        echo '{}'
        exit 0
    }
fi

if [ ! -f "$JSON_ARTIFACT" ]; then
    echo '{}'
    exit 0
fi

# Inject the markdown view as additionalContext. Bounded to ~4KB.
python3 - "$MD_ARTIFACT" "$JSON_ARTIFACT" <<'PYEOF'
import json, sys
from pathlib import Path
md_path, json_path = Path(sys.argv[1]), Path(sys.argv[2])
body = md_path.read_text(encoding="utf-8", errors="ignore") if md_path.is_file() else json_path.read_text(encoding="utf-8", errors="ignore")
if len(body) > 4096:
    body = body[:4093] + "..."
print(json.dumps({
    "additionalContext": (
        f"## Detected stack ({md_path})\n\n"
        f"{body}\n"
        f"\n(Auto-injected by session-start-detect-stack hook. "
        f"Schema-validated source: `{json_path.name}`. "
        f"Disable: KAIZEN_DETECT_STACK_DISABLE=1)"
    )
}))
PYEOF
