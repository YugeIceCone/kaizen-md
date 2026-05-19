---
name: knowledge
description: "Semantic search over brain notes + plans + backlog + workflow schemas. SQLite + sentence-transformers. Verbs - index | search | stats."
argument-hint: [index|reindex|search "<query>"|stats|get <id>|path|clear]
---

# kaizen knowledge

!`uv run --script ${CLAUDE_PLUGIN_ROOT}/scripts/indexers/knowledge_index.py ${ARGUMENTS:-stats}`
