---
name: review
description: Fast diff-time code review (per the article's "code review" definition). Runs against the current diff (HEAD vs base; staged if HEAD is clean). Lightweight, frequent, peer-style. Catches logic-error patterns, coding-skill violations, paired-test gaps, style drift, minor security smells. Pair with /kaizen:audit for periodic deep-dive.
argument-hint: [--scope <dir>|--base <ref>|--json|--agent]
---

# kaizen review

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/review.sh ${ARGUMENTS}`
