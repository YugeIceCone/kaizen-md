---
name: flow
description: Run the async pocketflow Node+Flow reference pipeline over the current workspace. 4 nodes (ReadBacklog → DetectPackages → GenerateDocs → WriteReport) with parallel fan-out via asyncio.gather. No LLM calls, no pip deps — vendors AsyncNode + AsyncFlow as kaizen's canonical Node+Flow primitives. See skills/workflow/references/node-flow.md.
argument-hint: [<workspace-dir>]
---

# kaizen flow

!`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/workflow/flow.py "${ARGUMENTS:-.}"`
