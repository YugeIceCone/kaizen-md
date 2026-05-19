---
name: onboard
description: "Semantic index for codebase search. SQLite + sentence-transformers. Project-scoped DB at <repo>/.kaizen/onboard.db. Pair with /init for full onboarding."
argument-hint: [index|reindex|search "<query>"|stats|get <id>|path|clear]
---

# kaizen onboard

!`uv run --script ${CLAUDE_PLUGIN_ROOT}/scripts/indexers/onboard_index.py ${ARGUMENTS:-stats}`
