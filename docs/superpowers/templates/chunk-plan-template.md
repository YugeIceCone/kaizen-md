# Chunk-plan template (v2)

Reusable template for multi-project / multi-turn / subagent workflows.

A plan is broken into **N independently-dispatchable chunks**. Each chunk follows a strict **4-section** internal shape so a fresh subagent can pick it up cold:

1. **Guide** — orientation: where to work, what to read first, which skills to load, which decisions already exist.
2. **Task list (checklist)** — `- [ ]` checkboxes the subagent ticks as it works. TaskCreate-ready.
3. **Plan** — file inventory table: every Create/Modify/Delete with its responsibility.
4. **TDD code chunks** — per-item RED test snippet → GREEN impl outline → commit message. Strict order. No item ships without all three.

Two footers per chunk (outside the 4-section structure): **Done when** (verification gate) and **Dispatch** (paste-ready `Agent()` call).

---

## Plan header (top of file)

```markdown
# <plan-title>

- **Date:** YYYY-MM-DD
- **Scope:** one-line — what the whole plan delivers
- **Projects:** [primary-repo, secondary-repo, ...]
- **Source / brainstorm:** path-to-source-doc-or-jsonl
- **Total chunks:** N
- **Concurrency:** "sequential" | "phase-1 parallel / phase-2 sequential" | "all parallel"
- **Verification cadence:** "per-chunk full suite" | "per-item + per-chunk suite" | "end-of-plan only"
```

## Orchestration table (right after header)

```markdown
## Orchestration

| Chunk | Title          | Deps     | Concurrent with | Subagent           | Project        | Budget       |
|-------|----------------|----------|-----------------|--------------------|----------------|--------------|
| 1     | <title>        | —        | —               | kaizen-implementer | repo-a         | ~80 calls    |
| 2     | <title>        | 1        | 3               | kaizen-implementer | repo-a         | ~80 calls    |
| 3     | <title>        | 1        | 2               | general-purpose    | repo-b         | ~50 calls    |
| 4     | <title>        | 2, 3     | —               | kaizen-implementer | repo-a         | ~120 calls   |
| 5     | <title>        | 4        | —               | kaizen-implementer | repo-a + b     | ~60 calls    |
```

The orchestrator (parent agent / human) reads this table and dispatches phase-by-phase. Same-deps rows in the `Concurrent with` column run in parallel — same message, multiple Agent calls.

---

## Per-chunk template (repeat per chunk)

> Use exactly these 4 H3 section headers, in this order: **Guide**, **Task list (checklist)**, **Plan**, **TDD code chunks**. Plus two footer headers: **Done when** and **Dispatch**.

```markdown
## Chunk N: <title>

| field        | value                                                     |
|--------------|-----------------------------------------------------------|
| **Purpose**  | one sentence — what this chunk produces                    |
| **Project**  | repo-name-or-path                                          |
| **Deps**     | [chunk IDs that must finish first] (empty for chunk 1)     |
| **Outputs**  | artifacts downstream chunks consume                        |
| **Subagent** | kaizen-implementer / general-purpose / Explore / etc.      |
| **Isolation**| worktree (default for code) / none (read-only / docs)      |
| **Budget**   | ~N tool calls — agent must commit-what's-green if exhausted|


### Guide

- **Working dir:** `/abs/path/to/repo`
- **Skills to load FIRST (in order):** `Skill(<x>)`, `Skill(<y>)`
- **Files to read FIRST (the canonical template / exemplar):** `path/a.py` (why), `path/b.yaml` (why)
- **Conventions in this codebase:** 2-3 bullets — patterns, naming rules, gate behaviors
- **Upstream decisions that constrain this chunk:** what the user / prior chunks already settled
- **What NOT to touch:** file paths / decisions explicitly out of scope


### Task list (checklist)

- [ ] **N.A** <short> — one-line description
- [ ] **N.B** <short> — one-line description
- [ ] **N.C** <short> — one-line description
- [ ] **N.D** <short> — one-line description
- [ ] **N.E** chunk close-out — full suite + arch log row + final commit refs chunk-N

(One bullet per logical TDD unit. Aim 3-7 per chunk; if it'd exceed 10, split into a sibling chunk.)


### Plan

| Action  | Path                                  | Responsibility                                |
|---------|---------------------------------------|-----------------------------------------------|
| Create  | `skills/.../foo.py`                   | <one-line responsibility>                     |
| Modify  | `bar.py:120-145`                      | <what changes>                                |
| Create  | `tests/test_foo.py`                   | paired test (iron-law bin-coverage)           |
| Update  | `.claude-plugin/plugin.json`          | perm entry for foo.py + bin/kaizen-foo        |
| Symlink | `bin/kaizen-foo`                      | → `../skills/.../foo.py`                      |
| Append  | `.kaizen/workflow/progress.md`        | architecture log row (close-out commit)       |


### TDD code chunks

> One `#### item N.X — <name>` block per checklist row. Strict shape: RED snippet, GREEN outline, commit message. No item ships without all three.

#### item N.A — <component name>

**RED test** (`tests/test_X.py`):
```python
def test_<scenario>(self):
    ...
    self.assertEqual(actual, expected)
```

Run: `cd plugins/kaizen && python3 -m unittest tests.test_X -v`
Expected: FAIL — `<reason>` (module/function/class doesn't exist yet).

**GREEN impl outline** (`skills/.../X.py`):
- Public API: `def f(x: T) -> U`
- Algorithm: <2-3 bullets — happy path, edges, error handling>
- Reuses: <which shared helpers — _envelope, _atomic, schema_cli, etc.>

**Commit:** `feat(<X>): <one-line subject> (chunk N item A)`

#### item N.B — <component name>

(Same shape — RED / GREEN / commit. Repeat for every checklist row.)

#### item N.E — chunk close-out

**RED:** `cd plugins/kaizen && python3 -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3` — expect `OK (skipped=N)`, NO failures.

**GREEN:** append architecture log row summarizing the N axes + test-baseline delta.

**Commit:** `chore(progress): chunk N close-out — <one-line> (Refs: docs/.../<plan>.md::chunk-N)`


### Done when:

- [ ] Every item's paired test green
- [ ] Full suite — 0 regressions on the prior baseline
- [ ] Architecture log row appended
- [ ] Hand-off note in close-out commit references `chunk-N` + downstream `chunk-N+1`


### Dispatch (paste-ready)

```python
Agent(
    description="Chunk N — <title>",
    subagent_type="kaizen-implementer",
    isolation="worktree",
    prompt=f"""Implement Chunk N of <plan-path>.

WORKING DIR: <abs path>

READ FIRST (in order):
1. <plan-path>::chunk-N
2. docs/superpowers/templates/chunk-plan-template.md (the shape of this chunk)
3. <one canonical exemplar file>

SKILLS TO LOAD (before any edit): <skill-list>

EXECUTE: the **Task list (checklist)** above, in order. Each item is a (RED → GREEN → commit) triple per **TDD code chunks**. Never skip RED-then-GREEN verification, never bundle items into one commit, never modify outside the chunk's **Plan** file inventory without flagging it first.

DEPS COMPLETE: Chunks {deps} are finished. Read their outputs (named in Outputs column) before starting.

DONE WHEN (the chunk's **Done when:** gate clears): every paired test green, full suite 0 regressions, arch log row appended, final commit references chunk-N.

BUDGET: ~{budget} tool calls. If exhausted before finish: commit green items + write `chunk-N-resume.md` listing what's left."""
)
```
```

---

## Common pitfalls (apply across all chunks)

| Pitfall                                                                  | Mitigation                                                                                       |
|--------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------|
| Chunk depends on a file produced by a parallel sibling — they collide    | Move the producer earlier in the chain; sequentialize the parallel pair                          |
| Subagent runs out of context before finishing                            | Smaller chunks (3-5 items each); explicit `BUDGET` cap; resume-doc on exhaust                    |
| TDD discipline drifts ("just this once skip RED")                        | Iron Laws block in dispatch prompt; require `RED test snippet` per item                          |
| Per-chunk full suite is too slow (3000+ tests × N chunks)                | Per-item paired tests + once-per-chunk full suite; flip the `Verification cadence` header        |
| Cross-project work needs files from repo-A to land in repo-B             | Explicit `Outputs:` line in chunk A naming the path; chunk B `Deps:` declares the import         |
| Subagent makes wrong git-state assumption (uncommitted prior chunk)      | Each chunk's first task: `git status` + `git log -1` + assert prior chunk's last commit SHA      |
| User says "do all 5" — orchestrator runs them in parallel, deps fail     | Honor the `Concurrent with` column literally; never collapse past declared deps                  |
| Per-chunk subagent loses brainstorm context                              | The **Guide** section is the rehydration block — must include the upstream `why` not just `what` |

## When to use this template

- **Use** for plans with ≥3 logical phases, multi-day duration, OR ≥1 subagent dispatch, OR work spanning ≥2 repos.
- **Skip** for one-shot tasks, single-component refactors, or anything ≤5 commits total. Inline TaskCreate is lighter weight.
- **Adapt** the chunk count freely — 3 chunks for medium plans, 7 for sprawling ones. The 4-section per-chunk shape (Guide / Task list / Plan / TDD code chunks) is invariant.

## Related

- `superpowers:writing-plans` — produces the inline plan; this template wraps it for multi-chunk dispatch.
- `superpowers:subagent-driven-development` — the agent-orchestrator pattern that consumes this template.
- `kaizen:handoff` — the artifact passed between sessions if a chunk spans a context boundary.
- `kaizen:loop` — the runtime for ledger-driven multi-iteration execution; one chunk = one ledger entry.
- `kaizen:tdd` — the discipline body referenced by every chunk's TDD code chunks block.
