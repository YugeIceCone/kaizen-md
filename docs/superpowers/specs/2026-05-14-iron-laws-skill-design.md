# Design — the `iron-laws` skill

## Status

**DRAFT 2026-05-14** — design approved in brainstorming; awaiting written-spec
review before `writing-plans`.

## Problem

The kaizen plugin's "iron laws" (the non-negotiable rules for plugin-original
development) live in `skills/plugin-development/domain/iron-laws.yaml` — a good
canonical YAML. But the system around them has two failure modes:

1. **Documentation drift.** The laws are *described and counted* in prose across
   `plugin-development/SKILL.md`, `CONTRIBUTING.md`, and `validate.py --help`.
   Those counts rotted: the header said "11-slot" / "13 iron laws" while the
   files actually held 13 slots / 21 laws. This is the textbook SSOT pitfall —
   "scattered duplicates become obsolete unless changes auto-propagate."

2. **Enforcement gap.** `validate.py::check_iron_laws()` reads the YAML but
   dispatches exactly one law (`no-modify-vendored`) — and that dispatch is a
   stub returning `[]`. Effectively **0 of 21 laws are machine-enforced** by the
   validator. The `detect:` predicates are documented but never run.

There is no single place that *owns* the iron laws as a managed system: source,
derived docs, and enforcement are scattered or absent.

## SSOT principles applied

Per the single-source-of-truth model (Wikipedia SSOT; "SSOT and problems with
implication", edunceputans):

- **One master, edited in one place.** `iron-laws.yaml` is the sole authoritative
  location. Nothing else holds law *content*.
- **Two valid derivation modes:**
  - **Reference** — consumers read the master live, never copy: the checker,
    `validate.py`, the pre-commit gate, the MCP server.
  - **Read-only copy (CQRS)** — generated, never hand-edited: `references/iron-laws.md`.
    `plugin-development`'s SKILL.md / CONTRIBUTING.md go further — they *link*,
    holding zero law content (pure reference).
- **Automatic propagation is mandatory.** The article's central warning is that
  derived data goes stale without an auto-propagation mechanism. Here that is the
  `codegen.py --check` drift gate, wired into CI and `refresh-cache.sh` — not
  optional, it is the component that makes the SSOT real.

## Decisions (locked in brainstorming)

| # | Decision |
|---|---|
| 1 | Goal = SoT + generated docs + enforcement (all three). |
| 2 | A **new `iron-laws` skill** owns the registry; `iron-laws.yaml` moves into it. `plugin-development` keeps `feature-shape.yaml` + `wiring-checklist.yaml` and *links* to the iron-laws skill. |
| 3 | Full enforcement surface: CLI + `validate.py` delegation + pre-commit gate + MCP server. |
| 4 | Classify all 21 laws; machine-check the mechanical subset (`enforcement: auto`), mark the fuzzy/session-state ones `enforcement: manual`. No false-positive-prone heuristics. |
| 5 | The registry is canonical for the 2 laws that overlap existing pre-commit gates — those gates become thin shims that defer to the checker by law ID. |

## Architecture

### Skill layout (canonical feature shape + workflow-skill SSOT pattern)

```
skills/iron-laws/
├── SKILL.md                          presentation — what iron laws are, how to add one
├── domain/
│   ├── iron-laws.yaml                THE MASTER (git mv'd from plugin-development/domain/)
│   └── schemas/iron-law.schema.json  JSON Schema validating iron-laws.yaml
├── application/
│   ├── _loader.py                    yaml → typed law objects, schema-validated, fail-fast
│   └── codegen.py                    renders references/iron-laws.md; --check = drift gate
└── references/iron-laws.md           GENERATED read-only copy (DO-NOT-HAND-EDIT header)
```

Backing code lands flat in `skills/workflow/scripts/` (per the canonical
"feature backing code is flat" rule):

- `_iron_laws.py` — core. Per-law `check_<id>()` functions + the dispatch
  registry. Reference-model consumer: loads `iron-laws.yaml` live, never copies.
- `iron_laws.py` — argparse CLI.
- `iron_laws_mcp.py` — FastMCP server (PEP-723 inline dep block).

Wiring (same-commit, per the iron laws themselves):

- `bin/kaizen-iron-laws` — shell wrapper.
- `commands/iron-laws.md` — `/kaizen:iron-laws` slash command.
- `tests/test_iron_laws.py` — loader, per-check, codegen, registry-integrity tests.
- `.mcp.json` entry `iron-laws` + `plugin.json` permission lines.

### Schema extension — every law gets an `enforcement` field

`iron-laws.yaml` gains one field per law:

```yaml
- id: hook-bypass-knob
  statement: "..."
  severity: hard
  enforcement: auto          # auto | manual
  check: hook_bypass_knob    # name of the check_* fn in _iron_laws.py — required iff enforcement: auto
  detect: "..."
  why: "..."
```

- `enforcement: auto` (~16 laws) — `_iron_laws.py` ships a `check_<check>()` function; runs in the checker.
- `enforcement: manual` (~5 laws) — listed + rendered + documented, never auto-run. The registry is honest about exactly what bites.

Proposed `manual` set (not mechanically checkable — fuzzy or needs session state):
`skill-cant-be-skipped`, `metrics-skip-check-before-merge`, `schema-driven-domain`,
`trace-coverage-all-tools`, `canonical-edit-path`. Final classification is a
plan-phase task; this is the starting proposal.

The `iron-law.schema.json` enforces: `enforcement` ∈ {auto, manual}; `check`
required iff `enforcement: auto`.

### Enforcement surfaces — all reference the master, none copy it

- **CLI** `kaizen-iron-laws`:
  - `list` — every law (id, severity, enforcement, one-line statement)
  - `show <id>` — full law record
  - `check [--staged | --all | --law <id>]` — run the `auto` checks, report findings (hard/soft)
  - `render` — regenerate `references/iron-laws.md` (delegates to `codegen.py`)
- **`validate.py` delegation** — `check_iron_laws()` stops being a stub: imports
  `_iron_laws` and runs the registry. The dead `_check_no_modify_vendored` stub
  is deleted.
- **Pre-commit gate** — `pre-commit.sh` gains one gate entry that runs
  `kaizen-iron-laws check --staged`. The two pre-existing overlapping gates
  (`claude-md-no-volatile-data`, `paired-tests`) are rewritten as shims that
  defer to the checker by law ID — each law defined + checked in exactly one place.
- **MCP** — `iron-laws` server exposes `iron_laws_list`, `iron_laws_show`,
  `iron_laws_check` so Claude can consult/check laws mid-session.

### The SSOT drift gate

- `codegen.py --check` exits non-zero if `references/iron-laws.md` differs from a
  fresh render. Wired into `.github/workflows/test.yml` (CI drift gate) and
  `refresh-cache.sh` (regenerate before sync) — identical to the workflow skill's
  pattern.
- `plugin-development`'s SKILL.md + CONTRIBUTING.md iron-law mentions become
  **links** to `skills/iron-laws/` — no embedded law content remains, so there is
  nothing left to drift. (`validate.py --help` was already de-counted.)

## Migration (the carve)

`iron-laws.yaml` moving is a file-set carve:

- `git mv skills/plugin-development/domain/iron-laws.yaml skills/iron-laws/domain/iron-laws.yaml`
- Update its readers: `validate.py`, `plugin-self-audit/`, `self_audit.py`,
  `_metrics.py`, `wiring-checklist.yaml`.
- `.kaizen/workflow/progress.md` row in the same commit (structural change).

## Sizing

New skill + moved master + new application layer + 3 backing scripts + wiring +
2 manifest edits (`plugin.json`, `.mcp.json`) + ~5 reader updates ⇒ **plan-file
tier**. The terminal step of this brainstorm is `writing-plans`, producing a
phased plan at `docs/kaizen/plans/2026-05-14-iron-laws-skill.md`.

## Testing

`tests/test_iron_laws.py` covers:

- **Loader** — `iron-laws.yaml` validates against `iron-law.schema.json`; fail-fast on bad input.
- **Per-check** — each `auto` law has a positive (violation detected) and negative (clean) case.
- **Codegen** — `references/iron-laws.md` render is idempotent (byte-identical on re-run); `--check` detects injected drift.
- **Registry integrity** — every law's `enforcement` ∈ {auto, manual} (exhaustive); every `auto` law has a matching `check_*` fn (no orphans); every `check_*` fn maps to a law (no dead checks).
- Tests sandbox via env vars; never touch real `~/.claude/`.

## Out of scope

- Merging `git-discipline.yaml`'s full pre-commit gate set into the iron-laws
  registry (brainstorm option 4 was declined). Only the 2 overlapping laws are
  reconciled.
- Moving `feature-shape.yaml` / `wiring-checklist.yaml` — they stay in
  `plugin-development`.
- Best-effort heuristic checks for the `manual` laws.
