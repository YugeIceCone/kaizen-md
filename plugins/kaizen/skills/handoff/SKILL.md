---
name: handoff-managing
description: Creates and resumes session handoff documents for transferring work between sessions. Use to save context, resume from previous sessions, or manage handoff files.
metadata:
  version: "1.4"
---

# Handoff Managing

Creates and resumes session handoff documents for transferring work between sessions.

- **`create`** — write a YAML handoff doc, index it into the handoff store, and bridge its durable learnings to brain so a future session picks up cleanly.
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
- **No raw `: ` (colon-space) inside a prose value.** YAML reads it as a nested mapping and the whole body fails to parse. Use ` — ` (em-dash) or `;` instead, or quote the value. A `file.rs:222` reference is fine — no space after the colon. (The line-based bridge tolerates a malformed body, but `resume` / the statusline `yaml.safe_load` the file — keep it valid.)
- Prefer file-path-with-line references (`crates/core/src/runtime/dispatch.rs:222`) over inline code blocks.
- Be thorough. The whole point is to compress context without losing key details.

Use the **Write** tool to save the file.

### Step 3 — Index the handoff into the store

The **filesystem YAML from Step 2 is the system of record**. The
plugin's handoff store (`handoff.db`) is the *queryable index* — it's
what `resume` reads to find the latest handoff fast. Index the YAML
you just wrote:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/handoff.py \
  save --session "{session-name}" \
       --file ~/.claude/thoughts/handoffs/{session-name}/{filename}.yaml \
       --status partial
```

`save` upserts on the file path — re-running it (Step 4 does) updates
the row in place, never duplicates. Status starts `partial`; Step 4
sets the final value. The store is plugin-owned (`handoff.py`); no
external-script dependency.

### Step 4 — Self-assess the outcome (REQUIRED)

Step 2 wrote placeholder `status:` / `outcome:`. Now finalize them.

**Default: agent-assigned.** You (the agent) self-assess the session
against the rubric below, write the outcome directly, and re-index in
one shot via `handoff.py auto-finalize`. No `AskUserQuestion` prompt
— that path was the old default and now applies only when the user
explicitly asks for an interactive sign-off.

Reasons to use the auto-assigned default:
- **Subagent invocations** — sub-agents have no `AskUserQuestion` access.
- **High-context-pressure sessions** (≥90% context used) — set
  `KAIZEN_HANDOFF_AGENT=1` to mark the intent clearly in the audit
  trail; the auto-finalize behavior is the same.
- **`/loop` / `/schedule` / autonomous runs** — no human to prompt.
- **Default interactive sessions** — Claude has the full session in
  context and can pick more reliably than asking the user "how did it
  go?" out of nowhere. The audit field `outcome_assigned_by: agent`
  records who picked.

#### Rubric — pick exactly one bucket

Look at four signals together: (1) which `done_this_session` tasks
landed, (2) whether the project's test baseline held (the `test:` line
should still pass), (3) what `blockers` / `questions` remain open, (4)
whether the `next:` items are forward-looking refinements or blocking
must-dos.

| Bucket | When to pick |
|---|---|
| **SUCCEEDED** | All planned `done_this_session` tasks landed AND the test baseline holds AND `blockers` is empty AND no `next:` item is blocking the session's stated goal. Tests green, goal met. |
| **PARTIAL_PLUS** | Most tasks landed; tests still green; at most minor open `questions` / non-blocking `next:` items. Net forward progress, no regressions. |
| **PARTIAL_MINUS** | Some tasks landed but **major** issues remain — pre-existing tests broken, a `blockers` entry surfaced, or `next:` items include must-fix-before-merge work. Partial progress, real follow-up required. |
| **FAILED** | Few/no tasks landed OR the session was abandoned mid-flight OR tests went red without a fix. Goal not met; the resume needs to triage before continuing. |

Bias toward the more conservative bucket when on the line. A
`PARTIAL_PLUS` that should have been `PARTIAL_MINUS` misleads the next
session's triage; the reverse is harmless.

#### Run auto-finalize

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/handoff.py \
  auto-finalize \
    --file ~/.claude/thoughts/handoffs/{session-name}/{filename}.yaml \
    --outcome SUCCEEDED \
    --justification "all 7 task chain landed; tests 1591→1608; no open blockers"
```

Flags:
- `--outcome SUCCEEDED | PARTIAL_PLUS | PARTIAL_MINUS | FAILED` — required
- `--status complete | partial | blocked` — default `complete` (most
  agent-assigned finalizations end with the work-lifecycle done)
- `--assigned-by agent | user` — default `agent`; set to `user` only
  when the user explicitly overrode your pick
- `--justification "<one line>"` — required-in-practice. The one-line
  rationale that links the outcome to evidence (test counts, task
  ratios, blocker shape). **No `: ` (colon-space) inside** — YAML
  reads it as a nested mapping; use ` — ` or `;` instead.
- `--session <name>` — default: parent-dir of `--file` (matches
  Step 1's session-name → folder convention)
- `--json` — emit canonical envelope on stdout

What it does in one shot:
1. Rewrites the YAML frontmatter (`status`, `outcome`,
   `outcome_assigned_by`, optional `outcome_justification`) atomically
   (tempfile + rename). Body preserved byte-for-byte.
2. Re-indexes into the SQLite store via the same `save_handoff`
   upsert Step 3 used — no duplicate row.

The YAML stays the system of record; the store stays the queryable
index. `auto-finalize` keeps the two in sync without a separate Edit
+ save sequence.

#### Interactive override (optional)

If the user explicitly asks for a sign-off ("walk me through the
outcome before saving" / "let me pick"), use `AskUserQuestion` with
the rubric buckets as options and your recommended pick as the first
option. After the user responds, pass their pick to `auto-finalize
--assigned-by user`.

### Step 5 — Bridge durable learnings to brain

A handoff's `decisions` / `findings` / `worked` / `failed` sections are
durable learnings — exactly what the **brain** (long-term memory)
wants. The session-ephemeral sections (`goal` / `now` /
`done_this_session` / `next` / `blockers`) are deliberately NOT
bridged — they'd pollute brain's semantic index with state that decays.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/handoff.py \
  bridge --file ~/.claude/thoughts/handoffs/{session-name}/{filename}.yaml
```

This lists the brain capture-candidates. **Review them** — capture the
genuinely durable ones (a real decision, a confirmed pattern, a
learned-the-hard-way failure) via:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/brain.py capture "<text>"
```

Skip the ones that were only true for this session. (`bridge --apply`
captures the whole set at once — use it only when you're confident
every candidate is brain-worthy.)

### Step 6 — Confirm completion to the user

```
Handoff saved: ~/.claude/thoughts/handoffs/{session-name}/{filename}.yaml
Outcome: {OUTCOME}.

Resume in a new session by pointing it at that path, or run the
`resume` command with no args — it reads the latest handoff straight
from the store. The YAML file stays the system of record; the store
is just the index.
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

Query the handoff store for the most recent entry:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/handoff.py latest --json
```

- The envelope wraps a `handoff` object → read `data.handoff.file_path`
  in full (Step 2). That file is the system of record.
- `data.handoff == null` → the store is empty. Fall back to the filesystem:
  `ls -t ~/.claude/thoughts/handoffs/*/*.yaml 2>/dev/null | head -5` —
  present the list, or tell the user there's nothing to resume.

Use `handoff.py list [--limit N] [--session SID]` to browse beyond
just the latest.

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
- **Create asks for outcome.** Do not skip Step 4 of `create` — write the answer to the YAML frontmatter (the system of record) AND re-index via `handoff.py save` so the store mirrors it.
- **The store is plugin-owned + self-contained.** `handoff.py` + `_handoff.py` + `handoff.db` (at `~/.claude/.kaizen/data/handoff.db`; override `KAIZEN_HANDOFF_DB`) ship with the plugin — no external `~/.claude/scripts/` dependency. This skill was refactored off the recovered-but-lost `stores.py` in v1.36.0; the YAML files remain the durable system of record, the store is the queryable index.
- **Handoff and brain are distinct, bridged — not merged.** A handoff is verbose, time-bound *session-state*; brain holds distilled, durable *knowledge*. They have separate systems-of-record and query models, so they stay separate features. The `create` Step 5 bridge moves only what's durable (decisions / findings / worked / failed) across — it never collapses the two concerns into one store.
