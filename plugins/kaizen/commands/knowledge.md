---
name: knowledge
description: Semantic search over kaizen's knowledge surface — Remember brain notes, project plans, backlog items, workflow schemas, persona beliefs. SQLite + sentence-transformers (same model as /kaizen:trace-search). Privacy-safe by default (signature embedding only; body opt-in). Pair with `self-rag` skill for retrieval discipline.
argument-hint: [index|reindex|search "<query>"|stats|get <id>|path|clear]
---

# kaizen knowledge

!`python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/knowledge_index.py ${ARGUMENTS:-stats}`
