#!/usr/bin/env bash
# userprompt-intake-autoload — match user prompt against the plugin-dev
# intake-checklist and emit the skills-to-load bundle as systemMessage.
#
# Closes the Phase-10 loop: instead of the agent firing
# `/kaizen:plugin-development intake` then AskUserQuestion, the hook
# does the match on UserPromptSubmit and surfaces the skill bundle
# directly. Agent loads the right skills BEFORE writing code.
#
# Decision:
#   match  → echo {"systemMessage": "kaizen-intake: load Skill(plugin:X), Skill(plugin:Y), ..."}
#   miss   → echo {} (silent)
#
# Bypass: KAIZEN_INTAKE_AUTOLOAD_DISABLE=1
# Iron-law: fires _trace.sh + reads stdin defensively.

set -uo pipefail

if [ "${KAIZEN_INTAKE_AUTOLOAD_DISABLE:-}" = "1" ]; then echo '{}'; exit 0; fi

_SCRIPT_REAL="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null \
  || python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "${BASH_SOURCE[0]}")"
_HOOK_DIR="$(cd "$(dirname "$_SCRIPT_REAL")" && pwd)"
# shellcheck source=../../scripts/util/_plugin_root.sh
source "$_HOOK_DIR/../../scripts/util/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || { echo '{}'; exit 0; }

EVENT=$(cat 2>/dev/null || echo '{}')
printf '%s' "$EVENT" | bash "$PLUGIN_ROOT/hooks/claude/_trace.sh" \
    UserPromptSubmit-intake 2>/dev/null || true

# Single python3 spawn: extract prompt + match against intake-checklist
# + emit hook-decision JSON. Falls back to `{}` on any failure (never
# break the host prompt cycle).
# Use env var to pass the event JSON into Python — heredoc collides
# with stdin redirection otherwise.
KAIZEN_INTAKE_EVENT="$EVENT" python3 - "$PLUGIN_ROOT" <<'PYEOF'
import json, os, sys
from pathlib import Path

PLUGIN_ROOT = Path(sys.argv[1])
INTAKE = PLUGIN_ROOT / "scripts/plugin_development/intake.py"
CHECKLIST = PLUGIN_ROOT / "schemas/plugin-development/intake-checklist.yaml"

def _emit(obj):
    print(json.dumps(obj))
    sys.exit(0)

try:
    event = json.loads(os.environ.get("KAIZEN_INTAKE_EVENT") or "{}")
except (json.JSONDecodeError, ValueError):
    _emit({})

prompt = (event.get("prompt") or "").strip()
if not prompt or len(prompt) < 4:
    _emit({})

# Load the checklist directly — cheaper than spawning intake.py.
try:
    import yaml
    data = yaml.safe_load(CHECKLIST.read_text())
except (ImportError, OSError):
    _emit({})

always = data.get("always", [])
target = prompt.lower()
matched = None
for wt in data.get("work_types", []):
    for trig in wt.get("triggers", []):
        if trig.lower() in target:
            matched = wt
            break
    if matched:
        break

if matched is None or not matched.get("skills"):
    _emit({})

bundle = always + matched.get("skills", [])
bundle_str = ", ".join(f"Skill({s})" for s in bundle)
_emit({
    "systemMessage": (
        f"kaizen-intake [{matched['id']}]: "
        f"load before writing code → {bundle_str}"
    )
})
PYEOF
