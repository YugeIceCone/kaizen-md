---
name: claude-docs
description: "Semantic search over local Claude API/Code/SDK docs mirror. Verbs - bootstrap | update | index | search | stats | get | path | clear."
argument-hint: [bootstrap|update|index|reindex|search "<query>"|stats|get <id>|path|clear --yes]
---

# kaizen claude-docs

Semantic search over a local Claude docs mirror (Claude API, Code, MCP, Agent SDK).

!`uv run --script ${CLAUDE_PLUGIN_ROOT}/scripts/indexers/claude_docs_index.py $ARGUMENTS`

Claude can also query this surface programmatically (no slash command needed) via the `kaizen-claude-docs` MCP server:

- `claude_docs_search(query, top_k=8)` — cosine top-k
- `claude_docs_stats()` — index meta + last_indexed_ts
- `claude_docs_get(chunk_id)` — full chunk text
- `claude_docs_list_files(limit=200)` — file index without embeddings
- `claude_docs_index_run()` — incremental reindex
