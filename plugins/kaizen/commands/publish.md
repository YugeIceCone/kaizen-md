---
name: publish
description: "Publish plugin/marketplace to GitHub. Full lifecycle - gh auth | remote create | push | release tag | fresh-history reset | diagnostic."
argument-hint: [status|auth|create-remote|push|tag <v>|reset-history|diagnose]
---

# kaizen publish

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/publish.sh ${ARGUMENTS:-status}`
