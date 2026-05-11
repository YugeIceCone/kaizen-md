---
name: observe
description: Unified observability across kaizen's 6 data-stream layers (L1 stderr → L6 plugin state). Schema-driven (uses v1.9.0 dataclasses), with dynamic queries (live filtering) and deterministic snapshots (SHA1-content-keyed captures). Subcommands: layers | query | stats | drill <sid> | snapshot | compare | snapshots. Drill is the automated debugging recipe.
---

# kaizen observe

Unified observability surface across all 6 layers:

- **L1** live UI / stderr (ephemeral, skipped)
- **L2** CC transcript at `~/.claude/projects/<slug>/<sid>.jsonl`
- **L3** kaizen trace at `~/.claude/.kaizen-trace/events.jsonl`
- **L4** domain logs (daemon, proxy, inbox, compile)
- **L5** per-repo state (`.workflow/`, `.kaizen/cache/`, `.kaizen.toml`)
- **L6** plugin + global state (`installed_plugins.json`, `settings.json`, backups, brain)

!`python3 ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/observe.py ${ARGUMENTS:-layers}`

## Subcommands

- `layers` — JSON summary of all 6 layers (sizes, counts, last activity). Default if no arg.
- `query --sid SID --src S --evt E --since 1h [--json]` — unified L3-indexed query. Filters compose.
- `stats --since 1h [--sid SID]` — counts + latency percentiles; flags schema-invalid records.
- `drill <sid> [--out PATH]` — automated debugging recipe → Markdown report walking all 6 layers for one session.
- `snapshot [--name NAME]` — content-hashed capture of all layer summaries to `~/.claude/.kaizen-observe/snapshots/`. SHA1-keyed: same inputs = same composite hash = same snapshot.
- `compare <a> <b>` — diff two snapshot files; reports which layers changed.
- `snapshots` — list saved snapshots.

## Schema-driven

L3 trace events are validated via `schemas.TraceEvent` from v1.9.0. Records that fail validation (invalid `src` enum, missing `evt`, negative `ms`) are flagged with `_validation_errors` field and counted in `stats.invalid`.

## Dynamic vs deterministic

- `query`, `tail`, `stats` are **dynamic** — read the live state every time, no caching.
- `snapshot` + `compare` are **deterministic** — content-keyed by SHA1. Byte-identical layer state produces byte-identical snapshot bytes. Use for reproducible point-in-time analysis, regression detection, "did anything change between session X and Y" questions.

## Debugging recipe

The canonical drill-down (recommended in the v1.8.0 agent-brief skill, now automated by `drill`):

1. **L3 stats** — fastest "what's happening" overview
2. **L3 query --sid** — narrow to one session
3. **L2 transcript** — full payload (commands, responses) for suspect records
4. **L4 domain log** — only if trace points at proxy/daemon/inbox
5. **L5 per-repo state** — only for gate/backlog/workflow concerns
6. **L6 plugin state** — only for "is this even installed/enabled"

`drill <sid>` runs steps 1–6 in order and emits a single Markdown report with findings + recommended next actions.

## Usage examples

```bash
# Top-level health check
kaizen-observe layers | jq '.L3_kaizen_trace, .L4_domain_logs'

# Stats for last 24h
kaizen-observe stats --since 24h

# All LLM events this session
kaizen-observe query --src llm --sid <session-uuid>

# Full drill-down for a session, saved as Markdown
kaizen-observe drill <sid> --out /tmp/debug.md

# Capture state, do something, capture again, compare
kaizen-observe snapshot --name before
# ... run commands ...
kaizen-observe snapshot --name after
kaizen-observe compare before.json after.json
```

## Composition with kaizen layers

This is the **read layer** for everything kaizen already produces:

- v1.9.0 `schemas.py` provides the typed contracts; observe validates against them
- v1.6.x `trace.py` produces the L3 events that observe indexes
- v1.4.x `inbox.py` produces L4 inbox records
- v1.5.x `daemon.py` produces L4 daemon logs
- v1.7.x `browser_mcp.py` events flow through hooks → L3 trace
- gate/backlog/workflow state lives in L5; observe summarizes it

No new instrumentation. `observe` is purely a unified reader + analyzer.
