---
name: blueprint
description: The `kaizen-blueprint` CLI — 1-roundtrip read/mutate/validate over blueprint-format plan JSON files. Use when an agent needs to inspect or mutate a plan stored at `.kaizen/docs/<YYYY-MM-DD>-<topic>/plan.json` without hand-editing the JSON. Memory-cached metadata makes the common "scan-then-pick" flow truly 1 call. Pairs with kaizen:planner (the chain orchestrator that writes blueprints) and the blueprint.schema.json (the canonical artifact format). Triggers on "show plan item", "list plan items", "plan scan", "mark task done", "set plan status", "validate blueprint", "kaizen-blueprint", "1-roundtrip plan op".
metadata:
  version: "1.0"
  origin: kaizen-md 2026-05-20 (gap surfaced by the unify-artifact-generation plan; built to honor the 1-roundtrip contract in decision 28)
---

# blueprint — 1-roundtrip plan management CLI

Hand-editing plan JSON via the Edit tool is error-prone (trailing
commas, broken DAG, no schema check, non-atomic writes). This CLI
collapses each common operation to ONE call that reads, mutates,
validates, and atomic-writes.

## When to use

- Agent needs the next pending task in a plan → `kaizen-blueprint show <N>`
- Status flip after completing work → `kaizen-blueprint set-status --id X --status shipped`
- Scan-before-pull (which item to fetch?) → `kaizen-blueprint scan`
- After editing the plan file by hand, want to validate → `kaizen-blueprint validate`

## When NOT to use

- Authoring fresh prose into an item's `content` field — easier via
  Read + Edit tool (the CLI doesn't replace long-form authoring).
- Bulk restructuring (renumbering all ids, swapping kinds at scale)
  — Read + Write is better; the CLI's per-op verbs would be N calls.

## Surface (every verb is 1-roundtrip atomic)

```bash
# Read
kaizen-blueprint show [file] [N]            # items[N] by index
kaizen-blueprint show [file] --id X         # by item id
kaizen-blueprint show [file] --id X --subtree=H   # + linked children
kaizen-blueprint show [file] --md           # whole plan as markdown
kaizen-blueprint list [file]                # compact scan (cache-hit)
kaizen-blueprint scan                       # pure cache hit, no source read

# Cache management
kaizen-blueprint state                      # which plans are cached, which is active
kaizen-blueprint state --clear              # drop all
kaizen-blueprint state --clear <path>       # drop one

# Validate
kaizen-blueprint validate [file]            # schema + DAG; exit 0/1

# Mutate (atomic-write via _atomic)
kaizen-blueprint set-status [file] --id X --status active|shipped|...
kaizen-blueprint set-task-status [file] --task-id 04.1 --status completed|...

# Author
kaizen-blueprint init <file> --topic T [--project P]   # from template
kaizen-blueprint create [args...]                       # legacy one-shot generator
```

## Active-plan inference

Every read auto-caches and marks the named plan ACTIVE. Subsequent
calls can OMIT the file argument:

```bash
# First call: populates cache + marks active
kaizen-blueprint list .kaizen/docs/plans/foo.json

# Subsequent calls: 1-roundtrip with no path
kaizen-blueprint scan              # cache only, no source read
kaizen-blueprint show 5            # items[5] of active plan
kaizen-blueprint show --id 04
kaizen-blueprint set-status --id 04 --status shipped
```

Cache is at `.kaizen/cache/blueprint-state.json`; mtime+size invalidated
on source-file change. Override via `KAIZEN_BLUEPRINT_STATE=<path>`.

## Smart positional

`show <N>` (numeric) → treated as INDEX of active plan when no
file-like string is supplied. `show <path/to.json>` (path) → treated as
file. Disambiguated by presence of `/` or `.` in the argument.

## Atomicity guarantees

Mutating verbs (`set-status`, `set-task-status`, `init`) route through
`scripts/io/_atomic.atomic_write_json`:

1. Read source (parse JSON)
2. Mutate in-memory
3. Optionally schema-validate (`--validate` flag)
4. Write tempfile in same directory
5. `os.replace` (atomic on POSIX + Windows since Python 3.3)

If any step fails, the source file is untouched.

## Cross-references

- `kaizen:planner` — the chain orchestrator that WRITES blueprints
- `.kaizen/docs/templates/blueprint.schema.json` — the artifact format
- `.kaizen/docs/templates/blueprint-template.json` — fillable scaffold
- `.kaizen/docs/templates/blueprint-editing-guide.md` — manual edit patterns
- `scripts/io/_atomic.py` — the underlying atomic-write primitive
- `scripts/blueprint/_blueprint.py` — pure-core read/mutate helpers
- `scripts/blueprint/_state.py` — memory-cache state file

## Anti-patterns

- **Re-implementing reads in shell** (`cat plan.json | jq '.items[5]'`) —
  use `kaizen-blueprint show 5` instead. Same result, validates the
  parse, populates cache for the next call.
- **Non-atomic edits** (`cat | jq > tmp; mv tmp plan.json`) — use
  `set-status` / `set-task-status` so a failed validation leaves the
  file untouched.
- **Skipping `validate`** after hand-edits — every Edit-tool mutation
  to a blueprint should be followed by `kaizen-blueprint validate`.
  Cheap call (parse + jsonschema); catches DAG breakage immediately.
