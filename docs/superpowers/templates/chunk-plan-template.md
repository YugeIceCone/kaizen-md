# Chunk-plan template

Reusable template for breaking a multi-step plan into 5 (or N) independently-dispatchable chunks. Each chunk is:

- **Self-contained** — a fresh subagent (or future-you in a new session) can pick it up cold from the chunk's context block alone.
- **Sequenced** — `Chunk N` declares `Deps: [chunk IDs]`. The orchestrator runs them in order (or in parallel where deps allow).
- **TDD-shaped** — every code chunk inside a chunk is a `RED test → GREEN impl → commit` triple; the test wedge is written before the impl outline.
- **Verifiable** — a `Done when:` gate at the chunk level says exactly what success looks like.
- **Subagent-ready** — the `Dispatch:` block at the bottom is paste-ready for the `Agent` tool.

---

## Plan header

```markdown
# <plan-title>

- **Date:** YYYY-MM-DD
- **Scope:** <one-line — what this plan delivers across all chunks>
- **Projects:** [primary-repo, secondary-repo, ...]  ← list every repo touched
- **Source / brainstorm:** <path-to-source-doc-or-jsonl>
- **Total chunks:** N
- **Concurrency:** <"sequential" | "parallel where deps allow" | "phase-1 parallel; phase-2 sequential">
- **Verification cadence:** <"per-chunk full suite" | "per-item paired tests + per-chunk suite" | "end-of-plan suite only">
```

## Chunk block (repeat per chunk)

```markdown
## Chunk N: <title>

| field        | value                                                                         |
|--------------|-------------------------------------------------------------------------------|
| **Purpose**  | one sentence — what this chunk produces                                        |
| **Project**  | <repo-name-or-path>                                                            |
| **Deps**     | [chunk IDs that must finish first] (empty for chunk 1)                         |
| **Outputs**  | artifacts downstream chunks consume (file paths, env knobs, schemas)           |
| **Subagent** | `kaizen-implementer` (default for TDD) / `general-purpose` / `Explore` / etc. |
| **Isolation**| `worktree` (default for code work) / `none` (read-only / docs)                |
| **Budget**   | ~N tool calls / N hours / one session                                          |

### Context block (self-contained — what the subagent needs)

- **Working dir:** `/abs/path/to/repo`
- **Related skills to load first:** `Skill(<x>)`, `Skill(<y>)`
- **Files that exist (read first):** `path/a.py` (purpose), `path/b.yaml` (purpose)
- **Conventions in this codebase:** <2-3 bullets — patterns, naming, gate behavior>
- **What the user previously decided:** <upstream decisions that constrain this chunk>

### Task list (TaskCreate-ready)

```yaml
- subject: "<short>"
  description: "<what needs doing>"
  activeForm: "<verb-ing>"
- subject: "..."
  ...
```

### Plan (file inventory + responsibilities)

| Action  | Path                                | Responsibility                              |
|---------|-------------------------------------|---------------------------------------------|
| Create  | `skills/.../foo.py`                 | <what it does>                              |
| Modify  | `bar.py:120-145`                    | <what changes there>                        |
| Create  | `tests/test_foo.py`                 | paired test (Iron-Laws bin-coverage)        |
| Update  | `.claude-plugin/plugin.json`        | perm entry for foo.py + bin/kaizen-foo      |
| Symlink | `bin/kaizen-foo`                    | → `../skills/.../foo.py`                    |

### TDD code units (`item N.A` ... `item N.Z`)

#### item N.A — <component name>

**RED test** (`tests/test_X.py`):
```python
def test_<scenario>(self):
    ...
    self.assertEqual(...)
```

Run: `cd plugins/kaizen && python3 -m unittest tests.test_X -v`
Expected: FAIL on `<reason>` (module / function / class doesn't exist).

**GREEN impl outline** (`skills/.../X.py`):
- Public API: `def f(x: T) -> U`
- Algorithm: <2-3 bullets — happy path, edges>
- Error handling: <which exceptions, which return shapes>

**Commit:** `feat(<feature>): <one-line> (chunk N item A)`

#### item N.B — ...

(Repeat for each TDD unit. Aim 3-7 items per chunk; split into smaller chunks if you'd cross 10.)

### Done when:

- [ ] Every item's paired test green
- [ ] `python3 -m unittest discover -s tests -p "test_*.py"` — 0 regressions
- [ ] `.kaizen/workflow/progress.md` row appended (or N rows for big chunks)
- [ ] Hand-off note in commit message: `Refs: docs/.../<plan>.md::chunk-N`

### Dispatch (paste-ready Agent call)

```python
Agent(
    description="Chunk N — <title>",
    subagent_type="kaizen-implementer",  # or general-purpose
    isolation="worktree",
    prompt=f"""You're implementing Chunk N of <plan-title>.

WORKING DIR: <abs path>

READ FIRST (in order):
1. docs/.../<plan>.md::chunk-N   — the chunk spec
2. <referenced files from context block>

REQUIRED SKILLS (load before any edit):
- kaizen:tdd  (TDD Iron Laws)
- kaizen:plugin-development  (for kaizen-md plugin changes)
- <any chunk-specific skills>

EXECUTE: every item in `### TDD code units`, in order, RED→GREEN→commit each.

DEPS COMPLETE: Chunks {deps} are finished — read their outputs (listed in chunk-N::Deps) before starting.

DELIVERABLES (per `Done when:`):
- All chunk-N tests green
- Full suite 0 regressions  
- Architecture log row
- Final commit message references `chunk-N` in the body

BUDGET: ~{budget} tool calls. If you exhaust budget before finishing, commit what's green and write a hand-off note to chunk-N+1 listing the remaining items.

NEVER: skip RED-then-GREEN verification, bundle multiple items into one commit, or modify outside the chunk's file inventory without flagging it first."""
)
```

```

## Orchestration block (top of plan, after header)

```markdown
## Orchestration

| Chunk | Title          | Deps     | Concurrent with | Subagent           | Project        |
|-------|----------------|----------|-----------------|--------------------|----------------|
| 1     | <title>        | —        | —               | kaizen-implementer | repo-a         |
| 2     | <title>        | 1        | 3               | kaizen-implementer | repo-a         |
| 3     | <title>        | 1        | 2               | general-purpose    | repo-b         |
| 4     | <title>        | 2, 3     | —               | kaizen-implementer | repo-a         |
| 5     | <title>        | 4        | —               | kaizen-implementer | repo-a + repo-b|
```

The orchestrator (parent agent or human) walks this table:
- **Sequential mode:** dispatch chunks one at a time, wait for `Done when:` to clear before the next.
- **Parallel mode:** dispatch chunks with no shared deps in the same message (the `Concurrent with` column).
- **Cross-project chunks:** the `Project` column tells the dispatcher to `cd` into the right repo (or pass `cwd=...` to the subagent).

## Common pitfalls

| Pitfall                                                                  | Mitigation                                                                                       |
|--------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------|
| Chunk depends on a file produced by a parallel sibling — they collide    | Move the producer earlier in the chain; sequentialize the parallel pair                          |
| Subagent runs out of context before finishing                            | Smaller chunks (3-5 items each); explicit `BUDGET` cap                                           |
| TDD discipline drifts ("just this once skip RED")                        | Iron Laws block in dispatch prompt; require `RED test snippet` per item in the chunk spec        |
| Per-chunk full suite is too slow (3000+ tests × N chunks = minutes)      | Per-item paired tests + once-per-chunk full suite; flip the `Verification cadence` header        |
| Cross-project work needs files from chunk in repo-A to land in repo-B    | Add an explicit `Outputs:` line in chunk A naming the path; chunk B `Deps:` declares the import |
| Subagent makes the wrong git-state assumption (uncommitted prior chunk)  | Each chunk's first task: `git status` + `git log -1` + assert the prior chunk's last commit SHA  |
| User says "do all 5" — orchestrator runs them in parallel, deps fail    | Honor the `Concurrent with` column literally; never collapse chunks past their declared deps    |

## When to use this template

- **Use** for plans with ≥3 logical phases, multi-day duration, OR ≥1 subagent dispatch.
- **Skip** for one-shot tasks, single-component refactors, or anything ≤5 commits total. Inline tasks via `TaskCreate` are lighter weight.
- **Adapt** the 5-chunk count freely — the template is N-chunk; 3 chunks for medium plans, 7 for sprawling ones.

## Related

- `superpowers:writing-plans` — produces the inline plan; this template wraps it for multi-chunk dispatch.
- `superpowers:subagent-driven-development` — the agent-orchestrator pattern that consumes this template.
- `kaizen:handoff` — the artifact passed between sessions if a chunk spans a context boundary.
- `kaizen:loop` — the runtime for ledger-driven multi-iteration execution; one chunk = one ledger entry.
