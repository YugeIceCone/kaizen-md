---
name: Phased-work commits use a consistent body template
description: When landing N items from a phased plan (Phase 4, roadmap, multi-PR refactor), each commit uses the same body shape — subject line / motivation / Files / env knobs / test baseline / refs. Atomic commits, one per item, identical structure so the log reads as a stable shape.
type: belief
confidence: 0.8
tags: [preference, commits, phased-work, conventional-commits]
sources_count: 1
freshness: stable
created: 2026-05-14
updated: 2026-05-14
---

# Phased-work commits use a consistent body template

For phased work landing N items from a roadmap / plan / migration,
use this exact commit-message shape — one commit per item, identical
body structure so `git log` reads as a coherent timeline:

```
<type>(<scope>): Phase <N> <id> — <one-line headline>

<2-3 sentences explaining what changed and why. Lead with the user
benefit / capability, not the file diff.>

Default off — gated on <env knob> + <dep>. <Migration / fallback
behavior in one sentence>.

Files
- <new module> (new) — <one-line role>
- <touched module> — <one-line delta>
- tests/test_<x>.py — <N tests; how many gated when>

Test baseline: <prev> to <new> (+<delta>); same 0 failures.

Env knobs (all opt-in, default off):
- KAIZEN_<X>_ENABLE=1
- <other knobs with defaults>

Refs: roadmap section <id>; Phase <N>: <M/N> complete
```

After all N items land, one cross-repo "tick the handoff" commit
updates the plan checkboxes + handoff progress bar in the
plan-owning repo.

## Why

Phased work generates parallel commits that share an audience: the
person reading the log a month later to understand the rollout.
Variable commit-message shapes force the reader to re-parse the
structure each time. A fixed template:

1. **Compresses the log.** Reader skims to "Test baseline:" line
   to see immediate impact; skims to "Refs:" line to see roadmap
   position. Body sections are predictable.
2. **Enforces the gates locally.** Every commit must state its env
   knobs, file scope, and test delta — surfaces if any of those
   are missing.
3. **Lets reviewers diff structure-vs-content.** When commit N+1
   skips a section, that's a signal something is off.

Proven during kaizen-md Phase 4 (2026-05-14) — 5 commits landed
with this shape (E9 / E10 / O8 / X4 / O5). `git log --oneline`
reads cleanly:

```
79d428c feat(summary): Phase 3 O5 — smart file-level summary
0e57f06 feat(migrate): Phase 4 X4 — code-lift engine + bin/kaizen-migrate
1257d11 feat(ts-chunk): Phase 4 O8 — tree-sitter universal symbol chunker
dfabf72 feat(colbert): Phase 4 E10 — ColBERT late-interaction sidecar
fa5653c feat(sparse): Phase 4 E9 — SPLADE sparse encoding + sparse_search
```

The headlines alone tell the story; the bodies fill in for anyone
who wants depth.

## How to apply

1. **TaskCreate first.** One task per item, one for the handoff
   commit. Surface progress as items land.

2. **Per-item flow.** Read context → implement → unit-test →
   integration-test (mocked) → smoke-verify → atomic commit using
   the template above.

3. **Test baseline arithmetic.** Always quote `<prev> to <new>
   (+<delta>)` so the reader sees the test growth without doing
   the math. Same `0 failures / 0 errors` line each time —
   absence is a signal something regressed.

4. **Cross-repo refs.** Use `Refs: roadmap section <id>` phrasing,
   NOT `plans/<date>-<slug>.md` path-references, when the plan
   file lives in a sibling repo. The kaizen pre-commit gate
   (post-fix `6c0cb15`) handles cross-repo paths, but the prose
   is also cleaner.

5. **Handoff commit at end.** Single commit in the plan-owning
   repo that ticks all N checkboxes + updates the progress bar +
   captures any session-trace notes worth carrying forward.

## Sections that are NEGOTIABLE

- "Env knobs" — drop entirely when the change has no user-facing
  knob (e.g. internal refactor).
- "Files" — drop when the diff is < 3 files with self-explanatory
  names.
- "Refs:" — required for phased work; optional for one-offs.

The "Test baseline" line is NOT negotiable. Always include it; it's
the single most useful piece of info for a future reader auditing
regressions.

## Anti-patterns

- ❌ Mega-commit landing 3 items together. Loses per-item revert
  granularity and makes the body unstructured.
- ❌ "WIP: Phase 4" then squash. Same problem — loses the
  per-item commit messages that have load-bearing context.
- ❌ Identical bodies copy-pasted with one find/replace. Each item
  has its own motivation and test delta; the structure is
  template but the *content* must be item-specific.

## Evidence

- source: kaizen-md commits fa5653c / dfabf72 / 1257d11 / 0e57f06
  / 79d428c (2026-05-14)
  description: 5 consecutive commits using this exact body shape
    during Phase 4 + O5 close-out. Reads as a coherent rollout
    in `git log`.
  date: 2026-05-14
