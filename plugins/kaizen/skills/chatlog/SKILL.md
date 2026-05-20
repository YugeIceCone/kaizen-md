---
name: chatlog
description: Trigger-rule-driven CC transcript slicer. Reads a Claude Code session jsonl, matches each event against rules (event_type / user_keyword / assistant_tool_use), captures a configurable window around each match, and writes one .jsonl per rule. Use when you want to extract just the relevant slices of a long transcript — "find every gate failure in this session", "extract every handoff call + the next assistant turn", "carve out all the user messages mentioning ralph". Triggers on "chatlog slice", "kaizen-chatlog", "slice this transcript", "extract gate failures from session", "transcript slicer", "chat log triggers", "trace user keyword in session".
metadata:
  version: "0.1.0"
---

# Chatlog — CC transcript slicer

The Claude Code session jsonl at
`~/.claude/projects/<slug>/<sid>.jsonl` is a verbose append-only log of
every user turn, assistant turn, tool use, tool result, and hook event.
For a 7K-line / 11 MB session, reading the whole thing to find "every
time the gate failed" wastes a lot of tokens. **Chatlog slices the
transcript by trigger-rule** so consumers read just the relevant
windows.

This is the MVP. Scope:

- **3 trigger types** — `event_type` / `user_keyword` /
  `assistant_tool_use`.
- **1 action** — `capture {before: N, after: N}` returns the matched
  event plus N events before + N after.
- **CLI only** — no hook, no MCP, no slash for v1. Future iterations
  can add a Stop hook that auto-applies a default rule set.

## CLI

```bash
kaizen-chatlog slice \
    --transcript ~/.claude/projects/<slug>/<sid>.jsonl \
    --rules <path>/rules.{json,yaml} \
    --out ~/.claude/.kaizen/chatlog/<sid>/

# Machine-readable summary
kaizen-chatlog slice ... --json
```

## Rules file shape

JSON or YAML — top-level `rules:` list. Each entry has `id` (used as
output filename), `trigger`, and `capture`.

```yaml
rules:
  - id: gate_failures
    trigger:
      type: user_keyword
      pattern: "gate.*fail|gate.*block"
    capture:
      before: 1
      after: 5
  - id: handoff_calls
    trigger:
      type: assistant_tool_use
      tool_name: handoff
    capture:
      before: 0
      after: 1
  - id: session_starts
    trigger:
      type: event_type
      event_type: attachment
    capture:
      before: 0
      after: 0
```

## Output

One `<rule_id>.jsonl` per rule under `--out` dir. Each line is **one
slice** (a JSON array of events on one line — easy to `jq '.[]'`).

```bash
# Count slices per rule:
wc -l ~/.claude/.kaizen/chatlog/<sid>/*.jsonl

# Read one slice's events:
head -1 ~/.claude/.kaizen/chatlog/<sid>/gate_failures.jsonl | jq '.[].type'

# Show all matched user-message bodies:
jq -r '.[] | select(.type=="user") | .message.content' \
    ~/.claude/.kaizen/chatlog/<sid>/gate_failures.jsonl
```

## Where it sits in the stack

- **Below trace / dxm**: trace/dxm capture _events as they happen_;
  chatlog _re-reads the transcript after-the-fact_ for arbitrary slices.
  Together they cover live + retroactive observability.
- **Above raw transcript read**: instead of `Read ~/.claude/.../sid.jsonl`
  (7K lines), produce a `gate_failures.jsonl` (5 slices = ~30 events
  = ~100 lines).
- **Sister to kaizen-trace-search**: trace-search does semantic
  retrieval over kaizen-trace events; chatlog does rule-based extraction
  from the CC transcript. Different sinks, different lenses.

## Design contract

- **Programmable** — `match_event` / `extract_slice` / `slice_transcript`
  are pure functions
- **Reproducible** — same `(events, rules)` → same output
- **Consistent** — every rule returns a list (empty = no matches)
- **Deterministic** — no wall-clock, no env reads, no randomness
- **Reusable** — works for any JSONL transcript with `type` + `message`
  fields

## Iron-law adherence

- `bin-wrapper-per-cli` — `bin/kaizen-chatlog` shipped same commit
- `plugin-manifest-permissions` — 2 entries in `plugin.json::permissions.allow`
- `sandbox-tests` — TestChatlogCLI uses `tempfile.TemporaryDirectory`
- `drift-resilient-config-read` — no module-level state

## Layout

```
skills/chatlog/
  SKILL.md
schemas/chatlog/
  schemas/triggers.schema.json
  examples.yaml
scripts/chatlog/
  _chatlog.py       — pure-function core
  chatlog.py        — CLI
bin/kaizen-chatlog  — bin wrapper
tests/test_chatlog.py  — 23 unit + integration tests
```
