---
name: deus-ex-machina
description: Live session-state mirror over Claude Code's session JSONL. Hook-driven sub-millisecond event capture; queryable real-time. Closes the 3-15s JSONL lag gap that makes scaffold/verify see stale state. Cross-session continuity via parent→child link. Triggers on "session lag", "JSONL stale", "real-time session state", "session continuity", "fresh session events", "kaizen-dxm".
metadata:
  version: "1.0"
---

# Deus ex machina — live session-state mirror

## ⚠ Iron Law — read in full

Skip nothing. The lag story (JSONL flushes per-turn, not per-event),
the hot-path discipline (shell-only capture, no python3 spawn), and
the cross-session continuity model only hang together as a whole.

## What this skill IS

A fast-store COMPANION to Claude Code's session JSONL. Doesn't
replace it — extends it.

CC writes session events to `~/.claude/projects/<slug>/<sid>.jsonl`
with buffered flushes (3-15s lag in practice — empirically measured).
That lag is fine for end-of-session mining (handoff `scaffold`) but
breaks any "what just happened a moment ago" use case.

`deus-ex-machina` solves this by:

1. **Sub-millisecond capture** via hooks (`dxm-event.sh` wired into
   PreToolUse / PostToolUse) — shell-only append, no python3 spawn.
2. **Real-time query API** (`kaizen-dxm now/tail`) — returns current
   session state with no buffer.
3. **Cross-session continuity** — `kaizen-dxm link --parent P --child C`
   records lineage; `now` surfaces it. Lets handoff resume read the
   PRIOR session's state to bridge the boundary.
4. **Graceful degradation** — `KAIZEN_DXM_DISABLE=1` bypasses; no
   external deps; tested in sandboxed `KAIZEN_DXM_DIR`.

## Why a separate store

Claude Code's JSONL is authoritative + comprehensive (every message,
thinking block, tool call, sub-agent stream). Three reasons NOT to
make it real-time:

- **Atomicity** — full message-with-content serialization needs to
  happen as one unit; piecemeal flushing risks partial-line corruption.
- **Volume** — 5 MB per long session; per-event sync would saturate disk.
- **Multi-consumer** — JSONL is read by other consumers (Anthropic
  console, web UI, eval pipelines); CC owns the flush cadence.

dxm is the opposite tradeoff: tiny per-event payload (just
`{ts_unix, session_id, evt_type, tool_name?}`), append-only, one file
per session, shell-only writes (zero python3 spawn).

## Storage layout

```
~/.claude/.kaizen/dxm/
├── events-<session_id>.jsonl     ← per-session event stream
├── events-<other_session>.jsonl
└── sessions.jsonl                 ← cross-session lineage (parent→child)
```

`KAIZEN_DXM_DIR` overrides root. Standard kaizen `~/.claude/.kaizen/`
namespace.

## Event shape

```json
{"ts_unix": 1747461308.876,
  "session_id": "66145c22-...",
  "evt_type": "PreToolUse",
  "tool_name": "Bash"}
```

`evt_type` is free-form (matches the hook name by convention).
`tool_name` is optional (set for tool-scoped events). Additional
fields preserved verbatim when supplied via `--payload`.

## CLI surface

    kaizen-dxm capture           # stdin = JSON event → append
    kaizen-dxm capture --payload '{"session_id":"...","evt_type":"x"}'

    kaizen-dxm now --session SID --json
      → envelope.data: {
          session_id, event_count, by_tool: {Bash:N, Edit:M, ...},
          last_event_at_unix, lag_seconds, parent_session_id?
        }

    kaizen-dxm tail --session SID [--limit 20] [--since-unix T] --json
      → envelope.data: {session_id, events: [...], count}

    kaizen-dxm link --parent P --child C
      → records P→C edge in sessions.jsonl

## Hot-path discipline

`dxm-event.sh` is in the PreToolUse / PostToolUse hook chain and
fires for EVERY tool call. Two non-negotiables:

1. **No python3 spawn.** Shell-only — `grep -oE`, `sed`, `date %s.%N`,
   `printf >>`. Saves ~50-200ms cold-start per fire vs spawning
   python3.
2. **Always exit 0.** Hook flow must not break on dxm failure. Worst
   case: events stop landing, but the host hook chain continues
   (consumers fall back to JSONL).

The macOS/BSD `date %s.%N` fallback: when GNU `%N` isn't supported,
fall back to one python3 spawn for the timestamp only. Linux hosts
(the common kaizen target) get pure-shell hot path.

## Cross-session continuity (the layered-on-top-of-CC bit)

Claude Code's session boundary is hard — when one session ends and
another begins, they're separate JSONLs with no built-in link. The
handoff feature bridges this on the WRITE side (handoff document
written at session end, read at next session start), but the
RUNTIME state continuity (open tasks, in-flight verdicts, recent
context) doesn't carry over.

`kaizen-dxm link` records the parent→child edge:

```bash
# At session end (auto-finalize Step 4 could call this):
kaizen-dxm link --parent <prev_sid> --child <new_sid>

# At session start (or any consumer that wants prior context):
kaizen-dxm now --session <new_sid> --json
# → parent_session_id surfaces; consumer can then:
kaizen-dxm tail --session <parent_sid> --limit 50
```

This gives any session a one-hop view to the prior session's recent
events. Multi-hop via repeated `now → tail` walks.

## Integration with handoff

The handoff `scaffold` subcommand mines the JSONL today
(see [handoff SKILL.md](../handoff/SKILL.md)). When the JSONL is
stale (lag_seconds > some threshold), scaffold COULD fall back to
dxm for fresh tool-call counts + last-event time. This is a
follow-up integration; today scaffold uses JSONL + accepts the lag.

Future loop:
- `scaffold` mines JSONL primary + dxm secondary for freshness
- `verify` consults dxm for "last N seconds of tool churn" when
  deciding clean/drift
- `auto-finalize` calls `dxm link --parent --child` to record the
  session→next-session edge

## TDD discipline

All 15 tests in `tests/test_dxm.py` cover:
- capture: append shape, ordering, missing-field rejection,
  malformed-JSON rejection, disable env
- now: event counts per tool, last_event_at, lag_seconds calculation,
  unknown-session empty
- tail: --limit N, --since-unix filtering
- link: parent→child recording, now surfaces parent

Sandboxing via `KAIZEN_DXM_DIR` env (matches kaizen feature
discipline — no `~/.claude/` writes during CI).

## Iron-law interaction

- **bin-wrapper-per-cli** — `bin/kaizen-dxm` wraps `dxm.py`.
- **plugin-manifest-permissions** — explicit perm entries in
  `plugin.json` for dxm.py + bin/kaizen-dxm + dxm-event.sh.
- **hook-bypass-knob** — `KAIZEN_DXM_DISABLE=1` honored by both
  the CLI and the hook script (early-exit before any writes).
- **sandbox-tests** — `KAIZEN_DXM_DIR` env per-test, no host
  contamination.

## What this skill is NOT

- A replacement for the JSONL. The JSONL is authoritative; dxm is the
  fast-store mirror. Anything dxm misses (e.g. between session restarts,
  before the hook fires) is recoverable from the JSONL.
- A general event-bus. dxm captures lifecycle events from CC hooks;
  it doesn't accept arbitrary application events from outside CC's
  hook chain. (If you want that, file a backlog item.)
- A telemetry pipeline. No remote sink, no metrics aggregation
  beyond `now`'s per-tool counts. The trace store (`kaizen-trace`) is
  the consumer-side telemetry surface; dxm is the producer-side
  freshness mirror.

## Sibling-skill relationships

`schema-driven-cli` — the lens runtime. dxm's `now` output matches
                       the v2 manifest's `now-out.schema.json`.

`handoff`           — the consumer that benefits most from dxm
                       freshness (scaffold + verify + auto-finalize).

`decision-rubric`   — `assess` could query dxm for live signals
                       (e.g. "have any failing tool calls happened in
                       the last 60s?") as a NEEDS_AGENT fallback.

`metrics`           — the lifetime telemetry surface (vs dxm's
                       session-scoped freshness mirror). Both consume
                       events; different time horizons.
