# Custom Observer — Design Spec

**Status:** spec only (this commit) — runtime ships next session(s).
**Repos:** spec lives in kaizen-md; runtime lives in clever-lama-mcp
(dual-home pattern, mirrors parallel-branches).

---

## Problem statement

The 6-layer observability model documented in kaizen-md's CLAUDE.md
(Live UI / CC transcript / kaizen-trace / domain logs / per-repo state /
plugin+global state) gives us READ paths for each layer but no
unified WATCH path that can:

1. See every tool call (main agent + every subagent + every Bash invocation + every MCP tool call + every slash command dispatch) in real time.
2. Evaluate that tool call against **rules** loaded from disk (specs / conditions / guards).
3. Surface verdicts to multiple consumers (statusline, MCP query, hook stream, CLI tail).
4. **Stay correct when the cache or the agent/MCP API drifts mid-session** — the canonical failure mode is "kaizen-implementer's tools list changed on disk but the runtime kept using the cached pinned version" (see commit `9b29d3d` for the live bug we just hit).

## Non-goals

- Replace the kaizen pre-commit gate (that's commit-time; observer is tool-call-time).
- Replace kaizen-trace (that's the structured event index; observer reuses it).
- Become a permission system (observer can flag but doesn't deny — denial is the existing PreToolUse Bash gate's job).

---

## Architecture — 5 components, one event bus

```
┌──────────────────────────────────────────────────────────────────┐
│  parent session + subagents + slash commands                      │
└─────────────────────────────────┬────────────────────────────────┘
                                  │ PreToolUse / PostToolUse /
                                  │ UserPromptSubmit / Stop /
                                  │ SubagentStop hook fires
                                  ▼
              ┌─────────────────────────────────────┐
              │  C1: HOOK CAPTURE                   │
              │  hooks/claude/observer-*.sh         │
              │  - reads hook stdin                 │
              │  - calls C2 with normalized event   │
              │  - always exits 0 (never blocks)    │
              └─────────────┬───────────────────────┘
                            ▼
              ┌─────────────────────────────────────┐
              │  C2: EVENT INGEST                   │
              │  src/observer/ingest.py             │
              │  - validates against schemas/       │
              │    event.schema.json                │
              │  - appends to events.jsonl          │
              │  - triggers C3 rule eval inline     │
              │  - graceful-degrades on schema      │
              │    drift (logs anomaly, still       │
              │    writes raw event)                │
              └────┬────────────────────────┬───────┘
                   ▼                        ▼
       ┌─────────────────────┐  ┌────────────────────────┐
       │  C3: RULE ENGINE    │  │  C5: EVENT SINK        │
       │  src/observer/      │  │  ~/.claude/.kaizen/    │
       │  rules.py           │  │  observer/events.jsonl │
       │  - reloads          │  │  - append-only         │
       │    rules.yaml from  │  │  - rotated by size     │
       │    disk PER eval    │  │  - source of truth     │
       │  - first-match      │  │    for everything else │
       │  - emits verdict    │  └────────────┬───────────┘
       │    event back to C5 │               │
       └─────────────────────┘               ▼
                                ┌────────────────────────┐
                                │  C4: QUERY SURFACE     │
                                │  - MCP: kaizen-observe │
                                │  - CLI: kaizen-observe │
                                │  - statusline fragment │
                                │  - all READ from C5    │
                                │    on demand, NO cache │
                                └────────────────────────┘
```

**Key invariant — no in-memory caching of mutable state:**

- C1 reads hook stdin every fire — no batching.
- C2 re-loads `event.schema.json` every ingest (cheap; ~1ms).
- C3 re-loads `rules.yaml` every eval (cheap; <5ms for ~50 rules).
- C4 reads `events.jsonl` per query (sequential scan, indexed by
  ts/sid in a sidecar SQLite if scan time exceeds 50ms).

This is what makes the observer **cache/API-drift resilient**: it
never trusts pinned in-memory state. If `rules.yaml` changes mid-
session, the next tool call uses the new rules. If `event.schema.json`
adds a field, the next event includes it (or graceful-degrades).

---

## Event schema (C2 / C5)

`~/.claude/.kaizen/observer/schemas/event.schema.json`:

```jsonc
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["ts", "event_kind", "source", "sid"],
  "properties": {
    "ts":         { "type": "string", "format": "date-time" },
    "event_kind": { "enum": [
      "pre_tool_use", "post_tool_use", "user_prompt", "stop",
      "subagent_dispatch", "subagent_stop",
      "slash_command", "mcp_tool_call",
      "rule_verdict"
    ]},
    "source":     { "enum": ["parent", "subagent", "slash", "mcp", "hook"]},
    "sid":        { "type": "string" },
    "tool":       { "type": "string" },
    "subagent_type": { "type": "string" },
    "command":    { "type": "string" },
    "mcp_server": { "type": "string" },
    "params":     {},
    "result_summary": { "type": "string" },
    "ms":         { "type": "integer" },
    "rule_id":    { "type": "string" },
    "verdict":    { "enum": ["allow", "warn", "deny", "info"] },
    "rule_reason": { "type": "string" },
    "drift_anomaly": { "type": "string" }
  }
}
```

`drift_anomaly` is the escape hatch: when an event doesn't match the
schema (e.g. an MCP tool added a new payload field), C2 still writes
the event but marks `drift_anomaly: "<field-name>: <observed-shape>"`.
C3 sees the anomaly + can fire a meta-rule ("warn on schema drift").

---

## Rule schema (C3)

`~/.claude/.kaizen/observer/rules.yaml`:

```yaml
version: 1
rules:
  - id: no-subagent-bash-destructive
    description: Subagents must never invoke destructive git/fs ops
    when:
      event_kind: pre_tool_use
      source: subagent
      tool: Bash
    match_params:
      command_regex: '\b(git\s+(push|reset|checkout|merge|rebase|clean|branch\s+-D|remote)|rm\s+-rf|rmdir)'
    verdict: warn
    reason: "Subagent attempted destructive op — kaizen-implementer's disallowedTools should have blocked, investigate"

  - id: master-mcp-tool-call-density
    description: Flag if main agent calls >20 MCP tools in <60s
    when:
      event_kind: mcp_tool_call
      source: parent
    aggregate:
      window_seconds: 60
      count_gt: 20
    verdict: warn
    reason: "Possible MCP loop / unintended retry storm"

  - id: command-after-error
    description: Slash command dispatched immediately after a tool error
    when:
      event_kind: slash_command
    requires_prior:
      event_kind: post_tool_use
      result_summary_regex: 'error|failed|exception'
      within_seconds: 5
    verdict: info
    reason: "User likely recovering from error — log for pattern mining"

  - id: cache-drift-detect
    description: Subagent dispatched with stale cached tools list
    when:
      event_kind: subagent_dispatch
    match_meta:
      cached_tools_hash_mismatch: true
    verdict: warn
    reason: "Subagent's pinned tool list differs from on-disk agent definition — session restart required for fix to take effect (see fix 9b29d3d)"
```

Each rule has:
- `id` — kebab-case unique
- `when` — event-kind + source filters (AND)
- `match_params` — regex/equality against the event's `params` blob
- `aggregate` — for rate/density rules (sliding window)
- `requires_prior` — temporal cross-event correlation
- `match_meta` — kaizen-introspected metadata (cached_tools_hash, etc.)
- `verdict` — allow / warn / deny / info (deny is reserved; observer
  doesn't block today — emits the verdict for downstream gates to act on)
- `reason` — human-readable rationale; surfaced in CLI + statusline

**Rule-evaluation contract:** every rule eval re-reads the YAML from
disk (no in-process cache). For 50 rules × ~10 tool calls/min, that's
~500 file-reads/min — well under 1% CPU on a modern machine. Worth the
drift-resilience.

---

## Component matrix — files + responsibilities

| Component | Files | Repo |
|---|---|---|
| **C1** Hook capture | `plugins/kaizen/hooks/claude/observer-{pretool,posttool,prompt,stop,subagent}.sh` | kaizen-md (hooks live there per CC plugin contract) |
| **C2** Event ingest | `src/observer/ingest.py` (~80 LOC) | clever-lama-mcp |
| **C3** Rule engine | `src/observer/rules.py` (~120 LOC) | clever-lama-mcp |
| **C4a** MCP query | `src/observer/mcp_server.py` (~60 LOC, registered as `kaizen-observe` tool) | clever-lama-mcp |
| **C4b** CLI | `src/observer/cli.py` (~80 LOC; subcommands: tail, stats, query, rules check) | clever-lama-mcp |
| **C4c** Statusline frag | `plugins/kaizen/skills/workflow/scripts/observer_statusline.py` (~30 LOC) | kaizen-md |
| **C5** Event sink | `~/.claude/.kaizen/observer/events.jsonl` (+ rotated `.gz` siblings) | runtime; both repos read |
| Schemas | `~/.claude/.kaizen/observer/schemas/{event,rule}.schema.json` | runtime; seeded from kaizen-md/docs/superpowers/templates/observer/ |
| Rules | `~/.claude/.kaizen/observer/rules.yaml` | runtime; seeded with a starter from kaizen-md/docs/superpowers/templates/observer/ |
| Spec doc | `docs/superpowers/specs/2026-05-18-custom-observer-design.md` (this file) | kaizen-md |
| Templates | `docs/superpowers/templates/observer/{event.schema.json, rule.schema.json, rules.yaml, README.md}` | kaizen-md |

## Build phases

**Phase 0 — spec + templates (this commit).** No runtime; just this
doc + the templates directory.

**Phase 1 — minimum viable runtime (1-2 sessions).**
- C2 ingest.py — read stdin, validate, append to events.jsonl. RED-first.
- C1 observer-pretool.sh + observer-posttool.sh — call C2.
- C4a kaizen-observe MCP tool with one verb: `recent N`.
- Smoke test: dispatch a tool, see the event in events.jsonl.

**Phase 2 — rule engine + verdict surface (1 session).**
- C3 rules.py — load YAML, eval against event, emit rule_verdict event.
- C4b CLI — `kaizen-observe tail`, `stats`, `rules check`.
- C4c statusline fragment.
- 3 seed rules: cache-drift-detect, no-subagent-bash-destructive,
  master-mcp-tool-call-density.

**Phase 3 — drift + correlation (1 session).**
- C2 schema-drift detection (graceful-degrade).
- C3 aggregate + requires_prior support (temporal rules).
- C4a MCP tool gains: `query --rule <id>`, `verdicts --since 1h`.

**Phase 4 — port runtime back to kaizen-md (optional, after benchmarks).**
- Same code, different repo. Schemas + docs stay SSOT in kaizen-md.

---

## Cache/API drift — how the observer survives it

This is the **#1 design constraint** per the user's ask.

| Drift source | Failure mode | Observer mitigation |
|---|---|---|
| Agent definition `tools` list changes on disk but parent's cached version is pinned | Subagent dispatched with stale tool surface (THE BUG we just hit) | `cache-drift-detect` rule compares the cached_tools_hash (passed via the dispatch event) against the live file hash; warns if mismatch |
| MCP server adds a new tool or new tool-param schema | Existing event-schema rejects the new shape | C2's `drift_anomaly` field — write the event, mark the anomaly, let C3 fire `warn-on-schema-drift` |
| Hook script renamed / deleted | Events stop arriving for that event_kind | `expected-hooks-firing` rule: count fires per event_kind per hour; warn if delta vs prior 24h > 50% |
| Kaizen plugin version bump | Rule schema changes (new fields) | Rules loaded with backward-compat: unknown fields ignored with `info` log line (not warn) |
| Settings.json permissions change | Subagent loses Bash mid-session | post_tool_use events with `Bash` tool stop appearing for that subagent_type; same `expected-hooks-firing` rule catches it |

**The unifying principle:** the observer treats every source file as
"the truth at this instant" — never caches pinned versions, never
trusts the runtime's view over the filesystem. This is exactly the
opposite of what burned us with kaizen-implementer.

---

## Iron laws (observer-specific, in addition to kaizen plugin's)

1. **Append-only event sink.** Never edit events.jsonl in-place. Rotation moves the file out, never truncates.
2. **Rules re-read per evaluation.** No `@lru_cache` on rule loaders.
3. **Schemas re-read per ingest.** Same.
4. **Hooks always exit 0.** Observer must never block the host session.
5. **Drift anomalies are events, not exceptions.** Every drift becomes a rule-eligible event.
6. **No PII in events by default.** Tool params are summarized (first 200 chars) unless explicitly opted in via `KAIZEN_OBSERVER_FULL_PARAMS=1`.

---

## Open questions for next session

1. Should the observer's MCP tool be a separate `kaizen-observe` registration or a `mode` of clever-agent? (Lean: separate — clever-agent is for reasoning modes; observer is meta-introspection.)
2. Rotation policy for events.jsonl — by size (10MB?), by age (7 days?), or both?
3. Statusline integration — overwrite the existing kaizen-statusline output or chain into it?
4. Should the CLI ship a `--watch` mode (tails events live, like `tail -f`)? (Lean: yes — useful for live debugging.)

---

## Connection to this session's bug

The cache-drift-detect rule's reason field references commit `9b29d3d`
directly. That bug — "agent's `tools:` list edited on disk but
runtime kept pinned cached version" — is the canonical case the
observer must catch. If we'd had this observer running today, we'd
have seen:

```
[2026-05-18T20:xx:xx] subagent_dispatch source=parent
  subagent_type=kaizen:kaizen-implementer
  cached_tools_hash=<old-sha>
  disk_tools_hash=<new-sha>
  drift_anomaly: "cache_hash_mismatch"
  rule_verdict: cache-drift-detect (warn)
  reason: "Subagent's pinned tool list differs from on-disk agent definition — session restart required"
```

That's the eyeball-on-the-bug we built this whole observer for.
