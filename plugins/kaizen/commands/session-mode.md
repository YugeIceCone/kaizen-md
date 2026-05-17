---
name: session-mode
description: "Set this session's mode (loop | workflow | neither) and pick discipline bundles via QA. Records the choice in .kaizen/session-mode.json so downstream hooks (per-prompt skill reminders, context-pressure auto-handoff, etc.) can act on it. Triggers on \"set session mode\", \"start loop\", \"start workflow\", \"choose disciplines for this session\". (Bin wrapper is `kaizen-session-mode` — old `/kaizen:mode` slash is a deprecation alias.)"
argument-hint: "loop | workflow | neither"
allowed-tools: ["Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-session-mode:*)", "AskUserQuestion"]
---

# /kaizen:session-mode — session mode + discipline bundles

Routes the user to the kaizen session-intake QA but with the mode
pre-selected when an argument is given. Skips the auto-fire
SessionStart prompt cycle when invoked directly.

## Argument: `$ARGUMENTS`

Parse the argument. Valid values: `loop`, `workflow`, `neither`.

### When `$ARGUMENTS` is one of `loop`/`workflow`/`neither`

Mode is known — skip the mode question and ask FOUR questions in a
single AskUserQuestion call: coding-style disciplines, operational
disciplines, work-mode disciplines, and auto-handoff threshold.
(Fits AskUserQuestion's 4-question ceiling exactly.)

```
QUESTION 1 — coding-style disciplines (multiSelect):
  question: "Which CODING-STYLE disciplines should be enforced this session?"
  header:   "Coding style"
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

QUESTION 2 — operational disciplines (multiSelect):
  question: "Which OPERATIONAL disciplines should be cross-cutting this session?"
  header:   "Operational"
  multiSelect: true
  options:
    - label: "Quality (gatekeeper + iron-laws + karpathy + simplify + vibe-check)"
      description: "Audit/review surface — auto-run gatekeeper and lint disciplines proactively."
    - label: "Security (security-review + iron-laws + verify-before-execution)"
      description: "OWASP-style scan + verify-before-execute gates on risky operations."
    - label: "Brain hygiene (remember + reflect + memory-state + evolve)"
      description: "Second Brain upkeep — capture / reflect / promote beliefs throughout session."
    - label: "Plugin-dev (plugin-development + plugin-pitfalls + iron-laws + writing-skills + command-development)"
      description: "kaizen plugin authoring — canonical feature shape + iron laws + skill/command conventions."

QUESTION 3 — work-mode disciplines (multiSelect):
  question: "Which WORK-MODE disciplines apply to this session's primary task type?"
  header:   "Work mode"
  multiSelect: true
  options:
    - label: "Discovery (explore + brainstorming + research + ast-grep-router + decision-rubric)"
      description: "Up-front exploration / idea-generation BEFORE implementation."
    - label: "Debugging (systematic-debugging + verify-before-execution + verification-before-completion)"
      description: "Bug hunt / RCA loops with hypothesis → test → narrow discipline."
    - label: "Refactoring (boy-scout + dry + onion-ddd + shim-and-sweep + finishing-a-development-branch)"
      description: "Structural cleanups with safe carve-outs + wrap-up gate."
    - label: "Planning (writing-plans + executing-plans + create-plan + execute-plan + decision-rubric)"
      description: "Multi-step work driven by an explicit plan/tasks artifact."

QUESTION 4 — auto-handoff trigger (single-select):
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

Bundle name mapping (lowercase, comma-separated). Merge picks from
ALL THREE multiSelect questions into a single `--bundles` CSV:

| Label                  | Bundle id                       |
|------------------------|---------------------------------|
| **Coding-style tier**  |                                 |
| Simplicity (…)         | `simplicity`                    |
| Structure (…)          | `structure`                     |
| Process (…)            | `process`                       |
| Karpathy 4             | `karpathy`                      |
| **Operational tier**   |                                 |
| Quality (…)            | `quality`                       |
| Security (…)           | `security`                      |
| Brain hygiene (…)      | `brain-hygiene`                 |
| Plugin-dev (…)         | `plugin-dev`                    |
| **Work-mode tier**     |                                 |
| Discovery (…)          | `discovery`                     |
| Debugging (…)          | `debugging`                     |
| Refactoring (…)        | `refactoring`                   |
| Planning (…)           | `planning`                      |

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

Print one line: `kaizen-session-mode: invalid argument '<arg>' — valid: loop | workflow | neither`. Do NOT call AskUserQuestion. Do NOT modify state.

## After persisting

Confirm to the user in one line:

```
kaizen: session mode = <mode>, bundles = <csv>
```

Then proceed with whatever the user wanted to do (if they had any
follow-up implied). When mode is `loop` or `workflow`, the agent
should typically ask the user for the loop prompt / workflow routine
as a natural next step — but do NOT auto-start one; the user may
have invoked `/kaizen:session-mode` purely to record the discipline.
