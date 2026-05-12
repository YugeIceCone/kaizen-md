---
name: trace-search
description: SQLite-backed semantic search over kaizen trace events. Sentence-transformers (default `all-MiniLM-L6-v2`, 384-dim) computes embeddings; cosine similarity ranks. Privacy-safe by default (embeds only event signature, never payload). Subcommands: index | reindex | search "<query>" | stats | get <id> | path | clear. Also exposed as `mcp__plugin_kaizen_kaizen-trace-search__*` MCP tools.
---

# kaizen trace-search

Semantic search over the kaizen trace event log. Stores embeddings in `~/.claude/.kaizen-trace/index.db` (SQLite). Sentence-transformers + numpy via uv PEP 723.

!`bash ${CLAUDE_PLUGIN_ROOT}/bin/kaizen-trace-index ${ARGUMENTS:-stats}`

## First-time setup

```bash
# Index existing trace events (~30s first time: downloads model + torch)
kaizen-trace-index index

# Verify
kaizen-trace-index stats
```

uv reads the PEP 723 inline metadata in `trace_index.py` and installs `sentence-transformers + numpy` to a cached venv. First call also downloads the model weights (~80MB) from HuggingFace.

## Subcommands

- `index [--max N] [--embed-data]` — incremental index of new events; skips already-indexed via content-hash dedup. `--embed-data` also embeds safe data fields (model, status, verdict). Default does NOT embed payload (privacy-safe).
- `reindex` — drop the table + rebuild from scratch (use after model change).
- `search "<query>" [--top-k 10] [--src S] [--sid SID] [--evt E] [--since 1h] [--json]` — semantic search. Filters compose. Score is cosine similarity in [0, 1].
- `stats` — total indexed, model, earliest/latest ts.
- `get <id>` — fetch full event by SQLite id (from a search result).
- `path` — print db path.
- `clear` — remove the SQLite file (next index rebuilds).

## Privacy model

By default, ONLY the event SIGNATURE is embedded:
- `src`, `evt`, `tool`, sid prefix (first 8 chars), latency category (fast/normal/slow/very_slow)

NO commands, file paths, prompts, or payload data. The SQL row still stores `data_json` for retrieval (queryable but not part of the semantic distance).

`--embed-data` opt-in adds these safe data fields: `model`, `status`, `verdict`, `outcome`, `kind`. Sensitive fields (`Authorization`, `command`, full prompts) are NEVER embedded regardless of flag.

## MCP tools (post-/reload-plugins)

Five `mcp__plugin_kaizen_kaizen-trace-search__*` tools exposed:

- `trace_search(query, top_k, src, sid, evt, since)` — semantic search
- `trace_index_status()` — health check
- `trace_index_run(embed_data, max_n)` — incremental re-index
- `trace_get(event_id)` — fetch by id
- `trace_recent(limit, src)` — latest N events (no ranking — fast)

The MCP server is registered in `.mcp.json` as `kaizen-trace-search`. Claude Code spawns it on-demand at first tool call. Single sentence-transformers model loaded across tool calls (~500MB RAM after first; instant embeddings thereafter).

## Query examples

```bash
# What slow events happened today?
kaizen-trace-index search "slow tool calls" --top-k 20 --since 24h

# Find LLM-related errors
kaizen-trace-index search "llm error or failure" --src llm

# Bash tool boundaries in a specific session
kaizen-trace-index search "shell command execution" --sid <uuid> --src hook

# JSON output for pipelining
kaizen-trace-index search "agent invocation" --json | jq '.[].id'
```

## Composition with other layers

- L3 trace events (events.jsonl) → indexed here as a queryable layer
- v1.9.0 `schemas.TraceEvent` validates on read (via observe.py); trace-search assumes valid events
- v1.10.0 `kaizen-observe drill` is the broad cross-layer report; trace-search is the deep semantic-narrow query

Use `observe drill` to see "what happened in session X across all 6 layers". Use `trace-search` to find "events that look like Y, semantically" across all time.

## Daemon integration (deferred)

The v1.5.x daemon's tick could call `trace-index index` to keep embeddings current. Not yet wired — manual re-index needed for now. Future micro: add `index_trace` to hygiene checks.
