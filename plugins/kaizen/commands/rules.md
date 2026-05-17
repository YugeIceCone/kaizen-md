---
name: rules
description: Inspect, validate, or generate templates for brain-sourced kaizen rules. Rules live as Markdown notes in <KAIZEN_BRAIN_DIR>/Notes/ (default ~/.claude/.kaizen/brain/Notes/) with a `kaizen:` frontmatter block, owned end-to-end by the kaizen plugin. (Bin wrapper is `kaizen-rules` — old `/kaizen:rule` slash is a deprecation alias.)
---

# kaizen rules

Inspect / validate / generate brain-sourced kaizen rules. Rules let you customize gate behaviour without touching plugin code: deletion allowlists, check-severity overrides, custom-pattern detectors.

!`python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/rules.py ${ARGUMENTS:-list}`

## Subcommands

- (no args) or `list` → list all kaizen rules across the brain
- `show <name>` → print one rule as JSON
- `deletion-allowed <path>` → check if a path is allowlisted for deletion (returns `yes (<rule-name>)` / `no`)
- `severity <check_id>` → check if a gate check has a severity override (`skip` / `warn` / `block` / `default`)
- `custom-patterns` → print all custom-pattern rules as JSON
- `validate` → schema-check all rules; exits 1 on any error
- `template <rule_type>` → print a brain-note template for the given rule type. Pipe to `/kaizen:remember` or copy into a new note.

## Rule types

| Rule type | What it does |
|---|---|
| `deletion-allow` | Whitelist `path_glob` for `git rm` (skips the pre-deletion belief scan) |
| `check-severity` | Override one of the 10 gate checks: `skip` / `warn` / `block` |
| `custom-pattern` | Run a regex over the staged diff; emit warn or hard-block on hit |

See `kaizen:behaviour-config` skill (`/kaizen:help` lists it) for the full schema, examples, and trigger phrases.

## How to author a rule

1. **Get a template:**
   ```
   /kaizen:rules template deletion-allow
   ```
2. **Save as a brain note:**
   `<KAIZEN_BRAIN_DIR>/Notes/kaizen-<your-rule-name>.md` (default `~/.claude/.kaizen/brain/Notes/`; any name works — the plugin discovers all `.md` files with a `kaizen:` frontmatter block).
3. **Validate:**
   ```
   /kaizen:rules validate
   ```
4. **Refresh:** next gate run picks up new rules automatically — no plugin restart needed.

## Why brain-sourced?

- **Survives across projects** — set once, applies everywhere kaizen runs.
- **Survives across sessions** — kaizen owns the brain end-to-end; persistence is via the file tree under `<KAIZEN_BRAIN_DIR>`.
- **Single source of truth** — no plugin-local config sprawl; rules are user preferences, owned by the brain.
- **Reversible** — rename `<rule>.md` → `<rule>.md.disabled` to disable (same trick `/kaizen:disable-dupes` uses for skills).
