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
| Symlink | `bin/kaizen-foo`                      | → `../skills/.../foo.py`                      |
| Write   | `.chunks/N/perms.json`                | perm fragment (merged in plan-level merge)    |
| Write   | `.chunks/N/progress.md`               | arch log fragment (merged in plan-level merge)|
| Write   | `.chunks/N/backlog.jsonl`             | backlog fragment (merged in plan-level merge) |


### Isolation contract

**Owns (exclusive write):**
- `skills/<feature>/...` paths matching this chunk's scope
- `tests/test_<this-chunk-only>.py`
- `bin/kaizen-<this-chunk-only>` (new symlinks only — never edit existing)
- `.chunks/N/` (this chunk's fragment directory — single-writer guarantee)

**Reads only (NEVER writes):**
- `.claude-plugin/plugin.json` — perm entries go to `.chunks/N/perms.json` fragment instead
- `.kaizen/workflow/progress.md` — arch log row goes to `.chunks/N/progress.md` instead
- `.kaizen/workflow/backlog.json` — backlog items go to `.chunks/N/backlog.jsonl` instead
- `gateway.py::SUBSERVERS` — MCP-mount entries go to `.chunks/N/mcp-mounts.txt` instead
- Files owned by other chunks (see their Isolation contract)

**Why fragments-not-direct-edits:** five parallel agents touching the same `plugin.json` would race. The fragment pattern guarantees each chunk's writes are conflict-free regardless of dispatch order; the plan-level **Merge step** (run by parent after all chunks settle) consolidates fragments into the canonical files in a single atomic pass.

**Fragment shapes** (canonical formats):

```json
// .chunks/N/perms.json — list of plugin.json::permissions.allow entries to merge
[
  "Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/foo.py:*)",
  "Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-foo:*)"
]
```

```markdown
<!-- .chunks/N/progress.md — single row destined for the architecture log -->
| 2026-MM-DD | feat | +X -0 | Chunk N — <title>: <one-line summary>. Refs: docs/.../plan.md::chunk-N |
```

```jsonl
// .chunks/N/backlog.jsonl — backlog items destined for `.kaizen/workflow/backlog.json`
{"title": "...", "probe": "...", "verify": "...", "section": "parked", "ref": "...", "tags": "..."}
```

**Worktree usage:** when `Isolation: worktree`, the chunk runs in `.claude/worktrees/chunk-N/` and the `.chunks/N/` fragment dir is created INSIDE that worktree. After the chunk's branch merges to master, the fragment becomes visible to the merge step.


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

## Plan-level Merge step (mandatory when ≥2 chunks run in parallel)

After all parallel chunks complete (their branches merged to master OR their commits land in master), the parent runs a single **Merge step** that consolidates per-chunk fragments into the canonical files. This is the ONLY phase allowed to mutate `plugin.json`, `progress.md`, `backlog.json`, or `gateway.py::SUBSERVERS`.

```markdown
## Merge step (run by parent / orchestrator)

**Trigger:** all chunks declared `Done when` clear AND their commits landed on master.

**Inputs:** `.chunks/*/perms.json`, `.chunks/*/progress.md`, `.chunks/*/backlog.jsonl`, `.chunks/*/mcp-mounts.txt` (where present)

**Actions** (single sequential pass — no concurrency here):

1. **Plugin perms:**
   ```bash
   python3 -c "
   import json
   from pathlib import Path
   pj = Path('plugins/kaizen/.claude-plugin/plugin.json')
   raw = json.loads(pj.read_text())
   allow = list(raw['permissions']['allow'])
   for frag in sorted(Path('.chunks').glob('*/perms.json')):
       allow.extend(e for e in json.loads(frag.read_text()) if e not in allow)
   raw['permissions']['allow'] = allow
   pj.write_text(json.dumps(raw, indent=2) + '\\n')
   "
   ```

2. **Architecture log:**
   ```bash
   for frag in $(ls .chunks/*/progress.md | sort); do
       cat "$frag" >> .kaizen/workflow/progress.md
   done
   ```

3. **Backlog:**
   ```bash
   for frag in $(ls .chunks/*/backlog.jsonl | sort); do
       while IFS= read -r line; do
           [ -z "$line" ] && continue
           # Parse line as JSON, dispatch to `kaizen backlog add`
           python3 -c "import json,subprocess,sys
   row = json.loads(sys.argv[1])
   subprocess.run(['kaizen', 'backlog', 'add',
       '--title', row['title'], '--probe', row['probe'],
       '--verify', row['verify'], '--section', row.get('section', 'parked'),
       '--ref', row.get('ref', ''), '--tags', row.get('tags', '')], check=True)" "$line"
       done < "$frag"
   done
   ```

4. **MCP mounts** (if any chunk wrote `.chunks/N/mcp-mounts.txt`): edit `gateway.py::SUBSERVERS` to append, one Edit per mount line.

5. **Cleanup:** `rm -rf .chunks/` (post-consolidation; the per-chunk fragments are now redundant).

6. **Merge commit:** `chore(merge): consolidate fragments from chunks 1-N (Refs: docs/.../plan.md)`

7. **Verification:** `python3 -m unittest discover -s plugins/kaizen/tests -p "test_*.py" | tail -3` — assert 0 regressions on the consolidated state.

**Why this works:** every step in the merge is deterministic and single-writer. No two agents are ever mutating the same canonical file simultaneously. The fragments are conflict-free by construction (each chunk owns its `.chunks/N/`).

**Done when:**
- [ ] `.chunks/` directory deleted
- [ ] One merge commit landed
- [ ] Full suite passes
```

## Parallelism contract (plan-level)

The **Orchestration table** column `Concurrent with` and the `Deps` column together define a DAG. To guarantee parallel-safe dispatch:

| Constraint                                                              | How the template enforces it                                                                          |
|-------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------|
| Two chunks must never write the same file                               | Each chunk's `Plan` table only lists files in its scope; canonical-shared files write to `.chunks/N/` fragments instead |
| A chunk consuming chunk X's output must declare `Deps: X`               | `Outputs` column in chunk X declares its artifacts; consuming chunks list X in `Deps`                  |
| Two chunks with no `Deps` between them may run in parallel              | `Concurrent with` column lists which siblings run in the same phase                                    |
| Cross-project chunks (different repos) are always parallel-safe         | `Project` column scopes the chunk's write surface                                                      |
| Retrofit / refactor work that touches existing files is NEVER parallel | Such work is its own chunk with `Deps: <all chunks producing the targets>` AND `Concurrent with: —`    |

**Dispatch rule:** parent only sends two chunks in the same message when EITHER:
- their `Concurrent with` columns name each other, OR
- they target different `Project` repos AND share no fragment-dir collisions

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
