---
name: plugin-development
description: "Hub for kaizen plugin-dev work. Verbs - intake | workflow | validate | rules | dispatch | audit | surface | cluster. Triggers - "add a kaizen feature", "plugin-dev workflow", "validate feature", "iron laws", "intake checklist"."
argument-hint: "[intake [<work-type>] | workflow | validate | rules | dispatch <task> | audit | surface | cluster <name> | (no args = load skill)]"
allowed-tools: ["AskUserQuestion", "Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/plugin-development/scripts/validate.py:*)", "Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/plugin-development/scripts/intake.py:*)", "Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/workflow/workflow_runner.py:*)", "Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-iron-laws:*)", "Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-rubric:*)", "Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-gatekeeper:*)", "Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-surface:*)"]
---

# /kaizen:plugin-development

The single entry point for plugin-development work in kaizen-md.
Handles all **routing** (which subagent, which routine, which
validator) and **context** (rules, feature shape, iron-laws,
plugin inventory) for building and auditing kaizen features.

## Verbs

| Verb | Does | Backend |
|---|---|---|
| (none) | Load the `plugin-development` skill body — full reference | `Skill(plugin:plugin-development)` |
| `intake [<type>]` | **QA checklist** — which skills to load for a given work-type (new-cli, new-hook, refactor, bug-fix, etc.). No arg → full table. | `intake-checklist.yaml` (data-driven) |
| `workflow` | Show the 8-stage TDD routine (run via `/workflow schema=plugin-development`) | `workflow_runner.py show plugin-development` |
| `validate [args]` | Validate staged diff or one feature against canonical shape + iron-laws | `validate.py` |
| `rules` | Dump iron-laws registry as JSON | `kaizen-iron-laws list --json` |
| `dispatch` | Show the agent-dispatch rubric — pick the right subagent for a task | `kaizen-rubric lint` on `dispatch-rubric.yaml` |
| `audit` | Run gatekeeper against the whole plugin | `kaizen-gatekeeper check --all` |
| `surface` | Inventory plugin surfaces (commands / bins / hooks / skills / MCPs) | counts via `ls` + `find` |
| `cluster <name>` | List commands in a domain cluster | grep over regenerated `commands/help.md` |

## Routing

!`bash -c '
ARGS="${ARGUMENTS:-}"
case "$ARGS" in
  intake|intake\ *)
    TYPE="${ARGS#intake}"
    TYPE="$(echo "$TYPE" | sed "s/^[[:space:]]*//")"
    python3 "${CLAUDE_PLUGIN_ROOT}/skills/plugin-development/scripts/intake.py" $TYPE
    ;;
  workflow|workflow\ *)
    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/workflow/workflow_runner.py" show plugin-development ;;
  validate|validate\ *)
    python3 "${CLAUDE_PLUGIN_ROOT}/skills/plugin-development/scripts/validate.py" ${ARGS#validate} ;;
  rules|rules\ *)
    "${CLAUDE_PLUGIN_ROOT}/bin/kaizen-iron-laws" list --json | head -80 ;;
  dispatch|dispatch\ *)
    echo "[plugin-development dispatch] agent-dispatch rubric:"
    "${CLAUDE_PLUGIN_ROOT}/bin/kaizen-rubric" lint --rubric "${CLAUDE_PLUGIN_ROOT}/skills/agent-formatting/domain/dispatch-rubric.yaml"
    echo ""
    echo "Compute signals from the task description (binary 0/1) — see skills/agent-formatting/domain/dispatch-rubric.yaml header for the 9 signal names + regexes. Then:"
    echo "  kaizen rubric eval --rubric .../dispatch-rubric.yaml --signals '"'"'{\"tdd\":1, \"multi_phase\":1, ...}'"'"'"
    ;;
  audit|audit\ *)
    "${CLAUDE_PLUGIN_ROOT}/bin/kaizen-gatekeeper" check --all 2>&1 | tail -25 ;;
  surface|surface\ *)
    PR="${CLAUDE_PLUGIN_ROOT}"
    echo "kaizen plugin surface inventory"
    echo "  commands:  $(ls "$PR/commands"/*.md 2>/dev/null | wc -l)"
    echo "  bins:      $(ls "$PR/bin" 2>/dev/null | wc -l)"
    echo "  hooks:     $(ls "$PR/hooks/claude"/*.sh 2>/dev/null | wc -l)"
    echo "  skills:    $(find "$PR/skills" -maxdepth 2 -name SKILL.md 2>/dev/null | wc -l)"
    echo "  mcps:      $(ls "$PR/skills/workflow/scripts"/*_mcp.py 2>/dev/null | wc -l)"
    echo "  agents:    $(ls "$PR/agents" 2>/dev/null | wc -l)"
    echo "  schemas:   $(ls -d "$PR/schemas"/*/ 2>/dev/null | wc -l)"
    ;;
  cluster|cluster\ *)
    NAME="${ARGS#cluster}"
    NAME="$(echo "$NAME" | sed "s/^[[:space:]]*//")"
    if [ -z "$NAME" ]; then
      echo "[plugin-development cluster] usage: cluster <name>"
      echo "  valid: audit/quality observability brain/memory workflow plugin-meta discovery/search dev-aids"
    else
      awk -v target="## $NAME" "
        /^## / { if (in_section) exit; if (\$0 ~ target) in_section=1 }
        in_section { print }
      " "${CLAUDE_PLUGIN_ROOT}/commands/help.md"
    fi
    ;;
  "")
    echo "[plugin-development] no args — the plugin-development skill loads via Skill(plugin:plugin-development)."
    echo ""
    echo "Verbs: workflow | validate | rules | dispatch | audit | surface | cluster <name>"
    ;;
  *)
    echo "[plugin-development] unknown verb: $ARGS" >&2
    echo "  valid: workflow | validate | rules | dispatch | audit | surface | cluster" >&2
    exit 2 ;;
esac'`

## Intake QA pattern (when `intake` is invoked with no work-type)

When the user runs `/kaizen:plugin-development intake` (no arg), the
bash dispatch above prints the full work-types table. **The agent
SHOULD ALSO call AskUserQuestion** to elicit the work-type
interactively, then re-invoke `intake <chosen-type>` to print the
final skill bundle.

Follow the `/kaizen:mode` pattern: the slash command body is
instructional; the agent does the orchestration via AskUserQuestion.

### Question to ask

```
question: "What plugin-development work are you doing right now?"
header:   "Work type"
multiSelect: false
options:
  - label: "New CLI feature"           description: "argparse main + bin wrapper + permissions + tests"
  - label: "New skill"                 description: "SKILL.md + agent-facing surface; no script"
  - label: "New hook"                  description: "lifecycle hook (PreToolUse / SessionEnd / etc.)"
  - label: "New MCP server"            description: "FastMCP server exposing tools to Claude"
  - label: "New rubric / classifier"   description: "decision-rubric pattern (BucketWalker)"
  - label: "New indexer"               description: "SQLite + semantic search with graceful fallback"
  - label: "Bug fix"                   description: "Regression in existing feature"
  - label: "Refactor"                  description: "Restructure without behavior change"
  - label: "Add tests"                 description: "Coverage gap on existing code"
  - label: "Rename / deprecate command" description: "Slash command renamed; preserve back-compat"
  - label: "Dispatch a subagent"       description: "Pick the right subagent type"
  - label: "Schema / config work"      description: "Domain yaml / JSON schema"
  - label: "Generic plugin work"       description: "(fallback — always-load skills only)"
```

### After the user picks

Map their label to the `work_types[].id` in
`skills/plugin-development/domain/intake-checklist.yaml`:

| Label | id |
|---|---|
| New CLI feature | `new-cli` |
| New skill | `new-skill` |
| New hook | `new-hook` |
| New MCP server | `new-mcp-server` |
| New rubric / classifier | `new-rubric-feature` |
| New indexer | `new-indexer` |
| Bug fix | `bug-fix` |
| Refactor | `refactor` |
| Add tests | `add-tests` |
| Rename / deprecate command | `rename-command` |
| Dispatch a subagent | `dispatch-subagent` |
| Schema / config work | `schema-or-config` |
| Generic plugin work | `generic-plugin-work` |

Then re-invoke: `/kaizen:plugin-development intake <id>` — the bash
dispatch above prints the skill bundle (always-load skills + the
work-type-specific skills) so the agent can Skill-load each one
before writing code.

### Direct invocation (skip the QA)

If the user already knows the work-type, pass it as an arg:
`/kaizen:plugin-development intake new-cli` → prints the bundle
immediately. Substring + trigger-phrase match (first-match-wins),
so `/kaizen:plugin-development intake "fix a bug"` also resolves
correctly via the `bug-fix` triggers.

## When to use each verb

| Situation | Verb |
|---|---|
| About to ship a new feature (new skill / bin / command / hook / MCP) | `workflow` |
| Staged a commit; want pre-commit assurance the feature shape is right | `validate` |
| Need to look up an iron-law (e.g. "what's the bin-wrapper-per-cli rule?") | `rules` |
| Starting a new task; not sure which skills to load | `intake` (no arg → agent asks via AskUserQuestion) |
| About to dispatch a subagent; not sure which type | `dispatch` |
| Periodic health check on the whole plugin | `audit` |
| Quick "how big is the plugin" check | `surface` |
| "What commands are in the brain/memory cluster?" | `cluster brain/memory` |

## Pairing

- **Skill body** (`skills/plugin-development/SKILL.md`) — the authoritative prose; always-load via `Skill(plugin:plugin-development)`.
- **Schema** (`schemas/plugin-development/schema.yaml`) — what `workflow` shows.
- **Validator** (`skills/plugin-development/scripts/validate.py`) — what `validate` invokes.
- **Iron-laws registry** (`skills/iron-laws/domain/iron-laws.yaml`) — what `rules` dumps.
- **Dispatch rubric** (`skills/agent-formatting/domain/dispatch-rubric.yaml`) — what `dispatch` lints.
- **Gatekeeper** (`bin/kaizen-gatekeeper`) — what `audit` runs.
- **Help.md** (`commands/help.md`) — what `cluster` greps.

This command is intentionally the **single entry point** for
plugin-development work. Instead of remembering 7 separate kaizen-*
bins (`kaizen-gatekeeper`, `kaizen-iron-laws`, `kaizen-rubric`,
`kaizen-surface`, the validator script path, the workflow runner
path, the help.md location), agents + users dispatch through one
verb.

## Folded surface (formerly separate slashes)

Four slashes folded here across the cat-2 consolidation — bins stay reachable:

| Concern | Bin (direct) | Use case |
|---|---|---|
| Brain-sourced rule inspection | `kaizen-rules` / `kaizen-iron-laws` | `list | show <name> | validate | template` — was `/kaizen:rules` |
| Workflow-schema inspection | `python3 scripts/workflow/workflow_runner.py {list|show|branches|validate}` | declarative DAG inspection — was `/kaizen:schema` |
| TAP pipeline smoke | `kaizen-test` | install → backlog → gate → hooks → backup → migrate pipeline — was `/kaizen:test` |
| Python unit + pytest suite | `kaizen-tests` (note the `s`) | parallel harness, auto-style detect — was `/kaizen:test-suite` |

Reach via this hub's `rules` verb (already wired) or the bins
directly. Both schemas + rules continue to drive the
behaviour-config / iron-laws / workflow surfaces.
