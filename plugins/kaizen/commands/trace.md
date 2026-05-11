---
name: trace
description: Unified event log across kaizen hooks, agents, LLM calls, tool invocations, and user actions. JSONL-backed, fast queries, auto-rotation. Subcommands: tail | query | stats | event | clear | path. Use to debug "what fired when", trace agent dispatch, see hook latency distribution, find LLM cost outliers.
---

# kaizen trace

Append-only JSONL event log at `~/.claude/.kaizen-trace/events.jsonl`. Every hook, agent invocation, LLM call, and tool boundary writes a structured event. Fast grep / replay / cost analysis without parsing free-form logs.

!`python3 ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/trace.py ${ARGUMENTS:-tail}`

## Schema

```json
{
  "ts":   "2026-05-12T00:30:00.123Z",   // ISO UTC with ms
  "src":  "hook|agent|llm|tool|user|cc|plugin",
  "evt":  "PreToolUse|invoke|complete|prompt|drift|...",
  "sid":  "<session_id>",
  "tool": "<tool name if applicable>",
  "ms":   <duration_ms or null>,
  "data": { ...arbitrary detail... }
}
```

## Subcommands

| arg | effect |
|---|---|
| (none) or `tail [-n N] [--src S] [--evt E]` | last N events (default 20) |
| `query --since 1h [--src hook --evt PreToolUse --tool Bash --sid X --json --count]` | filter; `--since` accepts `1h`/`30m`/`7d` or ISO ts |
| `stats [--since 1h]` | counts by src/evt/tool, p50/p95/max latency where `ms` set |
| `event --src S --evt E [--tool T --sid S --ms N --data JSON]` | append manual event (also reads stdin JSON merged into `data`) |
| `clear` | delete all trace data (current + rotated) |
| `path` | print log file path |

## What's instrumented

| Source | Events | Producer |
|---|---|---|
| `hook` | session-start, pretooluse-bash-gate, posttooluse-bash-commit, posttooluse-drain-inbox, stop-backlog-reminder, precompact-snapshot, userprompt-inbox | All kaizen hooks |
| `agent` | invoke, complete (with verdict) | kaizen-reviewer / curator / debt-auditor when they call out |
| `plugin` | gate-pass, gate-fail, cache-hit, cache-miss, refresh, daemon-tick, watcher-event | pre-commit.sh, daemon.py, watcher |
| `tool` | (mirror of PreToolUse/PostToolUse) | hooks fire this for each tool boundary |
| `user` | prompt-received | userprompt-inbox.sh |
| `llm` | call, complete, error | (local LLM proxy — opt-in via wrapper) |
| `cc` | session-start, session-end, compact | SessionStart / PreCompact hooks |

## Rotation + retention

| Threshold | Action |
|---|---|
| `events.jsonl` > `KAIZEN_TRACE_MAX_MB` (100) | rotate → `events-YYYYMMDD-HHMMSSZ.jsonl.gz` |
| rotated file age > `KAIZEN_TRACE_RETENTION_DAYS` (7) | auto-prune on next rotation |

Both knobs are env-tunable.

## Example queries

```bash
# Last 20 events (default)
kaizen-trace

# Just hook fires in the last hour
kaizen-trace query --since 1h --src hook

# All Bash tool boundaries
kaizen-trace query --src tool --tool Bash --since 30m

# Latency histogram across all sources
kaizen-trace stats --since 24h

# Cost analysis (when LLM events are wired)
kaizen-trace query --src llm --json --since 7d | jq '.data.tokens'

# Session replay (same sid across multiple agents)
kaizen-trace query --sid <session-uuid> --json
```

## Disable / silence

For production runs where tracing overhead matters: `export KAIZEN_TRACE_DISABLE=1`. Each instrumented site checks this and silently no-ops. Tracing must never break the host — the underlying `append_event()` swallows OSError + JSON errors.
