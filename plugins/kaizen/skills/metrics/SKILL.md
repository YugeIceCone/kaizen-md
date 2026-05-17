---
name: metrics
description: Rollup + never-used catalog + skip-detection over the kaizen trace log. Use to self-audit a session, identify dead features, or surface skill-loads that were skipped. Triggers on "what skills did I use", "metrics for this session", "kaizen never used", "skip detection", "which mcp tools did I call", "trace rollup", "lifetime usage", "skill usage report", "what's dead in kaizen", "did I forget to load a skill", "audit feature adoption". Pair with brain_audit for full end-of-session reflection.
version: 1.0.0
---

# Metrics — rollup + never-used + skip-detection

## ⚠ Iron Law — read in full

The metrics surface is the self-correction signal. Skipping the
analysis means the same mistake repeats next session.

## What this skill does

Surfaces rollup reports + diffs + a smoke check:

| Report | What it answers |
|---|---|
| `session` | "What did I use in THIS session?" |
| `lifetime` | "What's hot vs cold across all sessions?" |
| `never-used` | "What features have I NEVER used?" — the dead-code-equivalent for capabilities |
| `top` | "Top N most-used skills / tools / MCP servers" |
| `skips` | "Which skills did I touch the trigger files for but never load?" — the discipline-violation report |
| `graveyard` | "What's cold enough to archive?" — never-used AND the trace is old enough to judge |
| `smoke` | "Does every MCP server still import?" — catches a broken server before a user hits it |

## Quick reference

```bash
# Current session rollup
kaizen-metrics session

# Lifetime, last 7 days
kaizen-metrics lifetime --since 7d

# Never-used artifacts of a kind
kaizen-metrics never-used --kind skill
kaizen-metrics never-used --kind mcp
kaizen-metrics never-used --kind tool
kaizen-metrics never-used --kind bin

# Most-used artifacts
kaizen-metrics top --kind skill --n 10
kaizen-metrics top --kind tool

# Skip-detection — did I forget to load a skill the touched files implied?
kaizen-metrics skips

# Graveyard — cold-artifact candidates (only flags once the trace is
# old enough to judge — guards against false-dead on a young trace)
kaizen-metrics graveyard --kind skill --stale-days 14
kaizen-metrics graveyard --kind mcp

# MCP smoke-test — import every *_mcp.py, verify FastMCP instance
kaizen-metrics smoke --kind mcp

# JSON output for machine readers
kaizen-metrics lifetime --json
kaizen-metrics skips --json
```

## graveyard vs never-used — the recency guard

`never-used` is a raw set difference: available minus invoked. On a
YOUNG trace (the universal trace hook landed recently) almost
everything shows as never-used — that's a measurement artifact, not
dead code.

`graveyard` adds the recency guard: it computes `trace_age_days(kind)`
— how long the trace has actually been *watching* that artifact kind
— and refuses to flag candidates until that age clears `--stale-days`.
A `ready: false` result with a caveat means "trace too young, can't
judge yet." Only `ready: true` results carry actionable candidates,
and even then the caveat says verify each is genuinely dead (not just
rare / indirectly-triggered) before archiving. graveyard NEVER
archives — archiving is user-led (pre-deletion belief).

## smoke — MCP server health

`smoke --kind mcp` imports every `*_mcp.py` module and checks for a
module-level `mcp` FastMCP instance. A server that `sys.exit()`s on a
missing opt-in dep (e.g. `browser_mcp.py` without playwright) is
recorded as a `failed` entry — not a crash of the smoke run. Exit
code 2 when any server fails, so it's CI-gateable.

## What gets tracked (and what doesn't)

Trace coverage depends on the M1 universal-trace hook. As of v1.34+:

| Tool kind | Tracked? | Event names |
|---|---|---|
| Bash | ✓ pre-existing | `PreToolUse-bash` / `PostToolUse-bash` |
| Skill | ✓ (M1+) | `PreToolUse-Skill` with `data.ident=<skill>` |
| Edit / Write / Read / NotebookEdit | ✓ (M1+) | `PreToolUse-Edit` etc with `data.ident=<path>` |
| Glob / Grep | ✓ (M1+) | with `data.ident=<pattern>` |
| Agent | ✓ (M1+) | with `data.ident=<subagent_type>` |
| TaskCreate / TaskUpdate | ✓ (M1+) | |
| WebFetch / WebSearch | ✓ (M1+) | |
| mcp__* | ✓ (M1+) | `PreToolUse-mcp__plugin_kaizen_X__Y` |
| Other tools | ✓ (M1+) | bare tool name |

Events older than the M1 install date carry no skill / non-Bash
data. The never-used and skill rollups reflect data from M1 onward.

## Skip-detection — the rule catalog

`metrics.py::SKIP_RULES` declares which skills MUST be loaded when
certain file patterns are touched. Initial catalog (extend in code
when new mandatory-skill rules land):

| Skill | Triggers (touched-file patterns) | Rationale |
|---|---|---|
| `plugin-development` | `plugins/kaizen/{skills,commands,hooks,bin}/`, `plugin.json`, `hooks.json` | `iron-laws.yaml::skill-cant-be-skipped` |
| `brain` | `skills/brain/`, `brain*.py`, `~/.claude/.kaizen/brain/` | Touching brain files without the skill |
| `workflow` | `workflow/scripts/workflow*`, `commands/workflow.md` | Touching workflow scripts |

When SessionEnd fires + skip-detection finds violations, the
`metrics-session-end.sh` hook writes a draft Inbox entry to
`<brain>/Inbox/skip-detection-<date>-<rand>.md`. The user sees it
on the next session start (brain audit drains the Inbox).

## Trace log location + retention

Path resolution: `KAIZEN_TRACE_DIR` env > `~/.claude/.kaizen/trace/`.
The log auto-rotates at `KAIZEN_TRACE_MAX_MB` (default 100) into
gzipped files; default retention 7 days
(`KAIZEN_TRACE_RETENTION_DAYS`).

Metrics reads only the current `events.jsonl` — rotated files are
NOT scanned by default (a future enhancement; for now the rollup
is bounded to the live log).

## Disable

`KAIZEN_METRICS_DISABLE=1` short-circuits BOTH the universal trace
hooks (pretooluse-trace / posttooluse-trace) AND the SessionEnd
skip-detection hook. Useful when you genuinely don't want any
metrics overhead during a perf-sensitive run.

## MCP tools

After `/reload-plugins`, the agent can call:

  - `mcp__plugin_kaizen_metrics__metrics_session(sid)`
  - `mcp__plugin_kaizen_metrics__metrics_lifetime(since)`
  - `mcp__plugin_kaizen_metrics__metrics_never_used(kind)`
  - `mcp__plugin_kaizen_metrics__metrics_top(kind, n)`
  - `mcp__plugin_kaizen_metrics__metrics_skips(sid)`
  - `mcp__plugin_kaizen_metrics__metrics_path()`

## When to invoke

- **End of a long session** — `kaizen-metrics session` shows what
  you actually used; `kaizen-metrics skips` flags any
  mandatory-skill misses.
- **Periodic adoption audit** — `kaizen-metrics never-used --kind skill`
  (and `--kind mcp`) shows what's bundled but cold. Decide whether
  the feature has a real use case or should be retired.
- **Self-correction reflection** — after the brain-audit Inbox
  surfaces a skip-detection draft, decide whether the skip was
  legitimate (then archive the draft) or a mistake (capture a
  belief Note + adjust workflow).

## How metrics relates to existing surfaces

| Surface | Purpose |
|---|---|
| `kaizen:trace` | Append-only event log (the source) |
| `kaizen:trace-search` | Semantic search over events |
| `kaizen:observe` | Schema-driven snapshot system (deeper diagnostics) |
| `kaizen:metrics` (THIS skill) | Roll-up + never-used + skip-detection |
| `brain_audit` | User-quote candidate extraction (different angle) |

`metrics` is the cheapest, fastest summary. For deep query / search,
prefer trace-search; for snapshots, use observe.
