---
name: vibe-check
description: Run the vibe-coding discipline checklist against the currently staged diff. Combines `/kaizen:precommit` dry-run output with AI-specific checks (commit-message marker presence, dependency-allowlist rule consultation, scope-size advisory). Triggers on "vibe check", "is this safe to commit", "review my AI-generated diff".
---

# kaizen vibe-check

Runs the discipline gate over the staged diff with AI-coding specific augmentations on top of `/kaizen:precommit`'s 12 checks.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/vibe_check.sh`

## What it adds on top of `/kaizen:precommit`

`kaizen:gate` runs the 12 checks against staged. `vibe-check` additionally:

- Counts new exported functions vs new tests in the diff (heuristic). Warns on imbalance.
- Looks for new `use`/`import` statements referencing crates/packages NOT yet in `Cargo.toml` / `package.json`. Blocks if found (orphan import).
- Checks for `[AI]` marker / `AI-assisted` in `COMMIT_EDITMSG` (if running pre-commit). Suggests adding it.
- Surfaces matching pitfalls from `kaizen:plugin-pitfalls` based on diff patterns.

## What it doesn't do

- It's NOT a replacement for human review.
- It's NOT a substitute for `/kaizen:precommit` — invoke this AFTER the gate passes.
- It's NOT enforced (advisory). The actual block is `/kaizen:precommit` Check #13 (vibe marker, when enabled via env).

## Read the skill body first

Before running this command, load the canonical discipline:

```
/skill kaizen:vibe-check
```

The skill body documents: anti-patterns, safe prompt patterns, review checklist, governance/traceability, gradual adoption phases, and Iron Laws.

## Output

Markdown summary section to stderr (so it doesn't pollute pipes):

```
vibe-check on staged diff
  ✓ kaizen:precommit dry-run: green (12/12 pass)
  ! new exported fn count: 5 / new test count: 2 (imbalance: 3)
  ✓ no orphan imports
  ∘ commit msg marker: not yet (use [AI] in scope when committing)
  recommended: add 3 paired tests OR set KAIZEN_SKIP_TDD_CHECK=1 with justification
```
