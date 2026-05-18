# Shared coordination pool — brainstorm

> ⚠️ **PARTIALLY SUPERSEDED** — clever-lama's persistence layer (`learnings` table + FTS5, `recall_learnings`, `recall_semantic`, `skill_stats`) already provides 70%+ of what Phases B1-B3 proposed. The remaining ~30% is Phase A1 (heartbeat ledger) which may still be worth a thin layer. See [`CLEVER_LAMA_INTEGRATION.md`](CLEVER_LAMA_INTEGRATION.md) for the integration story.
> **Disciplines:** all rules in [`DISCIPLINES.md`](DISCIPLINES.md) apply.

> User idea: "shared pool maybe a ledger (state) so agents can communicate with each other to solve issues that crop up"

The current design eliminates cross-cutting writes (great for safety, eliminates whole classes of conflicts). But it also eliminates agent-to-agent communication entirely — every coordination problem must escalate to the parent orchestrator or get deferred to MERGE. This brainstorm explores adding a thin shared pool to bridge that gap WITHOUT re-introducing race conditions.

## What problems would a shared pool actually solve?

Mapping pool-able gaps from the audit:

| Audit gap | Pool helps how |
|---|---|
| **#4** silent ownership collisions | Agents check pool before writing files outside their declared `owns:` list |
| **#6** auto-handoff trigger not wired | Agent posts `tokens_used` heartbeat; parent sees > 30k and instructs handoff |
| **#7** handoff parentage | Posted as a `handoff` event with `parent_chunk_id` |
| **#11** no live progress monitoring | Pool IS the live progress stream |
| **W5** inter-wave failure recovery | Failed agent posts to pool; parent decides policy at run-time |
| **W4** cross-wave dep readiness | Chunk-12 queries pool for chunk-3 status before starting |
| **NEW** reusable discoveries | Chunk-4 builds a helper → posts → siblings reuse instead of reinventing |
| **NEW** cross-agent help requests | Chunk-3 stuck on a design decision → posts → sibling answers |

Coordination gaps the pool would NOT solve:
- Merge handlers being vaporware (#5)
- Prompt generator missing (#2)
- Worktree orchestration missing (#3)
- Schema cross-chunk uniqueness (#8 — still pre-flight)

## 5 shapes considered

### Shape A — read-only heartbeat ledger (KISS minimum)

```
.chunks/SHARED/heartbeats.jsonl    ← append-only; one row per significant event
```

```jsonl
{"ts": "T1", "chunk_id": "chunk-3", "event": "started", "wave": 1}
{"ts": "T2", "chunk_id": "chunk-3", "event": "iter_done", "item_id": "3.A", "progress": 0.33, "tokens_used": 8400}
{"ts": "T3", "chunk_id": "chunk-3", "event": "iter_done", "item_id": "3.B", "progress": 0.66, "tokens_used": 16100}
{"ts": "T4", "chunk_id": "chunk-3", "event": "completed", "commit_sha": "abc123", "tokens_used": 22000}
```

- Agents WRITE only their own rows (single-writer per row → no race)
- Agents READ the whole file periodically to see plan-wide state
- Parent reads for orchestration (auto-handoff trigger, failure detection)
- Append-only JSONL → no locking, conflict-free
- Validated by `heartbeat.schema.json`

**Solves:** #6, #7, #11, partial W4, partial W5
**Cost:** ~1-2k tokens per agent per read; ~50-100k total across plan

### Shape B — append-only message bus

```
.chunks/SHARED/messages.jsonl      ← append-only; typed inter-agent messages
```

```jsonl
{"ts": "T5", "from": "chunk-4", "type": "discovery", "payload": {"helper": "axis_runner_rules.run_grep", "path": "..."}}
{"ts": "T6", "from": "chunk-3", "type": "help", "payload": {"question": "verb-list — domain/ or scripts/ constant?"}, "blocking": true}
{"ts": "T7", "from": "chunk-7", "type": "response", "in_reply_to_ts": "T6", "payload": {"answer": "domain/", "rationale": "..."}}
{"ts": "T8", "from": "chunk-2", "type": "ownership_query", "payload": {"path": "skills/.../foo.py", "intent": "modify"}}
{"ts": "T9", "from": "chunk-5", "type": "ownership_grant", "in_reply_to_ts": "T8", "payload": {"path": "skills/.../foo.py", "granted": true, "until": "T+10min"}}
```

Message types:
- `status` — duplicate of heartbeat (Shape A subsumes)
- `discovery` — built something reusable mid-chunk
- `help` — need a decision; blocks until response or timeout
- `response` — answer to a `help` or `query`
- `ownership_query` — proposing to touch a file outside your `owns:`
- `ownership_grant` — yes/no on the query
- `failure` — I failed; here's why
- `dep_ready` — broadcasts dep completion (subsumed by `heartbeat.event == completed`)

**Solves:** #4 (via ownership_query/grant), discoveries (NEW), help-loop (NEW)
**Cost:** higher (~3-5k per agent for message read + 1-2k per message posted)

### Shape C — parent-arbitrated only

Agents emit coordination requests in their own output (no pool file); parent reads them on Agent() completion and arbitrates by injecting context into the next agent. Heavier parent involvement; agents stay pure.

**Pros:** no shared mutable state; single source of truth (parent)
**Cons:** synchronous bottleneck — every cross-agent action waits for parent; doesn't help in parallel waves where parent just dispatched and is waiting

### Shape D — lockfile mutex

`.chunks/SHARED/locks/<resource>.lock` files via POSIX `O_EXCL`. Filesystem-mediated mutex.

**Pros:** strict serialization on contended resources
**Cons:** easy to deadlock; agents need to release locks even on crash; over-engineered for our scale (most resources don't contend)

### Shape E — CRDT (eventually-consistent shared state)

Each agent maintains a local view; periodic merge using a CRDT (G-Set, OR-Set, LWW Register). Mathematically conflict-free.

**Pros:** theoretically sound for concurrent writes
**Cons:** massive complexity; needs a state-merging library; agents need CRDT primitives — way out of scope

## My recommendation — A + B hybrid

Ship **Shape A (heartbeat) + Shape B (subset: discovery / help / response / failure)**.

Skip from B:
- `status` — subsumed by heartbeat
- `ownership_query/grant` — pre-flight conflict check (audit #4) catches collisions; runtime collision is a contract violation that SHOULD fail loud, not negotiate
- `dep_ready` — subsumed by heartbeat (`event: completed` reads as dep-ready)

Skip C, D, E entirely.

### Why A+B together

- **A alone** gives observability but no agent-to-agent action (one-way broadcast)
- **B alone** without heartbeat means agents poll one giant message stream looking for status — wasteful
- **A+B together**: heartbeats are the high-volume passive stream; messages are the low-volume active stream. Each agent reads both per iter.

### On-disk shape

```
docs/superpowers/plans/<plan-name>/
├── plan.yaml
├── chunks/
├── merge.yaml
├── ledger/
│   ├── MASTER.jsonl
│   └── SHARED/                      ← NEW: coordination pool
│       ├── heartbeats.jsonl         ← Shape A
│       └── messages.jsonl           ← Shape B
└── CHECKLIST.md
```

The pool lives under `ledger/SHARED/` (siblings of MASTER.jsonl). Survives across waves and across merge boundaries (cleaned in final merge alongside `.chunks/`).

### Schema sketches

```json
// heartbeat.schema.json
{
  "type": "object",
  "required": ["ts", "chunk_id", "event"],
  "properties": {
    "ts":         {"type": "string", "format": "date-time"},
    "chunk_id":   {"type": "string"},
    "event":      {"enum": ["started", "iter_done", "completed", "failed", "handoff", "blocked"]},
    "item_id":    {"type": "string"},
    "progress":   {"type": "number", "minimum": 0.0, "maximum": 1.0},
    "tokens_used":{"type": "integer"},
    "commit_sha": {"type": "string"},
    "notes":      {"type": "string"}
  }
}
```

```json
// message.schema.json
{
  "type": "object",
  "required": ["ts", "from", "type", "payload"],
  "properties": {
    "ts":             {"type": "string", "format": "date-time"},
    "from":           {"type": "string", "description": "chunk_id"},
    "type":           {"enum": ["discovery", "help", "response", "failure"]},
    "to":             {"type": "string", "description": "chunk_id, or empty for broadcast"},
    "in_reply_to_ts": {"type": "string", "format": "date-time"},
    "blocking":       {"type": "boolean", "default": false},
    "payload":        {"type": "object"}
  }
}
```

### Agent contract additions

Each chunk's dispatch prompt gains:

```
COORDINATION POOL (read every iter; write on event):
- ledger/SHARED/heartbeats.jsonl — append your status: started / iter_done / completed / failed / handoff / blocked
- ledger/SHARED/messages.jsonl   — read for sibling discoveries + help requests; post your own when:
  * `discovery` — you built a reusable helper sibling chunks might want
  * `help`      — blocking question; wait up to 2 min for sibling response
  * `failure`   — committing-to-fail; lets parent decide retry policy

NEVER write to other chunks' fragment dirs (.chunks/<other-id>/). The pool is the ONLY shared write surface.
```

### New merge action

```yaml
# merge.yaml additions
stages:
  interwave:
    actions:
      - consolidate_perms
      - append_progress
      - render_master_ledger
      - render_checklist
      - prune_pool_acked    # NEW — remove pool messages whose reply landed
  final:
    actions:
      - ...
      - archive_pool        # NEW — copy ledger/SHARED/* to ledger/SHARED.archive/ before cleanup
      - cleanup_fragments
```

## New gaps this introduces

| New gap | Mitigation |
|---|---|
| **Pool durability** — fs corruption loses coordination state | Append-only writes; backup to `ledger/SHARED.archive/` before each merge stage |
| **Message volume** — 20 agents × N msgs/iter = lots of reads | Pool read cap: each agent reads at most last 200 messages per iter |
| **Stale `help`** — sibling never responds; chunk-3 hangs | Built-in 2-min timeout; on timeout, chunk-3 emits `failure` + proceeds with best-guess |
| **Read-after-write consistency** — agent posts then immediately reads, doesn't see own write | Use `os.fsync` after `atomic_append_line`; POSIX guarantees ordering after fsync |
| **Pool grows unboundedly** — 1000+ heartbeats per plan | Truncation at wave boundary: `prune_pool_acked` action archives rows for completed chunks |
| **Order of writes is timestamp-only** — clock skew across worktrees | All writes use UTC + monotonic counter suffix to break ties |
| **Schema drift** — agent posts malformed message | Validate-on-write via the agent prompt; reject-on-read for malformed |

## Trade-off table

| Concern | Without pool | With A+B pool |
|---|---|---|
| Failure visibility | Operator manually inspects .chunks/N/ledger.jsonl × 20 | Single `tail -f ledger/SHARED/heartbeats.jsonl` |
| Dep readiness | Implicit via wave order | Explicit via `event: completed` heartbeats |
| Cross-agent learning | None — each agent reinvents | Discoveries propagated via messages |
| Help loops | Block on parent (waste) | Sibling can answer faster |
| Token overhead | 0 | ~200k extra across 20-chunk plan (~10% of total) |
| Complexity | None | +2 schemas + 1 merge action + agent contract |
| Race conditions | 0 (no shared writes) | 0 (append-only, single-writer-per-row) |
| Operator dashboard | Static (rendered at merge) | Live (read pool any time) |

**Verdict:** the ~10% token overhead is well worth the failure-visibility + cross-agent learning wins. The append-only design preserves the "no race conditions" guarantee.

## Phased rollout (incremental — KISS)

### Phase A1 — heartbeat only
- Add `heartbeats.jsonl` + schema
- Each agent posts: `started` / `iter_done` / `completed` / `failed`
- Parent reads for auto-handoff trigger (tokens_used > 30k) + failure detection
- ~80 LOC + 1 schema
- Solves: #6 (auto-handoff trigger), #11 (live monitoring), partial #7 (parentage via `event: handoff` rows)

### Phase B1 — discovery messages
- Add `messages.jsonl` + schema; type=`discovery` only
- Agents post when they ship a reusable helper
- Siblings read every iter and can `import`/reference shipped helpers
- ~60 LOC + 1 schema
- Solves: NEW cross-agent learning (reduces duplicate work)

### Phase B2 — help/response loop
- Extend messages.jsonl with `type=help` + `type=response`
- Agents post blocking help requests; siblings or parent respond
- 2-min timeout default
- ~100 LOC + extended schema
- Solves: blocking-decision cases without parent escalation

### Phase B3 — failure broadcast
- Add `type=failure` to messages.jsonl
- Failed agent posts WHY before exiting
- Parent reads on wave-completion to apply `failure_policy`
- ~40 LOC (mostly the post-and-exit ritual)
- Solves: W5 (inter-wave failure recovery)

**Total runtime addition: ~280 LOC + 2 schemas + 1 new merge action.**

Can be built incrementally — each phase is independently useful and additive (no breaking changes to prior phases). Phase A1 alone provides 60% of the value.

## What this DOESN'T do (honesty)

- **Doesn't replace pre-flight checks** — runtime ownership collisions should still fail-loud, not negotiate. Pool augments, doesn't substitute, the conflict detector.
- **Doesn't enable speculative work** — agents shouldn't start chunk-12 just because chunk-3 might finish soon. Dep ordering still mediated by wave structure.
- **Doesn't make MERGE handlers unnecessary** — the pool is observability + coordination, not data consolidation. Fragments still need handlers to land in canonical files.
- **Doesn't help cross-repo chunks** — chunk-15 in semantic-search can't see kaizen-md's pool (different worktree tree). Cross-repo coordination remains parent-mediated.

## Alternative ideas considered, not pursued

- **Real-time WebSocket pool** — overkill; filesystem JSONL is fine for human-scale agent counts
- **gRPC service for agent comms** — would require running a server per plan; complexity not justified
- **Slack-style channels with subscriptions** — agents would need to declare interests; declarative complexity vs reading the whole stream is a wash at our scale
- **Database-backed pool (SQLite)** — would handle dedupe + query, but filesystem JSONL + jq is simpler for human inspection

## Open questions for the user

1. **Should help messages have a sibling-quorum response model** (need ≥2 siblings agreeing) or first-response-wins? KISS says first-wins.
2. **Should the pool persist across plan runs** (for retrospectives / learning) or get archived/cleaned per-plan? Recommendation: archive per-plan to `ledger/SHARED.archive/<plan-id>/`.
3. **Should agents be allowed to read the pool BEFORE their wave starts** (so a wave-2 chunk can see wave-1's discoveries)? Recommendation: yes — pool grows across waves, only reset between plans.
4. **Should `failure` messages auto-trigger parent retry** or always wait for operator? Recommendation: depends on `failure_policy` field — `partial` proceeds without retry; `abort` halts; `defer` queues a retry chunk.
5. **Live-stream the pool to operator** (e.g. statusline shows last 5 heartbeats)? Cheap addition once Phase A1 lands.

## Recommended next step

Build **Phase A1 (heartbeat) ONLY** first. Validate that operators actually want to see the live stream + that auto-handoff fires correctly. Then add Phase B1-3 as DRY/value triggers fire (≥2 plans where the lack of cross-agent communication blocked progress).

This stays YAGNI-aligned while opening the door to the user's instinct (agents communicating to solve issues) in a way that doesn't break the parallel-safety guarantees the kit's whole design rests on.
