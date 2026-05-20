---
name: blueprint
description: "1-roundtrip CLI over .kaizen/docs/<YYYY-MM-DD>-<topic>/plan.json. Read / mutate / validate / atomic-write per call. Verbs - show | list | scan | state | validate | set-status | set-task-status | add-item | add-task | chunk | dispatch | init | create. Triggers - 'show plan item', 'mark task done', 'next chunk', 'scan plan', 'kaizen-blueprint'."
argument-hint: "show <N> | list | scan | chunk --list-id X | set-task-status --task-id Y --status completed | add-item --kind K --title T | ..."
allowed-tools: ["Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-blueprint:*)", "Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/blueprint/blueprint.py:*)", "Bash(bash ${CLAUDE_PLUGIN_ROOT}/scripts/blueprint/dispatch.sh:*)"]
---

# /kaizen:blueprint

!`bash -c 'exec ${CLAUDE_PLUGIN_ROOT}/bin/kaizen-blueprint ${ARGUMENTS:-scan}'`

## Verbs

| Verb | Use |
|---|---|
| `show [file] [N]` | items[N] (positional, by array index) of the active or given plan |
| `show [file] --id X` | one item by id |
| `show [file] --id X --subtree[=H]` | item + linked children (H hops, default 1) |
| `show [file] --md` | whole plan as markdown |
| `list [file]` | compact one-row-per-item scan (cache-hit when fresh) |
| `scan` | pure cache rollup of active plan — no source read |
| `state` | inspect / `--clear` the cache index |
| `validate [file]` | schema + DAG check; exit 0/1 |
| `chunk [file] --list-id X` | apply chunking (default 3-task parent batches; `--subagents` for D2 rubric) |
| `dispatch prepare/finalize` | wrap subagent dispatch — see `bin/kaizen-blueprint dispatch --help` |
| `set-status [file] --id X --status S` | atomic item-status flip |
| `set-task-status [file] --task-id Y --status S` | atomic task-status flip |
| `add-item [file] --kind K --title T [--parent P]` | append item; auto-pick id; auto-link parent |
| `add-task [file] --to <list-id> --subject S` | append task to a task-list |
| `init <file> --topic T` | create from template |
| `create [args...]` | legacy one-shot generator |

## 1-roundtrip + active-plan inference

Every read auto-caches metadata at `.kaizen/cache/blueprint-state.json`
and marks the named plan **active**. Subsequent reads can omit the
file argument:

```bash
/kaizen:blueprint list .kaizen/docs/plans/foo.json   # populate cache
/kaizen:blueprint scan                                # cache only
/kaizen:blueprint show 5                              # items[5] of active
/kaizen:blueprint set-status --id 04 --status shipped
```

Cache is mtime+size invalidated. Override location via
`KAIZEN_BLUEPRINT_STATE=<path>`.

## Why a slash

Hand-editing plan JSON (cat / jq / mv) is non-atomic + skips
validation + can break the DAG silently. The CLI collapses each
common op to one call that reads / mutates / validates / atomic-writes.
The slash makes that surface discoverable from `/kaizen:*`.

## Pairs with

- `/kaizen:planner` — the chain orchestrator that WRITES blueprints
- `.kaizen/docs/templates/blueprint.schema.json` — canonical schema
- `.kaizen/docs/templates/blueprint-template.json` — fillable scaffold
- `.kaizen/docs/templates/blueprint-editing-guide.md` — manual-edit patterns
