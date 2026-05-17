---
name: rule
description: "DEPRECATED ALIAS — use `/kaizen:rules` (plural matches the bin `kaizen-rules`). Inspect, validate, or generate templates for brain-sourced kaizen rules."
---

# kaizen rule (deprecated alias)

**Use `/kaizen:rules` instead.** The slash and bin form (`kaizen-rules`) were inconsistent — singular slash, plural bin — so the canonical entry point was renamed to `/kaizen:rules`. This alias keeps the old name working.

!`python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/rules.py ${ARGUMENTS:-list}`
