# BACKLOG.md template

Canonical shape — copy verbatim, then fill in. Path is set by
`backlog_path` in `.kaizen.toml`; common locations:

- `.workflow/BACKLOG.md` — projects that have a workflow-state dir
  (alongside `progress.md`, `state.json`, snapshots, audits)
- `BACKLOG.md` — greenfield projects with no workflow-state convention
- `docs/workflow/BACKLOG.md` — projects that nest workflow state under
  `docs/`

```markdown
# Backlog

> Single rolling summary. Tier-up to plans/<date>-<slug>.md only when
> blast radius forces it. See ~/.claude/skills/kaizen.

## In flight

- [ ] <verb-first description of the current focus> — probe: `<grep|trace|sem cmd>` — verify: `<cmd>`

## Next up

- [ ] <item 1> — probe: `<cmd>` — verify: `<cmd>`
- [ ] <item 2> — probe: `<cmd>` — verify: `<cmd>`
- [ ] <item 3> — probe: `<cmd>` — verify: `<cmd>`

## Done (this week)

- [x] <item> — committed: <short-sha> — <date>

## Parked / deferred

- [ ] <item> — parked: <reason> — probe output: `<evidence>`

## Decisions

- <date> | <one-line decision> | <why>
```

## Worked example — shodan's 7 dual-stream handoff limitations as seed items

```markdown
# Backlog

## In flight

_(nothing currently)_

## Next up

- [ ] Buffer bootstrap tracing events until first subscriber attaches (handoff §lim 1) —
  probe: `git grep -n "tracing::info" crates/cli/src/dispatcher.rs` —
  verify: `cargo test -p shodan-runtime observability::bus`
- [ ] Wire find_references via LSP-backed analyzer (handoff §lim 4) —
  probe: `grep -rn "find_references" crates/static/src/tools/` —
  verify: `SHODAN_THINK_PROBES=find_symbol,find_references cargo run --bin shodan -- repl --obs-pane`
- [ ] Separate-capacity tier for low- vs high-rate bus streams (handoff §lim 5) —
  probe: `git grep -n "broadcast::channel" crates/runtime/src/observability/bus.rs` —
  verify: `cargo test -p shodan-runtime observability::bus::capacity`
- [ ] Per-tool arg builders in ThinkConsumer (handoff §lim 3) —
  probe: `git grep -n "args_for_tool" crates/nodes/src/observability/think_consumer.rs` —
  verify: `cargo test -p shodan-nodes observability::think_consumer::per_tool_args`

## Parked / deferred

- [ ] ratatui split-pane TUI (handoff §lim 2) — parked: prototype scope met by stderr stripe — probe output: stderr renderer is feature-complete; TUI is 300-500 LOC of UX polish, not architecture
- [ ] Symbol-extractor NLP false-positive filter (handoff §lim 6) — parked: signal-to-noise tolerable with cooldown — probe output: 1 false-positive per ~12 reasoning tokens, throttle absorbs
- [ ] Visibility::Promotable auto-rules (handoff §lim 7) — parked: needs live-session data on probe noise vs signal — probe output: 0 sessions of operator-pane data so far

## Decisions

- 2026-05-11 | Default ThinkConsumer probes = [find_symbol] only | Silenced find_references noise (iter 13); promoted to env-var override
- 2026-05-11 | Bus capacity 4096 fixed for now | Lagged(n) warnings logged but not catastrophic; capacity-tier work is a real lim
- 2026-05-11 | --obs-pane off by default | Clean baseline UX (iter 8); operator opts in
```

## Item-field discipline

**Verb-first description** (≤80 chars):
- ✗ `find_references work`
- ✗ `lim 4 from handoff`
- ✓ `Wire find_references via LSP-backed analyzer (handoff §lim 4)`

**Probe field** (the trace/sem/grep that proved the item stays micro):
- ✗ omitted ("just trust me")
- ✗ "look at the codebase"
- ✓ ```grep -rn "find_references" crates/static/src/tools/```
- ✓ ```cargo tree -i -p shodan-static```
- ✓ ```ast-grep --pattern 'impl SomeTrait for $X' --lang rust```

**Verify field** (the command that proves the work is done):
- ✗ "tests pass"
- ✗ "manual smoke check"
- ✓ ```cargo test -p shodan-runtime observability::bus```
- ✓ ```SHODAN_THINK_PROBES=find_symbol,find_references cargo run --bin shodan -- repl --obs-pane```

## Lifecycle in commits

```bash
# Item in ## Next up. You probe-confirm it stays micro:
$ grep -rn "find_references" crates/static/src/tools/ | wc -l
2
# 2 files. Micro. Move to In flight in the same commit as your first edit.

$ git add BACKLOG.md crates/static/src/tools/symbol.rs
$ git diff --cached BACKLOG.md
# Should show:
#   ## In flight
#  +- [ ] Wire find_references via LSP-backed analyzer ...
#   ## Next up
#  -- [ ] Wire find_references via LSP-backed analyzer ...

# After landing the work, tick + roll off:
$ git add BACKLOG.md crates/...
$ git diff --cached BACKLOG.md
#   ## In flight
#  -- [ ] Wire find_references ...
#   ## Done (this week)
#  +- [x] Wire find_references ... — committed: HEAD — 2026-05-11
```

## Weekly roll-off

Once a week (or when `## Done` exceeds 15 entries), prune:

```bash
# Move closed items into archive
mv BACKLOG.md /tmp/bk
# Edit: cut ## Done items into plans/archive/YYYY-MM/backlog-YYYY-WW.md
# OR: just delete if architecture log already captured structural rows
```

The architecture log (`.workflow/progress.md`) is the durable record
for structural moves; `BACKLOG.md ## Done` is a session-spanning
working memory, not a permanent log.
