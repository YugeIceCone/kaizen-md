---
name: flow
description: Run the async pocketflow Node+Flow demo over the current workspace. 4-node pipeline (ReadBacklog → DetectPackages → GenerateDocs → WriteReport) with parallel fan-out via asyncio.gather. No LLM calls, no pip deps — vendors AsyncNode + AsyncFlow.
argument-hint: [<workspace-dir>]
---

# kaizen flow

!`python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/flow_demo.py "${ARGUMENTS:-.}"`
