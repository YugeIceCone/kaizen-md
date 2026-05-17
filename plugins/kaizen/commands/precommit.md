---
name: precommit
description: "Dry-run the kaizen pre-commit gate against currently staged changes — without committing. Surfaces blocks, warns, and skill suggestions. Renamed from /kaizen:gate to disambiguate from /kaizen:gatekeeper (multi-axis audit aggregator). Triggers on \"dry-run the gate\", \"precommit check\", \"would this block my commit\", \"staged-diff gate\"."
argument-hint: "(no args — operates on staged diff)"
---

# Pre-commit gate (dry-run)

Runs the 9-check gate against currently staged changes without actually committing. Useful for checking what would block before running `git commit`.

If nothing is staged, the gate exits cleanly with a "nothing staged" note.

Run:

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/pre-commit.sh`

## Checks (in order)

1. **Compile barrier** — runs `compile_check_cmd` from `.kaizen.toml` (e.g. `cargo check --workspace --offline`)
2. **Conventional Commits prefix** — `feat|fix|refactor|docs|chore|test|perf|build|ci|style|revert`
3. **Structural change → architecture-log row** — if diff touches Cargo.toml/package.json/CLAUDE.md/crate boundaries, the staged diff must include a row in the architecture log
4. **Plan-file mention → checkbox tick** — if commit msg names `plans/<file>.md`, the staged diff must include a `- [x]` flip
5. **Pre-deletion gate** — `git rm` triggers a scan of brain `Notes/pref-no-deletions.md` + project memory `feedback_*delet*.md`; HARD BLOCK on match unless `KAIZEN_ALLOW_DELETE=1`
6. **CLAUDE.md no-sha / no-LOC** — rulebook must not carry volatile state
7. **Paired-test for new code** — SOFT warn if a new `.rs`/`.ts`/`.py` source file has no paired test
8. **Backlog drift** — `backlog.py verify` ensures `.md` matches `.json`
9. **Project-specific verify** — runs `verify_cmd` from `.kaizen.toml` if set

## Skill suggestions (printed alongside)

The gate routes to relevant skills when their domain is touched:

| Diff signal | Skill |
|---|---|
| Cargo.toml/package.json dep change | `onion-ddd-workflow` |
| New trait in domain | `onion-ddd-workflow` |
| New source file, no paired test | `tdd` / `superpowers:test-driven-development` |
| Large single-file diff (≥100 LOC) | `coding-skills:kiss` + `:separation-of-concerns` |
| Plan-file mention | `superpowers:executing-plans` |
| `git rm` detected | Remember plugin (belief scan) |
| Active workflow-routing routine in `state.json` | `workflow-routing` (advance via `/workflow`) |

## Override envs

- `KAIZEN_ALLOW_DELETE=1` — bypass pre-deletion gate (must be explicit user authorization)
- `KAIZEN_SKIP_TDD_CHECK=1` — silence the paired-test warn
- `git commit --no-verify` — emergency bypass; surface, never silently skip
