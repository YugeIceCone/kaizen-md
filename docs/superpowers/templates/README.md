# docs/superpowers/templates/ — durable kits + templates

This dir holds DURABLE cross-session reference material. Distinct from
session bundles (`<date>-<project>-<sid>/`) which are time-scoped.

## What's here

### 1. `parallel-branches/` — the multi-chunk dispatch kit

11 docs + 8 schemas + 1 decision rubric + worked examples. The
canonical answer for "I have a plan with N independent units of work
that can run in parallel subagents."

- **Entry:** [parallel-branches/INDEX.md](parallel-branches/INDEX.md)
- **Runtime:** clever-lama-mcp/src/parallel_branches/ (7 modules;
  Phase 1 + Phase 2 partial — see INDEX runtime-status table)
- **Status:** kit-driven workflow; preferred for ≥3-chunk plans.

### 2. `observer/` — the custom-observer schemas + seed rules

4 files seeding `~/.claude/.kaizen/observer/` for the tool-call
observer (capture hook + rules engine + query CLI). The schemas
define the event + rule shapes; rules.yaml ships 6 seed rules
including the canonical `cache-drift-detect`.

- **Entry:** [observer/README.md](observer/README.md)
- **Spec:** [../2026-05-18-kaizen-md-6ebbb7cb/spec-custom-observer-design.md](../2026-05-18-kaizen-md-6ebbb7cb/spec-custom-observer-design.md)
- **Runtime:** clever-lama-mcp/src/observer/ (ingest + rules) +
  kaizen-md/plugins/kaizen/hooks/claude/posttool-observer-capture.sh
- **Status:** Phase 0-2 + 1.5 + 1.6 shipped.

### 3. `chunk-plan-template.md` — prose chunk-plan template (loose)

Schema-free predecessor of the parallel-branches kit. A single
markdown template covering the 4-section per-chunk shape (Guide /
Task list / Plan / TDD code chunks) + two footers (Done when /
Dispatch).

- **Entry:** [chunk-plan-template.md](chunk-plan-template.md)
- **Status:** preserved for compatibility with older plans + as the
  human-readable starting point when schema validation isn't needed.
  For new plans, prefer the parallel-branches kit (above).

## Why kits live here (and not in session bundles)

Kits are LONG-LIVED reference material that multiple sessions consume.
Session bundles (sibling dirs under `docs/superpowers/`) are TIME-
SCOPED artifacts (one date + project + sid). The split keeps:

- Durable knowledge addressable by topic (here)
- Session work addressable by time + project (`<date>-<project>-<sid>/`)
- Templates discoverable as one canonical set (this dir)

## Adding a new kit

Conventions to follow:

1. **Top-level entry doc** — name it `INDEX.md` (preferred — matches
   parallel-branches/) OR `README.md` (acceptable — matches observer/).
   Just pick one; don't ship both.
2. **Schemas in `schemas/`** if the kit produces structured artifacts.
3. **Worked examples in `examples/`** with one example per ON_DISK_LAYOUT
   mode if multiple exist.
4. **Cross-reference the runtime** when the kit pairs with a runtime
   module in another repo (mirrors the dual-home convention validated
   for parallel-branches).
5. **Append a row to this README** under "What's here" so the umbrella
   stays current (per the `shim-and-sweep` iron-law).

## Boy-Scout (D10 from parallel-branches/DISCIPLINES.md)

When editing ANY doc here, fix any discipline violations encountered
in the same pass — don't leave them for later.
