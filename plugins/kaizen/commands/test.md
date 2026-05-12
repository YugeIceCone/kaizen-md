---
name: test
description: Run the full kaizen pipeline smoke-test (install → backlog → gate → hooks → backup → migrate). TAP-style output, detail only on failures. Low token usage by default. Pass -v / --keep for verbose / preserve sandbox.
argument-hint: [-v|--keep]
---

# kaizen test

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/test-pipeline.sh $ARGUMENTS`
