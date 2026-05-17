---
name: research
description: Gathers external facts from official docs, APIs, standards, and comparable implementations. Use when answers depend on sources outside the repo.
metadata:
  version: "1.1"
---

# Topic Researching

Gathers external facts from official docs, APIs, standards, and comparable implementations. Use this skill when the answer depends on facts outside the current repo or when the user needs sourced evidence.

## Research Modes

**First-choice doc source: Context7 MCP.** For any library, framework,
SDK, API, or CLI tool, use `resolve-library-id` then `query-docs`
before web search — it returns version-current documentation and code
examples. Web search and the legacy `*_docs.py` shims are the
fallback when Context7 has no coverage.

- external docs -> official docs, standards, changelogs, current APIs
- comparable implementations -> reference repos or current ecosystem examples
- mixed -> combine external sources with local code context

## Research Flow

1. State the exact question to answer.
2. Decide whether the work is external, local, or mixed.
3. Prefer primary sources and official docs.
4. Gather the smallest reliable source set.
5. Summarize the evidence with links, dates, and takeaways.
6. Hand off to **change-analyzing**, **create-plan**, or **plan-validating** if action follows.

## Compatibility Tooling

When deterministic local dry-runs or fixture-backed tests are useful, use the legacy compatibility shims in:

- `scripts/legacy_tool_shims/nia_docs.py`
- `scripts/legacy_tool_shims/perplexity_search.py`
- `scripts/legacy_tool_shims/firecrawl_scrape.py`
- `scripts/legacy_tool_shims/web_search.py`
- `scripts/legacy_tool_shims/web_fetch.py`

Use those only as local compatibility aids. Prefer live Codex and web tooling for real research.

## Evidence Standards

- cite links when external sources are used
- include concrete dates for current guidance when freshness matters
- separate observed evidence from your recommendation
- state uncertainty explicitly when the evidence is incomplete

## Companion Skills

- **codebase-exploring** -> local codebase orientation
- **change-analyzing** -> turn research into change constraints
- **plan-validating** -> final go or no-go assessment against current practice

## Agent Roles

Use the home agent catalog as role guidance:

- `external-researching` -> official docs and current best practices
- `dependency-analyzing` -> external repository analysis and examples
- `durable-note-taking` -> durable research notes when the user wants them

Use delegation only if the user explicitly asks for it.

## Rules

- Prefer official docs over secondary summaries when they exist.
- Do not guess on freshness when you can verify it.
- Prefer direct responses over mandatory handoff files.
- Avoid Markdown tables.
