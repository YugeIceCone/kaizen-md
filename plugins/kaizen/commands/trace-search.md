---
name: trace-search
description: SQLite-backed semantic search over kaizen trace events. Sentence-transformers (default `all-MiniLM-L6-v2`, 384-dim) computes embeddings; cosine similarity ranks. Privacy-safe by default (embeds only event signature, never payload). Subcommands: index | reindex | search "<query>" | stats | get <id> | path | clear. Also exposed as `mcp__plugin_kaizen_kaizen-trace-search__*` MCP tools.
argument-hint: [index|reindex|search "<query>"|stats|get <id>|path|clear]
---

# kaizen trace-search

!`bash ${CLAUDE_PLUGIN_ROOT}/bin/kaizen-trace-index ${ARGUMENTS:-stats}`
