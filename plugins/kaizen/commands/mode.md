---
name: mode
description: "Set this session's mode (loop | workflow | neither) and pick discipline bundles via QA. Records the choice in .kaizen/session-mode.json so downstream hooks (per-prompt skill reminders, context-pressure auto-handoff, etc.) can act on it. Triggers on \"set session mode\", \"start loop\", \"start workflow\", \"choose disciplines for this session\"."
argument-hint: "loop | workflow | neither"
allowed-tools: ["Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-session-mode:*)", "AskUserQuestion"]
---

# /kaizen:mode — session mode + discipline bundles

Routes the user to the kaizen session-intake QA but with the mode
pre-selected when an argument is given. Skips the auto-fire
SessionStart prompt cycle when invoked directly.

## Argument: `$ARGUMENTS`

Parse the argument. Valid values: `loop`, `workflow`, `neither`.

### When `$ARGUMENTS` is one of `loop`/`workflow`/`neither`

Mode is known — skip Q1, ask the discipline-bundles question PLUS
the auto-handoff-threshold question in a single AskUserQuestion call.

```
QUESTION 1 — disciplines (multiSelect):
  question: "Which discipline bundles should be enforced this session?"
  header:   "Disciplines"
  multiSelect: true
  options:
    - label: "Simplicity (KISS + YAGNI + DRY)"
      description: "Anti-bloat — small code, no premature abstraction, no repetition."
    - label: "Structure (SOLID + SoC + LoD + Onion-DDD + Hexagonal + Clean + DIP + Bounded-Contexts)"
      description: "Architecture — layered systems, inward-only deps, ports & adapters, bounded contexts."
    - label: "Process (TDD + Boy-Scout + Convention)"
      description: "How-you-work — test-first, leave it cleaner, follow existing patterns."
    - label: "Karpathy 4"
      description: "Code-as-communication — readable intent over clever density."

QUESTION 2 — auto-handoff trigger (single-select):
  question: "Auto-trigger a handoff when context window reaches ____ %?"
  header:   "Auto-handoff"
  multiSelect: false
  options:
    - label: "25%"        — paranoid, fire very early
    - label: "50%"        — half-full, comfortable buffer
    - label: "75%"        — conservative (recommended)
    - label: "85%"        — pushing it
    - label: "Disabled"   — no auto-handoff
```

Bundle name mapping (lowercase, comma-separated):
- "Simplicity (…)"  → `simplicity`
- "Structure (…)"   → `structure`
- "Process (…)"     → `process`
- "Karpathy 4"      → `karpathy`

Threshold mapping (integer or OMIT for Disabled):
- 25% / 50% / 75% / 85%  → numeric value via `--threshold`
- Disabled               → OMIT the `--threshold` flag

Persist all picks via ONE command:

```bash
kaizen-session-mode set $ARGUMENTS --bundles <csv> --threshold <25|50|75|85>
```

Omit flags whose user-pick was empty (zero bundles → no `--bundles`;
Disabled threshold → no `--threshold`).

### When `$ARGUMENTS` is empty

Both mode and disciplines unknown — fall back to the full
SessionStart-style QA: call `AskUserQuestion` with TWO questions in
one call (mode + disciplines), per the session-intake hook's
instruction in `hooks/claude/session-intake.sh`.

### When `$ARGUMENTS` is invalid

Print one line: `kaizen-mode: invalid argument '<arg>' — valid: loop | workflow | neither`. Do NOT call AskUserQuestion. Do NOT modify state.

## After persisting

Confirm to the user in one line:

```
kaizen: session mode = <mode>, bundles = <csv>
```

Then proceed with whatever the user wanted to do (if they had any
follow-up implied). When mode is `loop` or `workflow`, the agent
should typically ask the user for the loop prompt / workflow routine
as a natural next step — but do NOT auto-start one; the user may
have invoked `/kaizen:mode` purely to record the discipline.
