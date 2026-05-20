<!-- DO NOT HAND-EDIT.

Generated from schemas/workflow/git-discipline.yaml by
scripts/workflow/codegen.py.

To change content, edit the yaml and run:
    python3 scripts/workflow/codegen.py
or rely on refresh-cache.sh which invokes codegen before sync.
-->

# Git Workflow Discipline

Project-agnostic discipline for committing code via the kaizen plugin. Rules in this file are derived from the canonical `domain/git-discipline.yaml`. The pre-commit hook + commit-msg hook + backlog.py read the yaml directly; this markdown is for humans + agents.

## Commit format

- **Style:** conventional
- **Subject max chars:** 72
- **Body wrap chars:** 76
- **Scope required:** True
- **Allowed prefixes:** `feat`, `fix`, `refactor`, `docs`, `chore`, `test`, `perf`, `style`, `ci`, `build`, `revert`

## Sizing model (NEVER by clock-time)

Size work by **trace + sem + grep** — count actual files touched, manifest edits, trait moves, cross-context hops. Never by hours.

| Tier | Threshold | Destination |
|---|---|---|
| Micro | ≤3 files, 0 manifest edits, 0 trait moves | `backlog.json` |
| Split siblings | 4–15 files OR 1 manifest OR 1 trait move | sibling micros |
| Plan file | ≥16 files OR ≥2 manifests OR cross-context OR carve-out trigger | `plans/<date>-<slug>.md` |

## Pre-commit gates (13)

Each gate runs in order; cheaper gates first. Errors block; warnings notify.

### `compile_barrier` (error)

Project-defined compile check (cargo check / tsc / mypy / go build)

**Bypass:** `KAIZEN_SKIP_COMPILE=1`

### `backlog_schema_valid` (error)

backlog.json validates against schema_version:1 + kind:kaizen.backlog

**Probe:** `python3 ${SCRIPTS}/backlog.py verify`

### `backlog_md_in_sync` (error)

backlog.md regenerated from backlog.json (no hand-edit drift)

**Probe:** `python3 ${SCRIPTS}/backlog.py verify`

### `structural_change_logs_to_progress` (error)

If diff is structural (new crate / carve / locked-rule), progress.md row appended

### `plan_phase_tick` (error)

If a plan-file phase landed, the plan's checkbox is ticked in the same commit

### `no_deletion_without_auth` (error)

Pre-deletion belief — no `git rm` without explicit user authorization

**Probe:** `git diff --cached --diff-filter=D --name-only`

**Bypass:** `KAIZEN_ALLOW_DELETE=1`

### `no_amend_published` (error)

Never amend a commit that's been pushed

### `no_skip_hooks` (warn)

--no-verify usage flagged (hook skipping is a code smell)

### `paired_test_for_new_code` (warn)

New public function/class should have a paired test in the same commit

**Bypass:** `KAIZEN_SKIP_TDD_CHECK=1`

### `no_volatile_data_in_claude_md` (error)

CLAUDE.md must not contain SHAs, dates, or LOC numbers (volatile)

### `iron_laws` (error)

Staged diff checked against the auto-enforced iron laws (kaizen-md repo only)

**Probe:** `python3 ${SCRIPTS}/iron_laws.py check --staged`

### `conventional_commit_subject` (error)

Commit message subject matches Conventional Commits format

**Probe:** `${SCRIPTS}/commit-msg.sh`

### `read_after_mv` (warn)

Every `git mv` should be followed by a Read of the new path before editing

## Pre-deletion belief

Read → analyze → dedup → migrate → consolidate. Never `git rm` until
the user has explicitly approved that specific deletion.

**Bypass (single commit):** `KAIZEN_ALLOW_DELETE=1 git commit ...`

## Plan files

- **Location:** `plans/`
- **Archive:** `plans/archive/<YYYY-MM>/`
- **Triggers:** ≥3 phases, carve-out trigger, work needing a risk register, cross-context migration
- **Status values:** DRAFT, IN-PROGRESS, COMPLETE, SUPERSEDED

## Recovery patterns

- **wrong edit:** `git diff <file> → git checkout -- <file>`
- **wrong staged file:** `git restore --staged <file>`
- **before commit:** `git diff --staged`
- **mid task detour:** `git stash → fix → git stash pop`
- **multi file op:** `git status before + after`
- **failed edit:** `git diff first, diagnose before adding code`

## Forbidden without explicit user permission

- `git push --force`
- `git reset --hard`
- `git clean -fd`
- `git rebase against published branch`
- `git commit --no-verify`
- `git commit --no-gpg-sign`
- `cross-project commits`

## Bash invocation discipline

How to author Bash tool calls so they don't trigger unnecessary
permission reprompts on a Bash(*)-allowlisted setup, AND so destructive
operations are isolated in their own call frames for clearer audit.

### `rm_in_isolation` (**hard**)

Never combine `rm` / `rm -rf` with other operations in one Bash call

_Why:_ Destructive-op heuristic reprompts even when Bash(*) is allowed; isolation also makes audit trails clearer.

**Good:**
```bash
# Call 1 (setup): cd /tmp && mkdir test && cd test && git init -q
# Call 2 (test):  ...
# Call 3 (cleanup, separate): rm -rf "$TMPDIR"
```

**Bad:**
```bash
# ONE call: cd /tmp && rm -rf test && mkdir test && ...  ← reprompts
```

### `export_over_envprefix` (soft)

Prefer `export VAR=value; cmd` over `VAR=value cmd` inline

_Why:_ CC's matcher parses first-word-as-binary; env-prefix can hide the actual command from Bash(*) matching.

**Good:**
```bash
export KAIZEN_ALLOW_DELETE=1; git commit -m '...'
```

**Bad:**
```bash
KAIZEN_ALLOW_DELETE=1 git commit -m '...'
```

### `split_compound_when_destructive` (**hard**)

Split multi-line `&&` chains into discrete Bash tool calls when any step is destructive

_Why:_ Compound commands evaluated as one unit; one risky token pollutes the whole and triggers a single prompt for everything.

**Good:**
```bash
Issue setup, test, cleanup as 3 separate Bash tool calls
```

**Bad:**
```bash
All-in-one: `setup && test && rm -rf cleanup` in one tool call
```

### `mktemp_for_scaffolds` (soft)

Use `mktemp -d -t prefix-XXXX` for test scaffold dirs

_Why:_ Avoids hardcoded /tmp/<name> paths that race with prior runs and forces unique-per-invocation cleanup.

**Good:**
```bash
TMPDIR=$(mktemp -d -t deltest-XXXX)
```

**Bad:**
```bash
rm -rf /tmp/deltest && mkdir /tmp/deltest
```

### `find_delete_for_dir_empty` (soft)

`find <path> -mindepth 1 -delete` is a quieter alternative to `rm -rf <path>/*` for emptying a dir

_Why:_ Some heuristics flag rm -rf but allow find -delete (less broad blast radius pattern).

**Good:**
```bash
find ./.kaizen/cache -mindepth 1 -delete
```

**Bad:**
```bash
rm -rf ./.kaizen/cache/*
```

### `scope_tool_calls_narrowly` (soft)

One logical operation per Bash tool call; avoid 5+ chained && commands

_Why:_ Better debuggability + per-call permission decisions. Compound calls hide errors mid-chain.

**Good:**
```bash
Three separate calls: build, test, package
```

**Bad:**
```bash
build && test && package && deploy && tag && push
```

**Enforcement:** advisory via PreToolUse hook (see `references/orchestration.md`). Blocking: `False`.

