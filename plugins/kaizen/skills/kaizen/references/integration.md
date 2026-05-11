# Skill weaving — concrete invocation examples

Each row of the weaving table in `SKILL.md` PART 5, expanded with the
exact failure mode the gate is catching and the agent-facing
invocation that fixes it.

## 1. Cargo.toml / package.json dep change → `onion-ddd-workflow`

**Gate signal:**
```
! Skill to consider:
  Dep change → invoke skill: onion-ddd-workflow (check dep direction, structural-lint authoring)
```

**Why:** new dep can invert a layer arrow (e.g. `tokio` added to a domain crate's `Cargo.toml` puts an async runtime in the Domain layer — P0 by Onion's One Rule).

**Agent invocation:**
```
Load skill: onion-ddd-workflow
→ Apply PART 2 audit lens to the staged diff
→ If P0/P1 finding: PART 3 plan + execute before re-committing
```

## 2. New trait/interface in inner layer → `onion-ddd-workflow`

**Gate signal:** detected via `+pub trait` / `+pub interface` in a path matching the project's domain glob.

**Agent invocation:**
```
Load skill: onion-ddd-workflow
→ Apply PART 1 "Decision rules: where does this code go?"
→ If trait lives in Domain: author onion-no-redefine-<port>.yml lint
   rule in same commit (PART 3 §Codifying boundaries)
```

## 3. New `.rs` / `.ts` / `.py` source file with no paired test → `tdd`

**Gate signal (SOFT/WARN):**
```
! new file crates/foo/src/bar.rs has no paired test (load skill: tdd)
```

**Agent invocation:**
```
Load skill: tdd  (or superpowers:test-driven-development)
→ Phase 2 RED: write failing tests in crates/foo/src/bar.rs's
  #[cfg(test)] mod tests OR crates/foo/tests/bar.rs
→ Re-stage; warning clears
```

## 4. Diff > 100 LOC in a single file → `coding-skills:kiss` + `coding-skills:separation-of-concerns`

**Gate signal:**
```
! Skill to consider:
  Large single-file diff → invoke skill: coding-skills:kiss + coding-skills:separation-of-concerns
    crates/cli/src/repl.rs (+340 -80)
```

**Why:** 100+ LOC in one file usually signals a missing extraction.

**Agent invocation:**
```
Load skills: coding-skills:kiss, coding-skills:separation-of-concerns
→ KISS checklist: any 3+ levels of nesting? any "and"-conjoined functions?
→ SoC checklist: does this file mix parsing + business + presentation?
→ Extract a helper if either fails; re-commit
```

## 5. New abstraction (trait + 1 impl, no second consumer) → `coding-skills:yagni`

**Gate signal:** heuristic detection of new `pub trait Foo` whose grep across staged + unstaged files returns exactly one `impl Foo`.

**Agent invocation:**
```
Load skill: coding-skills:yagni
→ Is there a concrete second consumer planned in BACKLOG.md ## Next up?
→ If no: collapse the trait, use the concrete type directly. Re-commit.
→ If yes: keep the trait; add YAGNI-justification note in commit body.
```

## 6. Two parallel trait defs across crates → `coding-skills:dry`

**Gate signal:** detected via grep for `pub trait <Name>` returning ≥2 matches in different crates.

**Agent invocation:**
```
Load skill: coding-skills:dry  (then onion-ddd-workflow)
→ Lift the canonical trait to the inner-most layer; outer crates re-export
→ Author onion-no-redefine-<port>.yml lint to prevent regression
```

## 7. Plan-file mention in commit msg → `superpowers:executing-plans`

**Gate signal:**
```
✗ plan plans/2026-05-11-foo.md mentioned but no '+- [x]' flip staged
```

**Agent invocation:**
```
Load skill: superpowers:executing-plans
→ Open the plan; find the phase that landed in this commit
→ Edit '- [ ]' to '- [x]'; stage the plan file; re-commit
→ If phase didn't actually land, remove the plan mention from the commit msg
```

## 8. `git rm` detected → memory / Remember plugin

**Gate signal:**
```
✗ deletion staged + matching deletion-prevention belief(s) found:
   → ~/.claude/brain/Notes/pref-no-deletions.md
   → ~/.claude/projects/<slug>/memory/feedback_borg_loop_no_deletions.md
Override: KAIZEN_ALLOW_DELETE=1 git commit ...
```

**Agent invocation:**
```
1. STOP. Surface the deletion + belief to the user.
2. Quote the belief's "## How to apply" section in your response.
3. Ask for explicit authorization with the override env var visible.
4. Only after user confirms: KAIZEN_ALLOW_DELETE=1 git commit ...
```

This is the persona directive made operational. Never bypass silently.

## 9. Architecture-log row added → `coding-skills:convention-over-configuration`

**Gate signal:** detected via `+| YYYY-MM-DD |` row pattern in the architecture log.

**Agent invocation:**
```
Load skill: coding-skills:convention-over-configuration
→ Match column count + delimiter style + scope-tag conventions
   of existing rows. Don't invent.
→ Check ΔLOC convention against project's documented rules
```

## 10. Branch ready to merge → `superpowers:finishing-a-development-branch`

**Not a gate signal** — surfaced when the user asks "is this ready?" or
when staging the final commit of a branch.

**Agent invocation:**
```
Load skill: superpowers:finishing-a-development-branch
→ Walk the structured completion checklist (PR vs merge vs cleanup)
```

# Memory plugin integration points

## At session start

The brain's `Persona.md` is auto-loaded. The kaizen skill expects
to find:

- `## Top Beliefs` — for the pre-deletion gate to scan
- `[[Notes/pref-no-deletions]]` (or equivalent) — the canonical
  deletion-prevention belief

If neither exists, the pre-deletion gate degrades to a soft warn (still
catches `git rm` but doesn't block without an explicit user-curated
belief to cite).

## At commit time

When the gate runs:
1. Reads `<brain>/Persona.md` to count current Top Beliefs
2. If `Notes/pref-no-deletions.md` exists AND staged diff has deletions
   → BLOCK (Check #5)
3. If project memory dir has `feedback_*delet*.md` → BLOCK
4. Optionally injects `(applies Notes/<top-belief>.md)` into commit msg
   when the diff touches files matching that belief's scope

## Post-commit

(Future) — for landmark commits (new crate, retired module, locked
rule), append a draft note to project memory for `/remember:process`
to pick up on the next session-processing run.

# Anti-patterns

| Anti-pattern | What it produces | Fix |
|---|---|---|
| Skipping the gate with `--no-verify` because it's slow | Architectural rot accumulates silently | Profile the slow check (usually `cargo check`); tune via `--offline` or per-package; never bypass |
| Adding a Cargo.toml dep without invoking onion-ddd-workflow | Hidden dep-direction inversion | Make the suggestion non-skippable: hook BLOCKS until the dep change has a one-line justification in the commit body |
| Plan-file mention but ticking the checkbox in a follow-up commit | Two-commit dance for what should be atomic | The CLAUDE.md "no amend" rule applies: roll the tick into the same commit BEFORE running `git commit` |
| Using BACKLOG.md for genuinely 5-phase work | Decisions get lost, dependency ordering ambiguous | Use the plan-file escape clause. SKILL.md PART 2 §"When NOT to use BACKLOG.md" |
| `git rm` after `KAIZEN_ALLOW_DELETE=1` without user OK | Silently bypassed the belief that exists for a reason | The override env var only fires when user typed it. As an agent, never set it yourself — surface the block, get authorization, then quote the variable in your response so the user runs the commit |
