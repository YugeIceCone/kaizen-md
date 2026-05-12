---
name: publish
description: Publish this plugin/marketplace to GitHub. Subcommands cover the full lifecycle — gh auth setup, remote create, push, release tagging, fresh-history reset, and diagnostic. Handles the failure modes (SSH user mismatch, stale origin, ssh-askpass missing) documented in the `publishing` skill.
argument-hint: [status|auth|create-remote|push|tag <v>|reset-history|diagnose]
---

# kaizen publish

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/publish.sh ${ARGUMENTS:-status}`
