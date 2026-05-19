---
name: test
description: "TAP-style pipeline smoke-test (install → backlog → gate → hooks → backup → migrate). Distinct from /kaizen:test-suite (Python unittest+pytest)."
argument-hint: [-v|--keep]
---

# kaizen test

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/test-pipeline.sh $ARGUMENTS`
