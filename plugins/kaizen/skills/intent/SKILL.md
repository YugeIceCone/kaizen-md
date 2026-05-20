---
name: intent
description: Declarative intent → action automation on top of Claude Code's hook surface + dxm event stream. Maps user/agent intent (phrase patterns + event_pattern triggers) to suggested or auto-runnable kaizen actions. Triggers on "automate by intent", "intent detection", "phrase trigger", "event pattern automation", "wake word", "kaizen-intent", "auto suggestion", "rule engine".
metadata:
  version: "1.0"
---

# kaizen-intent — automate by intent

## ⚠ Iron Law — read in full

Skip nothing. The three-layer model (trace = past, dxm = now, intent
= should), the trigger taxonomy (phrase vs event_pattern), the
confidence-ranked suggest semantics, and the agent-in-the-loop
contract only hang together as a whole.

## What this skill IS

A rules engine that watches Claude Code's hook + tool surface for
**intent signals** and recommends actions. Declarative rules live in
`schemas/intent/intents.yaml`. Two trigger kinds today:

1. **`phrase`** — regex match against text (typically a
   `UserPromptSubmit` body)
2. **`event_pattern`** — dxm event sequence threshold (e.g.,
   "3+ Bash failures in 60s")

The CLI is read-only by design — it RECOMMENDS, agents EXECUTE. No
auto-running of suggested actions in MVP; the agent decides whether
to act based on `confidence` + context.

## Three-layer kaizen observability stack

  `kaizen-trace`  = what *happened* (lifetime log, queryable index)
  `kaizen-dxm`    = what's *happening now* (real-time event mirror,
                     sub-millisecond capture from CC hooks)
  `kaizen-intent` = what *should* happen (rule-driven automation
                     reading dxm + text)

Each layer is independently useful. Together they form a closed-loop
observability + automation system on top of CC's hook surface.

## CLI

    kaizen-intent list --json
      → envelope.data: {intents[], count}
        Each intent: {id, description, trigger_kinds, confidence}

    kaizen-intent match --text "let's wrap up" --json
    kaizen-intent match --events-json '[...]' --json
    echo "let's wrap up" | kaizen-intent match --json
      → envelope.data: {matched[], count}
        matched[] sorted by confidence DESC

    kaizen-intent suggest --text "..." --json
      → envelope.data: {intent: {...} | null}
        Returns the SINGLE highest-confidence match (for statusline /
        agent one-liner consumption)

## Intent shape (intents.yaml)

```yaml
version: 1
intents:
  - id: wrap-up
    description: User signals end-of-session; suggest handoff create.
    triggers:
      - { kind: phrase, pattern: "let'?s wrap (this )?up", case_insensitive: true }
      - { kind: phrase, pattern: "wrap.*session", case_insensitive: true }
    action:
      suggest: "kaizen-handoff scaffold --session <project>"
      subcommand: handoff-scaffold
      confidence: 0.9

  - id: repeated-bash-failures
    description: 3+ failing Bash calls in 60s; suggest investigation.
    triggers:
      - kind: event_pattern
        evt_type: PostToolUse
        tool_name: Bash
        exit_code_nonzero: true
        count_at_least: 3
        window_seconds: 60
    action:
      suggest: "3+ Bash failures in 60s — investigate root cause"
      subcommand: debug
      confidence: 0.95
```

Triggers within one intent are **OR'd** — any matching trigger fires
the intent. Multiple intents can match the same input; `match`
returns all sorted by confidence; `suggest` returns the top one.

## Trigger reference

### `phrase`

```yaml
{ kind: phrase,
  pattern: "<python regex>",
  case_insensitive: true|false   # default false
}
```

Uses Python `re.search`. Pattern compiled with `re.IGNORECASE` flag
when `case_insensitive: true`. Invalid regex → silently doesn't match
(no crash; the rule is best-effort).

### `event_pattern`

```yaml
{ kind: event_pattern,
  evt_type: <PreToolUse|PostToolUse|UserPromptSubmit|...>,  # optional
  tool_name: <Bash|Edit|Read|...>,                            # optional
  exit_code_nonzero: true|false,                              # optional
  count_at_least: <N>,
  window_seconds: <N>                                         # 0 = no window
}
```

Filters the supplied event list, then checks whether any sliding
window of `count_at_least` consecutive matching events spans
`<= window_seconds`. Events must carry `ts_unix` for the window check
(dxm always populates this).

`exit_code_nonzero: true` requires the event to have `exit_code` set
to a non-zero integer. Useful for "failures within a window" rules.

## Integration with dxm

```bash
# Tail the last 60s of events from dxm, pipe into intent match
kaizen-dxm tail --session <sid> --back 60 --json \
  | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["data"]["events"]))' \
  | xargs -0 kaizen-intent match --events-json
```

Or in one shot: a future `kaizen-intent watch --session SID` could
subscribe to dxm and emit suggestions on every event. Filed for
follow-up.

## Integration with UserPromptSubmit hook

Future wiring: a new `intent-userprompt.sh` hook reads the user's
prompt text + calls `kaizen-intent suggest --text "$PROMPT" --json`.
When a suggestion fires, surface it as a system reminder to the
agent. Today, the agent can call `kaizen-intent match` explicitly.

## Agent-in-the-loop contract

`kaizen-intent` does NOT auto-execute suggested actions. The agent
decides whether to act based on:

1. **Confidence** (numeric, 0.0–1.0). `suggest` returns the top
   match; agent can ignore low-confidence ones.
2. **Context** — the agent knows whether the suggestion fits the
   current goal. A `wrap-up` suggestion on the third turn of a
   long session is noise.
3. **Side-effects** — suggestions like `compact` reset context;
   agent must judge whether to commit to that.

This is intentional. Auto-execution at the rule level is an
anti-pattern in agent systems (sees-something-does-something
trips up real users); the rules engine surfaces signal, the agent
exercises judgment.

## When to add a new intent

Add an intent when:
- A recurring text pattern (user phrasing, error message) maps to a
  well-defined kaizen action you keep doing manually
- An event pattern (failures, time, sequence) reliably indicates a
  specific next step
- The suggested action is **kaizen-shaped** (uses a kaizen CLI or
  slash command)

Don't add an intent when:
- The pattern is one-off / user-specific
- The suggested action is judgment-heavy (the agent should think,
  not pattern-match)
- The trigger would fire constantly (low-signal)

## Env

  `KAIZEN_INTENTS_FILE`     override default `intents.yaml` path
  `KAIZEN_INTENT_DISABLE=1` all match/suggest calls no-op (returns
                            empty matched list; never errors)

## Iron-law interaction

- **bin-wrapper-per-cli** — `bin/kaizen-intent` wraps `intent.py`.
- **plugin-manifest-permissions** — explicit perm entries in
  `plugin.json`.
- **schema-driven domain yaml** — intents.yaml IS the rule set;
  intent.py just walks it deterministically.
- **sandbox-tests** — `KAIZEN_INTENTS_FILE` env per-test.

## What this skill is NOT

- An LLM-driven intent classifier. Pattern matching only. For
  semantic-level intent detection (paraphrase tolerance, novel
  phrasing), a Haiku call would slot in cleanly — filed for
  follow-up via a `--llm-fallback` flag.
- A workflow engine. Intents recommend single actions, not
  multi-step orchestration. For that, see `flow.py` /
  `workflow` routines.
- An auto-execution layer. Suggestions are advisory.

## Sibling-skill relationships

`schema-driven-cli` — the lens runtime; intent's manifest is a v2 lens
`deus-ex-machina`   — the event stream intent consumes for
                       event_pattern triggers
`handoff`           — primary action target (wrap-up, resume-prior)
`decision-rubric`   — different shape: rubric maps SIGNALS to BUCKETS
                       deterministically; intent maps TEXT/EVENTS to
                       SUGGESTED ACTIONS. Both first-match-wins, both
                       confidence-ranked.
