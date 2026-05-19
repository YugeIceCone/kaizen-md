---
name: trace
description: Unified event log across kaizen hooks, agents, LLM calls, tool invocations, and user actions. JSONL-backed, fast queries, auto-rotation. Subcommands: tail | query | stats | event | clear | path. Use to debug "what fired when", trace agent dispatch, see hook latency distribution, find LLM cost outliers.
argument-hint: [tail [--n N] [--src S] [--evt E]|query|stats|event ...|clear|path]
---

# kaizen trace

Raw event log — every kaizen hook/agent/LLM/tool action. JSONL, auto-rotated.

!`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/observe/trace.py ${ARGUMENTS:-tail}`

Programmatic access via the `kaizen-state` MCP server (read-only subset):

- `state_trace_tail(n=20, src="", evt="")` — most recent events as dicts
- `state_trace_stats()` — counts per src + evt

For semantic search over the same log, use the `kaizen-trace-search` MCP server.
