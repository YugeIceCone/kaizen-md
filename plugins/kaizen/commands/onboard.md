---
name: onboard
description: Index a codebase for semantic search. SQLite + sentence-transformers (same model as /kaizen:trace-search and /kaizen:knowledge). Source files only (extension allowlist), comments stripped per-language, whitespace normalized. Project-scoped — db at `<repo>/.kaizen/onboard.db`. Pair with `/init` (Claude Code's built-in) for full onboarding: /init writes CLAUDE.md from a read-pass, /kaizen:onboard builds the semantic index.
argument-hint: [index|reindex|search "<query>"|stats|get <id>|path|clear]
---

# kaizen onboard

!`uv run --script ${CLAUDE_PLUGIN_ROOT}/scripts/indexers/onboard_index.py ${ARGUMENTS:-stats}`
