---
name: handoff-managing
description: Creates and resumes session handoff documents for transferring work between sessions. Use to save context, resume from previous sessions, or manage handoff files.
metadata:
  version: "1.1"
---

# Handoff Managing

Creates and resumes session handoff documents for transferring work between sessions.

- **`create`** — write a YAML handoff doc + persist to the DB so a future session can pick up cleanly.
- **`resume`** — read the latest handoff (or one specified by path/ticket), verify the codebase still matches, then propose a continuation plan.

If the user's intent is ambiguous, ask which one.

---

## Command: `create`

You are wrapping up the current session. Goal: produce a thorough but **concise** handoff document so another agent (or you in a fresh session) can resume without re-deriving context.

### Step 1 — Determine session name + filepath

```bash
# Latest existing session folder. Returns folder name, or empty if none.
ls -td ~/.claude/thoughts/handoffs/*/ 2>/dev/null | head -1 | xargs -r basename
```

If output is empty, use `general` as the session name. Otherwise use the returned folder name (e.g. `open-source-release`, `ENG-2124`).

File path:

```
~/.claude/thoughts/handoffs/{session-name}/YYYY-MM-DD_HH-MM_{kebab-description}.yaml
```

- `YYYY-MM-DD` — today (UTC date is fine)
- `HH-MM` — 24-hour time, no seconds
- `{kebab-description}` — short kebab-case summary (e.g. `memory-system-fix`, `bug-investigation`)

Get the timestamp:

```bash
date -u +%Y-%m-%d_%H-%M
```

### Step 2 — Write the YAML handoff

**CRITICAL:** Use exactly this schema. The `goal:` and `now:` fields are parsed by the statusline — **renaming them breaks the statusline display**.

```yaml
---
session: {session-name from step 1}
date: YYYY-MM-DD
status: complete|partial|blocked
outcome: SUCCEEDED|PARTIAL_PLUS|PARTIAL_MINUS|FAILED
---

goal: {one line — what this session accomplished. Shown in statusline.}
now: {one line — what the next session should do first. Shown in statusline.}
test: {command to verify this work, e.g. `cargo test --workspace`}

done_this_session:
  - task: {first completed task}
    files: [path/to/file1.rs, path/to/file2.rs]
  - task: {second completed task}
    files: [path/to/file3.rs]

blockers: [any blocking issues — empty list if none]
questions: [unresolved questions for next session]

decisions:
  - {decision_name}: {rationale}

findings:
  - {key_finding}: {details}

worked: [approaches that worked — repeat]
failed: [approaches that failed and why — avoid]

next:
  - {first next step}
  - {second next step}

files:
  created: [new files]
  modified: [changed files]
```

**Rules:**
- `goal:` + `now:` — required, statusline-visible.
- **Do not** rename to `session_goal` / `objective` / `focus` / `current` — the parser only matches `goal:` and `now:`.
- Prefer file-path-with-line references (`crates/core/src/runtime/dispatch.rs:222`) over inline code blocks.
- Be thorough. The whole point is to compress context without losing key details.

Use the **Write** tool to save the file.

### Step 3 — Persist to the SQLite DB

The handoff is stored to BOTH the filesystem (above) AND the SQLite DB at `~/.claude/session_logs.db` (primary, queryable).

```bash
~/.claude/scripts/.venv/bin/python3 -c "
import sys, os
sys.path.insert(0, os.path.expanduser('~/.claude/scripts'))
from stores import handoff_save
content = open(os.path.expanduser('~/.claude/thoughts/handoffs/{session-name}/{filename}.yaml')).read()
handoff_save('{session-name}', content, 'partial')
print('Saved to DB')
"
```

Replace `{session-name}` and `{filename}` (no extension) with values from step 1. Initial status is `partial` — the final outcome is set in step 4.

### Step 4 — Mark session outcome (REQUIRED)

Before responding to the user, ask about the session outcome via the **AskUserQuestion** tool:

```
Question: "How did this session go?"
Options:
  - SUCCEEDED:     Task completed successfully
  - PARTIAL_PLUS:  Mostly done, minor issues remain
  - PARTIAL_MINUS: Some progress, major issues remain
  - FAILED:        Task abandoned or blocked
```

After the user responds, re-save with the final status:

```bash
~/.claude/scripts/.venv/bin/python3 -c "
import sys, os
sys.path.insert(0, os.path.expanduser('~/.claude/scripts'))
from stores import handoff_save
content = open(os.path.expanduser('~/.claude/thoughts/handoffs/{session-name}/{filename}.yaml')).read()
handoff_save('{session-name}', content, '<USER_CHOICE>')
print('Outcome recorded in DB')
"
```

Replace `<USER_CHOICE>` with the literal answer (`SUCCEEDED` / `PARTIAL_PLUS` / `PARTIAL_MINUS` / `FAILED`). Outcome lives in the `status` column of the `handoffs` table.

### Step 5 — Confirm completion to the user

```
Handoff created at ~/.claude/thoughts/handoffs/{session-name}/{filename}.yaml
Outcome marked as {OUTCOME}.

Resume in a new session with the `resume` command (no args needed —
the latest DB handoff loads automatically) or by passing a path.
```

---

## Command: `resume`

You are resuming work from a prior handoff. Goal: load the latest (or specified) handoff, **verify the codebase still matches its assumptions**, then propose a continuation plan.

### Step 1 — Locate the handoff

Three input modes:

#### Mode A — Explicit path provided

```
/resume_handoff path/to/handoff.yaml
```

→ Skip the lookup. Read that file in full immediately.

#### Mode B — Ticket number provided (e.g. `ENG-2124`)

Look up `~/.claude/thoughts/handoffs/{ticket}/`:

```bash
ls -t ~/.claude/thoughts/handoffs/{TICKET}/ 2>/dev/null
```

- Zero files / dir doesn't exist → tell the user: *"I can't find a handoff for that ticket. Provide a path or run with no args to use the latest DB entry."*
- One file → use it.
- Multiple files → use the most recent (filename starts with `YYYY-MM-DD_HH-MM`).

#### Mode C — No args

Query the DB for the latest entry:

```bash
~/.claude/scripts/.venv/bin/python3 -c "
import sys, os
sys.path.insert(0, os.path.expanduser('~/.claude/scripts'))
from stores import handoff_latest
results = handoff_latest(limit=1)
if results:
    h = results[0]
    print(f'session_id={h[\"session_id\"]} created_at={h[\"created_at\"]} status={h[\"status\"]}')
    print('---CONTENT---')
    print(h['content'])
else:
    print('NO_DB_HANDOFF')
"
```

- DB hit → use that content directly (skip the "ask which one" prompt).
- `NO_DB_HANDOFF` → fall back to filesystem: list `~/.claude/thoughts/handoffs/*/` and present options.

### Step 2 — Read the handoff fully + its references

Use **Read** without `limit`/`offset` so you get the whole thing.

Then **read every artifact it links** (research docs, plan docs, mentioned files). Do this directly — **do not delegate to a sub-agent for these critical reads**.

### Step 3 — Verify codebase state matches

Spawn focused research tasks in parallel to check:

1. **Files mentioned in `done_this_session`** — still exist? Modified since?
2. **`worked:` patterns** — still applicable in current code?
3. **`failed:` approaches** — make sure they haven't been re-introduced.
4. **`next:` action items** — still valid given the current tree?
5. **Recent commits** — `git log --oneline <handoff-date>..HEAD` to see what changed since the handoff was written.

Wait for ALL sub-tasks to complete before continuing.

### Step 4 — Synthesize and present analysis

```
I've analyzed the handoff from {date}. Current situation:

**Original goal:** {goal from handoff}
**Original next step:** {now from handoff}

**Done this session — verification:**
- {task 1}: {Verified present | Modified | Reverted | Missing}
- {task 2}: ...

**Decisions still in force:**
- {decision}: {still holds | superseded by commit X}

**Findings still valid:**
- {finding}: {confirmed | stale because Y}

**Recent codebase changes since handoff** ({git log range}):
- {commit summary}
- ...

**Recommended next actions:**
1. {most logical next step from `next:`}
2. {second priority}
3. {newly discovered task, if any}

**Issues identified:**
- {regression / conflict / missing dep, if any}

Shall I proceed with {recommended action 1}, or would you like to adjust?
```

### Step 5 — Get confirmation, then create the action plan

After the user confirms direction:

1. Use **TaskCreate** to create the task list — convert handoff `next:` items + newly discovered tasks into trackable tasks.
2. Begin execution. **Mark each task `in_progress` when starting, `completed` immediately when done** (no batching).
3. Apply `worked:` patterns; avoid `failed:` ones.
4. Reference the handoff path in commits: `Refs: ~/.claude/thoughts/handoffs/.../X.yaml`.

### Common scenarios

| Scenario | Action |
|---|---|
| Clean continuation — nothing diverged | Proceed with handoff's `next:` items as written. |
| Diverged codebase — some changes missing | Reconcile. Surface the divergence to the user before touching code. |
| Incomplete handoff work — tasks still `in_progress` | Finish those first before any new work. |
| Stale handoff — significant time / refactoring since | Re-evaluate strategy. Treat handoff as historical context, not the plan. |

---

## Notes for both commands

- **Be thorough**: more information is better than less. Include both top-level objectives and lower-level details.
- **Avoid large code blocks / diffs**. Use `path/to/file.ext:line` references the next agent can follow when ready.
- **Resume verifies, never assumes.** Codebase state can drift between sessions; always confirm `done_this_session` files still exist and the `worked:` patterns still hold.
- **Create asks for outcome.** Do not skip step 4 of `create` — the DB outcome column is what makes handoffs queryable later.
