---
name: cache
description: Inspect, clear, or query the kaizen per-repo cache at `<repo>/.kaizen/cache/`. Used by the compile-barrier check to skip redundant `cargo check` / `tsc --noEmit` / etc. runs when staged content is unchanged, and by agents (kaizen-reviewer) to memoize verdicts by diff sha.
argument-hint: [stats|key <part1> [part2 ...]|get <key>|put <key> <json>|delete <key>|clear]
---

# kaizen cache

Per-repo hash-keyed JSON cache at `<repo>/.kaizen/cache/`. Hash-invalidated, no TTL.

!`python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/cache.py ${ARGUMENTS:-stats}`

Programmatic access via the `kaizen-state` MCP server: `state_cache_stats()` returns `{count, bytes, dir, exists}`.

Mutating ops (`put`, `delete`, `clear`) stay slash-only.
