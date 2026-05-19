---
name: trace
description: "Unified event log across kaizen hooks/agents/LLM/tool/user actions. JSONL, auto-rotated. Verbs - tail | query | stats | event | clear | path | search | index. (search folded from /kaizen:trace-search.)"
argument-hint: "[tail [--n N] [--src S] [--evt E]|query|stats|event ...|clear|path|search \"<query>\"|index|reindex|get <id>]"
---

# kaizen trace

Raw event log — every kaizen hook/agent/LLM/tool action. JSONL, auto-rotated.

!`bash -c 'ARGS="${ARGUMENTS:-tail}"
case "$ARGS" in
  search|search\ *|index|index\ *|reindex|reindex\ *|get\ *|clear\ --yes*)
    # Semantic-search verbs (folded from retired /kaizen:trace-search).
    # Heavy-dep: sentence-transformers via uv-managed venv.
    exec bash ${CLAUDE_PLUGIN_ROOT}/bin/kaizen-trace-index $ARGS
    ;;
  *)
    exec python3 ${CLAUDE_PLUGIN_ROOT}/scripts/observe/trace.py $ARGS
    ;;
esac'`

## Verbs

| Verb | Backing | Notes |
|---|---|---|
| `tail` (default) | trace.py | most recent N events (JSONL filter) |
| `query` | trace.py | filtered slice |
| `stats` | trace.py | counts per src + evt |
| `event` | trace.py | emit one event (used by hooks) |
| `clear` / `path` | trace.py | maintenance |
| `search "<query>"` | kaizen-trace-index | **semantic** search over the same log (folded from retired `/kaizen:trace-search`). SQLite + sentence-transformers, 384-dim cosine. |
| `index` / `reindex` | kaizen-trace-index | (re)build the semantic index |
| `get <id>` | kaizen-trace-index | full event by row id |

The semantic verbs share the same JSONL source but route through the
heavy-dep `kaizen-trace-index` (uv-managed venv with
sentence-transformers). First invocation auto-installs the venv.

## Programmatic access

`kaizen-state` MCP server (read-only subset):
- `state_trace_tail(n=20, src="", evt="")` — most recent events as dicts
- `state_trace_stats()` — counts per src + evt
