---
name: flow
description: "Async Node+Flow demo pipeline over the current workspace. 4 nodes (ReadBacklog → DetectPackages → GenerateDocs → WriteReport). asyncio.gather fan-out. No deps."
argument-hint: [<workspace-dir>]
---

# kaizen flow

!`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/workflow/flow.py "${ARGUMENTS:-.}"`
