---
name: handoff-managing
description: Creates and resumes session handoff documents for transferring work between sessions. Use to save context, resume from previous sessions, or manage handoff files.
metadata:
  version: "1.2"
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

The session name groups related handoffs into one folder. Derive it
from the **current project** — the "latest folder" heuristic alone is
project-blind and mis-files cross-project work (kaizen-md work under a
`shodan-rs/` folder, etc.).

```bash
# Primary signal: the current git repo name — the correct grouping.
git rev-parse --show-toplevel 2>/dev/null | xargs -r basename
```

- If that prints a name → use it.
- If empty (not in a git repo) → fall back to the latest existing
  folder: `ls -td ~/.claude/thoughts/handoffs/*/ 2>/dev/null | head -1 | xargs -r basename`.
- If still empty → use `general`.
- If you're working a ticket (e.g. `ENG-2124`), prefer the ticket id
  as the session name regardless of the above.

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
status: partial          # PLACEHOLDER — Step 4 sets the real value
outcome: IN_PROGRESS     # PLACEHOLDER — Step 4 sets this from the user's answer
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
- `status:` + `outcome:` — write the PLACEHOLDER values shown above (`partial` / `IN_PROGRESS`) and nothing else. The real values come from the user in Step 4 — do NOT guess or pre-fill them here, or Step 4's question becomes performative.
- Prefer file-path-with-line references (`crates/core/src/runtime/dispatch.rs:222`) over inline code blocks.
- Be thorough. The whole point is to compress context without losing key details.

Use the **Write** tool to save the file.

### Step 3 — Optionally persist to the SQLite DB

The **filesystem YAML from Step 2 is the system of record** — portable,
always works, what `resume` reads. The SQLite DB at
`~/.claude/session_logs.db` is an *optional queryable index*, written
via `~/.claude/scripts/stores.py`. That helper is **not shipped with
the plugin** — it's part of a personal `~/.claude/scripts/` setup. If
it's absent, **skip this step**; the handoff is already saved.

```bash
# Guarded — only touch the DB if the helper actually exists.
if [ -f ~/.claude/scripts/stores.py ]; then
  python3 -c "
import sys, os
sys.path.insert(0, os.path.expanduser('~/.claude/scripts'))
from stores import handoff_save
content = open(os.path.expanduser('~/.claude/thoughts/handoffs/{session-name}/{filename}.yaml')).read()
handoff_save('{session-name}', content, 'partial')
print('Saved to DB')
"
else
  echo "stores.py absent — filesystem YAML is the record; skipping DB."
fi
```

Replace `{session-name}` and `{filename}` (no extension) with values from step 1. The DB row's status starts `partial`; the final outcome is set in Step 4.

### Step 4 — Mark session outcome (REQUIRED)

Step 2 wrote placeholder `status:` / `outcome:`. Now get the real
values from the user and write them back.

Ask about the session outcome via the **AskUserQuestion** tool:

```
Question: "How did this session go?"
Options:
  - SUCCEEDED:     Task completed successfully
  - PARTIAL_PLUS:  Mostly done, minor issues remain
  - PARTIAL_MINUS: Some progress, major issues remain
  - FAILED:        Task abandoned or blocked
```

After the user responds:

1. **Update the YAML file** (the system of record) — use the **Edit**
   tool to replace the placeholder frontmatter:
   - `status:` → `complete` (or `partial` / `blocked` per the work)
   - `outcome:` → the user's literal answer (`SUCCEEDED` / `PARTIAL_PLUS` / `PARTIAL_MINUS` / `FAILED`)

2. **Optionally re-save to the DB** — same guard as Step 3:

```bash
if [ -f ~/.claude/scripts/stores.py ]; then
  python3 -c "
import sys, os
sys.path.insert(0, os.path.expanduser('~/.claude/scripts'))
from stores import handoff_save
content = open(os.path.expanduser('~/.claude/thoughts/handoffs/{session-name}/{filename}.yaml')).read()
handoff_save('{session-name}', content, '<USER_CHOICE>')
print('Outcome recorded in DB')
"
else
  echo "stores.py absent — YAML frontmatter already updated; skipping DB."
fi
```

Replace `<USER_CHOICE>` with the literal answer. If the DB step runs, the outcome lives in the `status` column of the `handoffs` table — but the YAML frontmatter is authoritative.

### Step 5 — Confirm completion to the user

```
Handoff saved: ~/.claude/thoughts/handoffs/{session-name}/{filename}.yaml
Outcome: {OUTCOME}.

Resume in a new session by pointing it at that path, or run the
`resume` command with the path. (If the optional DB index is present,
`resume` with no args also works — but the YAML file is the record.)
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

The filesystem is the system of record. List the most recent handoffs:

```bash
ls -t ~/.claude/thoughts/handoffs/*/*.yaml 2>/dev/null | head -5
```

- One clear most-recent → read it (Step 2).
- Several plausible / ambiguous → present the list, ask which one.
- None found → tell the user there's no handoff to resume.

The optional DB index (`~/.claude/scripts/stores.py`, if present) can
also answer "latest" — but it's just a convenience over the YAML
files, which are authoritative. Don't depend on it.

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
- **Create asks for outcome.** Do not skip Step 4 of `create` — and write the answer back to the YAML frontmatter, not just the DB. The YAML file is the system of record; the SQLite DB is an optional, may-not-be-present index.
- **The plugin ships self-contained.** The `~/.claude/scripts/stores.py` DB helper is NOT part of the plugin — every DB step is guarded with `if [ -f ~/.claude/scripts/stores.py ]` and degrades to filesystem-only. Never add an unguarded external-script invocation (iron law `skill-md-no-external-script-paths`).
