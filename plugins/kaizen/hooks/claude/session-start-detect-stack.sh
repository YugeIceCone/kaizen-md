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
# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || { echo '{}'; exit 0; }

EVENT=$(cat 2>/dev/null || echo '{}')
printf '%s' "$EVENT" | bash "$PLUGIN_ROOT/hooks/claude/_trace.sh" \
    SessionStart-detect-stack 2>/dev/null || true

DETECT="$PLUGIN_ROOT/skills/workflow/scripts/detect_stack.py"

# Resolve repo root (where .agents/ lives). Skip silently if we're
# not inside a project (no git, no manifest).
REPO=$(git rev-parse --show-toplevel 2>/dev/null) || REPO="$(pwd)"
ARTIFACT="$REPO/.agents/stack-context.md"

# Regen if missing or stale (>30 days). The `scan` subcommand
# self-short-circuits when fresh, so this is just a forced run on
# absence to ensure the artifact exists.
if [ ! -f "$ARTIFACT" ]; then
    cd "$REPO" && python3 "$DETECT" scan >/dev/null 2>&1 || {
        # Detection bailed (no manifests, no source files). Silent exit.
        echo '{}'
        exit 0
    }
fi

if [ ! -f "$ARTIFACT" ]; then
    echo '{}'
    exit 0
fi

# Inject artifact contents as additionalContext. Bounded to ~4KB
# (the typical artifact is well under) so we don't bloat the prompt.
python3 - "$ARTIFACT" <<'PYEOF'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
body = p.read_text(encoding="utf-8", errors="ignore")
if len(body) > 4096:
    body = body[:4093] + "..."
print(json.dumps({
    "additionalContext": (
        f"## Detected stack ({p})\n\n"
        f"{body}\n"
        f"\n(Auto-injected by session-start-detect-stack hook. "
        f"Disable: KAIZEN_DETECT_STACK_DISABLE=1)"
    )
}))
PYEOF
