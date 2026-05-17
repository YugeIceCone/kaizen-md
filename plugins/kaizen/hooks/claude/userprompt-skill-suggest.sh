#!/usr/bin/env bash
# kaizen UserPromptSubmit hook — suggest skills to load based on
# trigger-phrase matches in the user's prompt.
#
# Complements intent-userprompt.sh (named workflows) with
# discipline / domain skill suggestions (onion-ddd, tdd, ast-grep,
# debugging, etc).
#
# Emits additionalContext listing top-3 matched skills. Empty when no
# match / no prompt / disabled.
#
# Bypass: KAIZEN_SKILL_SUGGEST_DISABLE=1

set -uo pipefail

[ "${KAIZEN_SKILL_SUGGEST_DISABLE:-}" = "1" ] && { echo '{}'; exit 0; }

_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || { echo '{}'; exit 0; }

# Single python3 spawn — userprompt_skill_suggest.py does the work.
python3 "$PLUGIN_ROOT/skills/workflow/scripts/userprompt_skill_suggest.py"
