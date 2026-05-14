---
name: iron-laws
description: The single-source-of-truth registry for the kaizen plugin's iron laws — the non-negotiable rules for plugin-original development. Use when adding or changing an iron law, checking code against the iron laws, asking "what are the iron laws", "is this an iron-law violation", "add an iron law", "iron-laws registry", or wiring iron-law enforcement into a gate or validator.
version: 1
---

# Iron Laws

The **iron laws** are the non-negotiable rules for kaizen-plugin-original
development (bin-wrapper-per-cli, hook-bypass-knob, no-modify-vendored, …).
This skill owns them as a managed **single source of truth**.

## The single source of truth

`domain/iron-laws.yaml` is the master. It is the **only** place a law's
content is edited. Every other surface either *references* it live or is a
*generated read-only copy* of it:

| Surface | Relationship to the master |
|---|---|
| `domain/iron-laws.yaml` | **master** — edited here, nowhere else |
| `references/iron-laws.md` | generated read-only copy (codegen; `DO-NOT-HAND-EDIT` header) |
| `application/_loader.py` | reference — loads + schema-validates the master |
| `_iron_laws.py` checker | reference — runs each law's check against live code |
| `validate.py`, the pre-commit gate, the MCP server | reference — call the checker |
| `plugin-development` SKILL.md / CONTRIBUTING.md | *link* to this skill — hold zero law content |

A law described or counted in prose anywhere else is drift waiting to happen
(see the stale "11-slot" / "13 iron laws" counts that motivated this skill).
The `codegen.py --check` drift gate is the automatic-propagation mechanism
that keeps the read-only copy honest.

## Each law's shape

```yaml
- id: hook-bypass-knob
  statement: "..."           # the rule, one line
  severity: hard             # hard (commit-blocked) | soft (warned) | info
  enforcement: auto          # auto (machine-checked) | manual (documented only)
  check: hook_bypass_knob    # name of the check_* fn in _iron_laws.py — required iff enforcement: auto
  detect: "..."              # the machine-checkable predicate, in prose
  why: "..."                 # rationale / the incident that produced the law
```

- **`enforcement: auto`** — `_iron_laws.py` ships a `check_<check>()` function;
  the checker runs it. Most laws.
- **`enforcement: manual`** — the law is fuzzy or needs session state (e.g.
  "session entered cwd without the skill loaded"). It is listed, rendered, and
  documented, but not auto-checked. The registry stays honest about exactly
  what bites.

The schema (`domain/schemas/iron-law.schema.json`) enforces the shape, and
requires `check` whenever `enforcement` is `auto`.

## Adding or changing a law

1. Edit `domain/iron-laws.yaml` — the master, and the only file that holds law content.
2. If `enforcement: auto`, add a matching `check_<check>(ctx)` function in
   `skills/workflow/scripts/_iron_laws.py` with a positive + negative test in
   `tests/test_iron_laws.py`.
3. Regenerate the reference: run the `iron-laws` codegen (the `kaizen-iron-laws`
   CLI `render` subcommand, or `application/codegen.py` directly).
4. Run the test suite. The registry-integrity test fails if a law's
   `enforcement`/`check` fields are inconsistent or a `check_*` function is
   orphaned.

## Surfaces

- **CLI** `kaizen-iron-laws` — `list` (every law), `show <id>` (one law),
  `check` (run the auto checks; `--staged` / `--all` / `--law <id>`),
  `render` (regenerate the reference).
- **`validate.py`** — the plugin-development validator's `check_iron_laws`
  delegates to the checker.
- **Pre-commit gate** — runs `kaizen-iron-laws check --staged`; the two laws
  that overlap pre-existing `git-discipline.yaml` gates are checked here by
  law id, so each law is defined and checked in exactly one place.
- **MCP** — the `iron-laws` server exposes `iron_laws_list`, `iron_laws_show`,
  `iron_laws_check` for mid-session use.

## Layout

```
skills/iron-laws/
├── SKILL.md                       this file
├── domain/
│   ├── iron-laws.yaml             the master
│   └── schemas/iron-law.schema.json
├── application/
│   ├── _loader.py                 schema-validated loader
│   └── codegen.py                 references renderer + --check drift gate
└── references/iron-laws.md        generated read-only copy
```

Checker + CLI + MCP backing code lives flat in `skills/workflow/scripts/`
(`_iron_laws.py`, `iron_laws.py`, `iron_laws_mcp.py`) per the canonical
feature shape.
