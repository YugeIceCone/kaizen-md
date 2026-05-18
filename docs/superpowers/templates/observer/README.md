# Custom Observer — templates

Spec: `../../specs/2026-05-18-custom-observer-design.md`.

These four files seed `~/.claude/.kaizen/observer/` on first install.
The runtime (planned for clever-lama-mcp under `src/observer/`) treats
the user's copies as the live source of truth — re-reading both
schemas + rules from disk on every evaluation so the observer stays
drift-resilient against cache/API changes.

## Files

| File | Maps to | Owner |
|---|---|---|
| `event.schema.json` | `~/.claude/.kaizen/observer/schemas/event.schema.json` | C2 ingest validates against this; C5 sink uses it for structural checks |
| `rule.schema.json` | `~/.claude/.kaizen/observer/schemas/rule.schema.json` | C3 rule engine validates the rules.yaml entries against this |
| `rules.yaml` | `~/.claude/.kaizen/observer/rules.yaml` | C3 rule engine; user-editable; re-read per evaluation |
| `README.md` | (this file — docs only, not copied) | |

## First-install seed (planned `kaizen-observe init` behavior)

```bash
# Phase 2+ — the kaizen-observe CLI will provide this:
kaizen-observe init   # copies templates to ~/.claude/.kaizen/observer/
                       # safe to re-run; never overwrites existing files
                       # use --force to overwrite
```

## Why these files live in kaizen-md and not clever-lama-mcp

The runtime lives on clever-lama-mcp (per the dual-home pattern this
session validated with parallel-branches), but the **spec + schemas +
seed rules** are SSOT in kaizen-md. That matches the parallel-branches
convention: kaizen-md owns the canonical artifacts; clever-lama-mcp
implements one runtime against them.

When the runtime ships, it'll either:
- bundle the templates at install time (cp from a kaizen-md submodule), or
- fetch them from a known URL (the `$id` field in each schema points
  at `https://kaizen-md/templates/observer/...` for that).

The chosen mechanism gets nailed down in Phase 2.

## Editing rules

`rules.yaml` is intended to be **directly editable by the user**. The
observer reloads it on every evaluation, so changes take effect on the
NEXT tool call — no daemon restart, no cache invalidation, nothing.

This is the deliberate inverse of how `~/.claude/plugins/cache/...`
behaves (which is what burned us in 9b29d3d). The observer treats
disk as truth, always.

Validation: `kaizen-observe rules check` (Phase 2) will lint the file
against `rule.schema.json` + warn on unreachable rules + warn on
duplicate ids.
