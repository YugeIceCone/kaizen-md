---
name: plugin-development
description: "Multi-verb entry point for adding/auditing features in the kaizen-md plugin. Default: load the plugin-development skill (rules + 13-slot feature shape). `workflow` runs the 8-stage TDD routine (scope → scaffold → wire → red → green → refactor → validate → document). `validate` runs the schema-coverage + plugin-shape validator. `rules` lists the iron-laws + feature-shape summary. Triggers on \"add a kaizen feature\", \"build a plugin feature\", \"plugin-dev workflow\", \"feature shape\", \"iron laws\", \"validate feature\"."
argument-hint: "[workflow | validate | rules | (no args = load skill)]"
allowed-tools: ["Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/plugin-development/scripts/validate.py:*)", "Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/workflow_runner.py:*)", "Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-iron-laws:*)"]
---

# /kaizen:plugin-development

Build (or audit) a kaizen-plugin feature with the canonical
13-slot shape + 13 iron-laws + TDD discipline.

## Verbs

| Verb | Does |
|---|---|
| (none) | Load the `plugin-development` skill body — full reference for the feature shape, iron laws, and wiring checklist. |
| `workflow` | Run the **8-stage TDD routine** (scope → scaffold → wire → red → green → refactor → validate → document). Schema at `plugins/kaizen/schemas/plugin-development/schema.yaml`. |
| `validate` | Run `skills/plugin-development/scripts/validate.py` on the staged diff or a specific feature. |
| `rules` | Print the iron-laws registry + feature-shape summary as JSON. |

## Routing

The body below routes on `$ARGUMENTS`:

- empty → load `Skill(plugin:plugin-development)` (no shell exec)
- `workflow` → `workflow_runner.py show plugin-development` (print the routine; `/workflow schema=plugin-development` runs it)
- `validate [args...]` → `validate.py [args...]`
- `rules` → `kaizen-iron-laws list --json`

!`bash -c '
ARGS="${ARGUMENTS:-}"
case "$ARGS" in
  workflow|workflow\ *)
    python3 "${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/workflow_runner.py" show plugin-development ;;
  validate|validate\ *)
    python3 "${CLAUDE_PLUGIN_ROOT}/skills/plugin-development/scripts/validate.py" ${ARGS#validate} ;;
  rules|rules\ *)
    "${CLAUDE_PLUGIN_ROOT}/bin/kaizen-iron-laws" list --json | head -80 ;;
  "")
    echo "[plugin-development] no args — the plugin-development skill is loaded directly via Skill(plugin:plugin-development). Pass: workflow | validate | rules" ;;
  *)
    echo "[plugin-development] unknown verb: $ARGS" >&2; echo "  valid: workflow | validate | rules" >&2 ;;
esac'`

## When to run `workflow`

When you're about to ship a NEW feature (new skill, new bin, new
hook, new MCP, new indexer) and want the TDD routine to walk you
through each stage with a machine-checkable gate per stage.

For incremental tweaks to an existing feature, prefer the targeted
verb (`validate`) — the full workflow is overhead for small changes.

## When to run `validate`

After staging a commit that touched plugin-original code, before
running `git commit`. Catches:
- iron-law violations (bin-wrapper-per-cli, hook-bypass-knob,
  plugin-manifest-permissions, sandbox-tests)
- canonical-feature-shape mismatches (missing slot, wrong path)
- soft-discipline issues (heavy deps without lazy-load, hardcoded
  routing instead of yaml)

## When to run `rules`

Quick reference dump — iron-laws registry as JSON. Pipe to `jq` to
extract specific rules: `kaizen plugin-development rules | jq
'.[] | select(.severity=="hard")'`.

## Pairing

- **Skill body** (`skills/plugin-development/SKILL.md`) — the
  authoritative prose; always-load via `Skill(plugin:plugin-development)`.
- **Schema** (`schemas/plugin-development/schema.yaml`) — the
  routine the workflow verb runs.
- **Validator** (`skills/plugin-development/scripts/validate.py`)
  — what the `validate` verb invokes.
- **Iron-laws registry** (`skills/iron-laws/domain/iron-laws.yaml`)
  — what the `rules` verb dumps.
