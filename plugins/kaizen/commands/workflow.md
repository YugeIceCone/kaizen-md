---
name: workflow
description: "Persist + read the workflow-shape DEFAULTS for this project (or globally): scope / run-mode / disciplines / auto-handoff threshold. Sister to /kaizen:session-mode — session-mode captures the CURRENT session's intake; this captures the persistent DEFAULTS future sessions start from. No-args → 4-question AskUserQuestion wizard. With-args → direct dispatch to `kaizen-workflow-config`. Triggers on \"set workflow defaults\", \"configure workflow\", \"workflow shape\", \"persistent disciplines\", \"workflow menu\"."
argument-hint: "(empty = interactive 4-Q wizard) | [set|get|show|path|reset ...]"
allowed-tools: ["AskUserQuestion", "Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-workflow-config:*)", "Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/workflow_config.py:*)"]
---

# /kaizen:workflow — persistent workflow-shape defaults

Persist (and read) the workflow-shape DEFAULTS a project — or the user
globally — wants future sessions to start from. Read by
`/kaizen:session-mode` as a pre-fill source; downstream hooks
(auto-handoff, skill-suggest) can also consult these defaults when no
explicit session-mode is set.

!`bash ${CLAUDE_PLUGIN_ROOT}/bin/kaizen-workflow-config $ARGUMENTS`

## Interactive wizard (when `$ARGUMENTS` is empty)

When the user invokes `/kaizen:workflow` with **no arguments**, the
body above runs `kaizen-workflow-config` with no args (which errors
because a subcommand is required — this is expected; the agent
SHOULD step the user through the AskUserQuestion wizard below, then
re-invoke this command with the resolved `set` flags).

Follow the `/kaizen:session-mode` orchestration pattern: the body is
instructional, the agent does the AskUserQuestion calls. All 4
questions fit in a single AskUserQuestion call (within the
4-question-per-call contract).

### Question 1 — scope

```
question:    "Persist these defaults at which scope?"
header:      "Scope"
multiSelect: false
options:
  - label: "This project (.kaizen/workflow.json)"
    description: "Lives in the repo. Commit it to share with the team."
  - label: "User-global (~/.claude/.kaizen/workflow-global.json)"
    description: "Applies across every project for this user. Project file overrides it."
```

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
Q2=Loop), assemble:

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

## Relationship to /kaizen:session-mode

| Concern | `/kaizen:session-mode` | `/kaizen:workflow` |
|---|---|---|
| **Scope** | Current session only | Persists across sessions |
| **Storage** | `.kaizen/session-mode.json` (per session id) | `.kaizen/workflow.json` (project) OR `workflow-global.json` (user) |
| **Lifetime** | Reset at session boundary | Until manually changed |
| **Purpose** | "What disciplines apply RIGHT NOW" | "What this project defaults to" |
| **Consumer** | per-prompt hook, auto-handoff hook | session-intake pre-fill + downstream hooks when no session-mode is set |

The two are designed to compose: workflow.json sets the project's
defaults; session-mode lets the user override for a single session
without mutating the durable file. SessionStart QA reads workflow.json
as the pre-fill source for its questions when present.

## Schema

JSON Schema: `skills/workflow/domain/schemas/workflow-config.schema.json`
(version 1). Required field: `version`. All others optional — partial
configs are valid (set only what you want to override).
