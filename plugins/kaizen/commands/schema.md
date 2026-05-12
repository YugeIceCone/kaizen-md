---
name: schema
description: Inspect declarative workflow schemas (v1.14.0+). Schemas live as yaml in `.kaizen/workflow/schemas/<name>/` (project, post-v1.22), `~/.claude/.kaizen/schemas/<name>/` (user), or the plugin's built-ins (minimalist, kaizen-default, spec-driven). Pair with `/workflow schema=<name>` to run a schema-driven routine.
---

# kaizen schema

Inspect / validate workflow schemas. A schema is a declarative yaml file declaring artifacts + their `requires:` dependencies + an `apply:` gate, used by `/workflow schema=<name>` to drive a topo-ordered routine without modifying the plugin.

!`python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow-routing/scripts/workflow_runner.py ${ARGUMENTS:-list}`

## Subcommands

- (no args) or `list` → list every schema across project + user + built-in tiers
- `show <name>` → print the parsed schema as JSON
- `validate <name>` → structural + DAG check (cycles, unknown `requires:` refs, bad `apply.gate`)
- `stages <name>` → print topo-ordered stage ids, one per line (the same output `/workflow schema=<name>` consumes)
- `artifact <name> <id>` → print one artifact's dict as JSON, including its description prose
- `branches <name> <id>` (v1.15.0+) → print the artifact's `branch_high` / `branch_medium` / `branch_low` paths as JSON. As of **v1.17.0** this is also wired into the workflow.sh state machine — see below.

## Runtime branching (v1.17.0+)

After completing a stage that declares `branch_*` fields, the agent can splice the workflow's stage list to match the chosen path:

```bash
workflow.sh advance design "design done; confidence=medium"
workflow.sh branch  design medium
# → state.stages[current:] replaced with branch_medium's list
# → next stage advances accordingly
# → branch_decisions audit trail recorded in state.json
```

Validation: `branch <stage> <key>` requires (a) a schema-driven workflow (`schema=NAME` passed at init), (b) `<stage>` matches the most-recently-completed stage, (c) `<key>` exists in the schema's `branch_*` keys for that artifact. Invalid combinations exit non-zero with a clear message.

## Built-in schemas (v1.14.0)

| Schema          | Stages                                                                             | Use when                                              |
|-----------------|------------------------------------------------------------------------------------|-------------------------------------------------------|
| `minimalist`    | specs → tasks                                                                      | Low-risk solo / hobby work; G/W/T or EARS acceptance  |
| `kaizen-default`| explore → research → analyze → plan → tasks → execute → review → validate          | Medium-risk multi-step work (mirrors hardcoded route) |
| `spec-driven`   | analyze → design → (decisions, tasks) → implement → validate → reflect → handoff   | Higher-risk: EARS requirements + Decision Records     |

## Run a schema

```bash
/workflow schema=spec-driven add a CSV importer feature
# initializes .kaizen/workflow/state.json with routine=schema:spec-driven and
# the 8 topo-ordered stages from spec-driven/schema.yaml.
```

## Author your own schema

1. Pick a tier:
   - Project-scoped (versioned with the repo): `.kaizen/workflow/schemas/<name>/schema.yaml`
   - User-scoped (across all projects):       `~/.claude/.kaizen/schemas/<name>/schema.yaml`
2. Copy `<plugin>/schemas/minimalist/schema.yaml` as a starter.
3. Validate: `/kaizen:schema validate <name>`
4. Run: `/workflow schema=<name> <prompt>`

## Why declarative?

- **User-extensible.** Add a routine without editing the plugin source.
- **Project-extensible.** Schema lives in the repo alongside code, version-controlled.
- **Composable.** `requires:` is a DAG — insert / re-order phases by editing yaml.
- **Inspectable.** Agents read the yaml to know what a routine will produce, before running.

See `docs/workflow-schemas-research.md` in the plugin for the design rationale and the strangler-fig migration path from hardcoded routines.
