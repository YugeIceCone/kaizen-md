---
name: kaizen-schema
description: Catalog + dispatch hub for the kaizen-md plugin's schema surface — 49 JSON Schemas + 32 domain/*.yaml configs + 14 workflow routine schemas. Tells you where each schema lives, how to validate against it, when to write a new one vs extend existing. Pairs with iron-laws (rules layer) and plugin-development (feature shape). Triggers on "kaizen schema", "validate yaml", "JSON schema for X", "schema-driven kaizen feature", "where's the schema for Y", "kaizen-md domain yaml", "add a schema", "schema audit".
---

# kaizen-schema — Plugin Schema Surface Catalog

## ⚠ Iron Law — read in full

Skip nothing. The 3-tier schema taxonomy (workflow routines / per-skill
domain / per-skill data) only holds together end-to-end. Picking the
wrong tier creates parallel implementations + drift.

## Three schema tiers

### Tier 1 — workflow routine schemas (orchestration)

Drive `/workflow schema=<name>` multi-stage routines. Each schema
declares stages, gates, transitions.

Location: `plugins/kaizen/schemas/<routine>/schema.yaml` (plugin-shipped)
or `~/.claude/.kaizen/schemas/<routine>/schema.yaml` (user-installed extensions).

Plugin-shipped routines (authoritative list: `ls plugins/kaizen/schemas/`):

| Routine | When |
|---|---|
| `kaizen-default` | Default workflow |
| `audit` | Periodic comprehensive audit |
| `boy-scout` | Boy-scout inline cleanup pattern |
| `consolidate` | Slash / module consolidation routine |
| `debug-with-pdb` | Debug-driven workflow |
| `fix-bug` | Bug-fix routine |
| `harden` | Hardening + verification |
| `mcp-build` | New MCP server build |
| `migrate` | Migration routine |
| `minimalist` | Smallest-possible flow |
| `plugin-development` | 8-stage TDD plugin-dev routine |
| `ralph-loop` | Self-correcting loop |
| `refactor` | Refactor routine |
| `review` | Diff-time review routine |
| `shim-and-sweep` | Shim + sweep pattern |
| `spec-driven` | Spec → impl routine |

User-installed extensions (examples — actual set is per-user):

| Routine | When |
|---|---|
| `onion-tdd-strict` | Onion-DDD + TDD discipline (Persona Directive) |

Validation: `kaizen-schema validate <name>` (or `workflow_runner.py show <name>`).

### Tier 2 — per-skill domain configs (declarative behavior)

Each skill that's schema-driven keeps a `domain/` dir with YAML
configs (and optionally JSON Schemas to validate them). Live count
via `find plugins/kaizen/skills -path '*/domain/*.yaml'`.

Examples:
- `schemas/iron-laws/iron-laws.yaml` — the iron-law registry
- `schemas/brain/routing.yaml` — capture-flow routing rules
- `schemas/brainstorming/brainstorm-rubric.yaml` — scoring rubric
- `schemas/plugin-development/feature-shape.yaml` — canonical feature slots
- `schemas/plugin-development/intake-checklist.yaml` — which skills to load per work-type
- `schemas/chatlog/examples.yaml`
- `schemas/agent-formatting/dispatch-rubric.yaml`

These yamls are SSOT for their domain. Code (Python loaders, generators)
reads them; markdown explains them. Don't duplicate yaml content in
the SKILL.md body — link/cite it.

Validation: typically a per-skill loader (e.g. `_loader.py`) +
JSON Schema in `domain/schemas/<name>.schema.json`.

### Tier 3 — per-skill data schemas (runtime types)

JSON Schemas that validate runtime data structures the skill produces
or consumes. Live count via `find plugins/kaizen -name '*.schema.json'`.

Examples:
- `schemas/brain/schemas/memory-entry.schema.json` — auto-memory entry shape
- `schemas/brain/schemas/note.schema.json` — brain Note frontmatter
- `schemas/brainstorming/schemas/idea.schema.json` — brainstorm result shape
- `schemas/chatlog/schemas/triggers.schema.json`
- `skills/parallel-branches/schemas/{chunk,master-plan,merge-action,chunk-ledger,backlog-fragment,perms-fragment,progress-fragment}.schema.json`
- `schemas/workflow/schemas/architecture-log-row.schema.json`
- `schemas/kaizen-config.schema.json` — plugin TOML config shape

Validation: `jsonschema` Python library (used in tests + at runtime).

## Where to add a new schema

| Need | Tier | Location |
|---|---|---|
| New `/workflow` routine | 1 | `schemas/<routine>/schema.yaml` |
| New declarative config for a skill | 2 | `skills/<skill>/domain/<config>.yaml` |
| New JSON Schema for skill's runtime data | 3 | `skills/<skill>/domain/schemas/<thing>.schema.json` |
| Cross-skill config schema | mixed | `schemas/<name>.schema.json` |

## Coverage + audit surface

- `kaizen-schema-coverage` — checks every domain/*.yaml has a paired
  `.schema.json` for validation. Surfaces uncovered configs.
- `kaizen-schema-load-coverage` — checks every JSON Schema has at
  least one consumer (Python loader or test).
- `kaizen-gatekeeper check --staged` — runs both as part of the pre-commit gate.

## Anti-patterns

- **Parallel yaml + Python data structure** — yaml IS the SSOT. Code
  loads it; don't replicate.
- **JSON Schema without a loader** — orphaned schemas don't validate
  anything. Either wire them up or remove (with auth).
- **Per-skill `domain/` mixed with non-yaml code** — keep `domain/`
  for declarative data; put loaders in `application/` or `scripts/`.

## Pairing with siblings

| Sibling | Relationship |
|---|---|
| `iron-laws` | iron-laws.yaml IS a tier-2 schema-driven config. kaizen-schema knows about it. |
| `plugin-development` | feature-shape.yaml + intake-checklist.yaml are tier-2 configs that plugin-development consumes. |
| `decision-rubric` | rubric YAML format reuses the tier-2 pattern with first-match-wins semantics. |
| `schema-driven-cli` | the cli wrapper around BucketWalker — consumes tier-2 rubric yamls. |

## Triggers (when to load this skill)

- About to add a new schema and unsure which tier
- Validating a yaml/json config and unsure which schema applies
- Auditing the plugin's schema surface (drift, orphans, gaps)
- Understanding the schema-driven pattern in any skill

## DON'T load when

- You're editing CODE that loads a schema (load the loader's skill)
- You're authoring a NEW skill (load `Skill(plugin-development)` —
  it covers schema slots in the feature shape)
