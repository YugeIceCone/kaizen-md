---
name: workflow
description: "Workflow-shape config — default scope × run-mode × disciplines × threshold. Three scopes - session-mode (ephemeral), project, user-global. 4-question wizard or direct dispatch. Triggers - \"set session mode\", \"start loop/workflow\", \"choose disciplines\"."
argument-hint: "(empty = interactive 4-Q wizard) | [set|get|show|path|reset ...]"
allowed-tools: ["AskUserQuestion", "Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-workflow-config:*)", "Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-session-mode:*)", "Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/workflow/workflow_config.py:*)"]
---

# /kaizen:workflow — persistent workflow-shape defaults

Persist (and read) the workflow-shape DEFAULTS a project — or the user
globally — wants future sessions to start from. Read by
`/kaizen:session-mode` as a pre-fill source; downstream hooks
(auto-handoff, skill-suggest) can also consult these defaults when no
explicit session-mode is set.

!`bash -c '${CLAUDE_PLUGIN_ROOT}/bin/kaizen-workflow-config ${ARGUMENTS:-show}; [ -z "${ARGUMENTS:-}" ] && [ -f .kaizen/workflow.json ] && python3 ${CLAUDE_PLUGIN_ROOT}/scripts/workflow/_workflow_prefill.py --from .kaizen/workflow.json; true'`

## Interactive wizard (when `$ARGUMENTS` is empty)

When the user invokes `/kaizen:workflow` with **no arguments**, the
body above defaults to `kaizen-workflow-config show` — a clean
read-only print of the current persisted state (empty on first run).
The agent SHOULD then step the user through the AskUserQuestion
wizard below and re-invoke this command with the resolved `set` flags
to persist the picks.

Follow the `/kaizen:session-mode` orchestration pattern: the body is
instructional, the agent does the AskUserQuestion calls. All 4
questions fit in a single AskUserQuestion call (within the
4-question-per-call contract).

**Pre-fill defaults (Phase 9 auto-fill):** If the body output above
contains a "PERSISTED workflow defaults" block, those values are the
project's saved picks. Use them as the DEFAULT options in each
AskUserQuestion (mark "(persisted)" in the label). User can confirm
or override; only re-prompt for fields with no persisted value.

### Question 1 — scope

```
question:    "Apply these workflow defaults at which scope?"
header:      "Scope"
multiSelect: false
options:
  - label: "This session only (.kaizen/session-mode.json)"
    description: "Ephemeral — applies just to the current session; resets at session boundary. Folds the retired /kaizen:session-mode slash."
  - label: "This project (.kaizen/workflow.json)"
    description: "Persistent — lives in the repo. Commit it to share with the team."
  - label: "User-global (~/.claude/.kaizen/workflow-global.json)"
    description: "Persistent across every project for this user. Project file overrides it."
```

When Q1 picks **This session only**, the agent dispatches
`kaizen-session-mode set <mode> --skills <comma-sep>
--threshold <N|disabled>` instead of `kaizen-workflow-config set` —
the file format + consumer hooks (`auto-handoff.sh`,
`userprompt-skills-reminder.sh`, `session-intake.sh`) all read from
`.kaizen/session-mode.json`, so the session scope intentionally uses
the session-mode storage rather than workflow-config's JSON.

The two remaining persistent scopes (project / global) use
`kaizen-workflow-config set --scope <project|global>` as before.

### Question 2 — run mode

```
question:    "Default workflow shape?"
header:      "Run mode"
multiSelect: false
options:
  - label: "Routine (multi-stage)"
    description: "/workflow runs a curated routine (build-feature, fix-bug, refactor, etc.). Stage gates between steps."
  - label: "Loop (Ralph)"
    description: "/kaizen:loop runs a self-correcting iteration loop. Continues until ledger empty or completion-promise emitted."
  - label: "Schema (declarative DAG)"
    description: "/workflow runs a schema (onion-tdd-strict / mcp-build / spec-driven). Each artifact has a gate."
```

When Q2 picks **Loop**, also follow the **`/kaizen:loop`** wizard
(P3 — see `commands/loop.md`) to set iteration budget + stop-conditions.
The 2 extra questions can run in a second AskUserQuestion call after
this one resolves; persist the answers via `--loop-its` + `--loop-stop`
flags on the same `kaizen-workflow-config set` call.

### Question 3 — disciplines (multiSelect)

```
question:    "Which discipline bundles should be enforced by default?"
header:      "Disciplines"
multiSelect: true
options:
  - label: "Simplicity (kiss + yagni + dry)"
    description: "Anti-bloat: small code, no premature abstraction, no repetition."
  - label: "Structure (solid + soc + lod + onion-ddd + hexagonal + clean-arch + dip + bounded-contexts)"
    description: "Architecture: layered systems, inward-only deps, ports & adapters, bounded contexts."
  - label: "Process (tdd + boy-scout + convention + karpathy)"
    description: "How-you-work: test-first, leave it cleaner, follow existing patterns, code-as-communication."
```

Bundle expansion (when assembling the `--disciplines` flag):

| Bundle pick | Expands to (comma-sep)                                              |
|-------------|---------------------------------------------------------------------|
| Simplicity  | `kiss,yagni,dry`                                                    |
| Structure   | `solid,soc,lod,onion-ddd,hexagonal,clean-arch,dip,bounded-contexts` |
| Process     | `tdd,boy-scout,convention,karpathy`                                 |

Merge picks then deduplicate. Example: Simplicity + Process →
`kiss,yagni,dry,tdd,boy-scout,convention,karpathy`.

### Question 4 — auto-handoff threshold

```
question:    "Auto-trigger a handoff when context window reaches ____ %?"
header:      "Threshold"
multiSelect: false
options:
  - label: "75% (recommended)"
    description: "Conservative — fires with comfortable buffer for the wrap-up itself."
  - label: "85%"
    description: "Pushing it — leaves less buffer; ok for short sessions."
  - label: "50%"
    description: "Half-full — fires very early. Fine for paranoid / cheap-context flows."
  - label: "Disabled"
    description: "No auto-handoff. /kaizen:handoff create stays manual-only."
```

### Arg assembly

After all four answers (plus optional loop sub-wizard from P3 when
Q2=Loop), pick the dispatcher based on Q1.

**Session scope (Q1 = "This session only")** — dispatch `kaizen-session-mode`:

```bash
kaizen-session-mode set <Q2-mode> \
    --skills <expanded Q3>          # comma-sep discipline tags
    --threshold <Q4>                # 25 | 50 | 75 | 85 | disabled
```

`<Q2-mode>` maps as: Routine → `workflow`, Loop → `loop`, Schema → `workflow`
(session-mode's `mode` field only knows `loop` / `workflow` / `neither`;
schema-flavored runs surface as `workflow`).

**Project / global scope (Q1 = "This project" or "User-global")** —
dispatch `kaizen-workflow-config`:

```bash
kaizen-workflow-config set \
    --scope <Q1>                    # project | global
    --run-mode <Q2>                 # routine | loop | schema
    --disciplines <expanded Q3>     # comma-sep
    --threshold <Q4>                # 25 | 50 | 75 | 85 | disabled
    [--loop-its <N>]                # when Q2=Loop, from /kaizen:loop wizard
    [--loop-stop <conds>]           # when Q2=Loop, comma-sep
    [--routine <name>]              # when Q2=Routine, optional default routine
    [--schema <name>]               # when Q2=Schema, optional default schema
```

Threshold mapping: `"75% (recommended)"` → `--threshold 75`,
`"Disabled"` → `--threshold disabled`.

Then re-invoke: `/kaizen:workflow show` to confirm the persisted state.

## Subcommands (direct CLI)

| Invocation | What runs |
|---|---|
| `/kaizen:workflow set [--scope ...] [--run-mode ...] [--disciplines ...] [--threshold ...]` | Write/update fields. Scope defaults to `project`. |
| `/kaizen:workflow get [--scope ...] [--json]` | Print resolved config. With no `--scope`, merges project on top of global. |
| `/kaizen:workflow show [--scope ...]` | Human-readable view. |
| `/kaizen:workflow path [--scope ...]` | Print the JSON file location. |
| `/kaizen:workflow reset [--scope ...] [--yes]` | Delete the file. Default dry-run. |

## Folded surface — what happened to /kaizen:session-mode

**Retired.** `/kaizen:session-mode` was a separate slash for ephemeral
per-session disciplines + mode + threshold. Its functionality folded
into `/kaizen:workflow` Q1 scope = "This session only". One slash, three
scopes (session / project / global), one mental model.

The underlying storage + bin + python module (`session_mode.py`,
`kaizen-session-mode`, `.kaizen/session-mode.json`) all stay — they're
the back-end implementation of the session scope (and consumed directly
by `auto-handoff.sh`, `userprompt-skills-reminder.sh`, and
`session-intake.sh`). Only the slash retires.

**Scope comparison:**

| Scope            | Storage                                          | Lifetime         | Dispatcher                              |
|------------------|--------------------------------------------------|------------------|-----------------------------------------|
| Session only     | `.kaizen/session-mode.json`                      | Per session      | `kaizen-session-mode set ...`           |
| This project     | `.kaizen/workflow.json`                          | Until changed    | `kaizen-workflow-config set --scope project ...` |
| User-global      | `~/.claude/.kaizen/workflow-global.json`         | Until changed    | `kaizen-workflow-config set --scope global ...`  |

Persistent scopes act as pre-fill sources for the SessionStart QA;
session scope overrides them for a single session without mutating
the durable files.

## Schema

JSON Schema: `skills/workflow/domain/schemas/workflow-config.schema.json`
(version 1). Required field: `version`. All others optional — partial
configs are valid (set only what you want to override).
