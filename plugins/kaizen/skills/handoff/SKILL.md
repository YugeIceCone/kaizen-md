---
name: handoff-managing
description: Creates and resumes session handoff documents for transferring work between sessions. Use to save context, resume from previous sessions, or manage handoff files.
metadata:
  version: "2.0"
---

# Handoff Managing

Lens-driven session handoff creation + resumption. The filesystem YAML
at `<handoffs_dir>/<session>/<ts>.yaml` is the system of record; the
SQLite store (`handoff.db`) is the queryable index.

- **`create`** — write a YAML handoff, index it, bridge durable learnings to brain.
- **`resume`** — read the latest (or specified) handoff, verify codebase still matches, propose a continuation plan.

If the user's intent is ambiguous, ask which one.

## Lens contract — the v2 manifest

Every subcommand declares its input + output schemas in
`skills/handoff/domain/handoff.yaml` (v2 manifest). The runtime
(`skills/workflow/scripts/schema_cli.py`, the "lens") validates I/O
before each call. Agents discover the contract by reading the manifest:

| Subcommand        | Role | Input schema | Output schema |
|---|---|---|---|
| `scaffold`        | git-driven YAML pre-fill | `schemas/scaffold-in.json` | `schemas/scaffold-out.json` |
| `create`          | typed one-shot YAML write + index | `schemas/create-in.json` | `schemas/create-out.json` |
| `verify`          | mechanical structural verification | `schemas/verify-in.json` | `schemas/verify-report.json` |
| `assess`          | deterministic outcome rubric | `schemas/assess-in.json` | `schemas/assess-out.json` |
| `auto-finalize`   | rewrite outcome + index, no AskUserQuestion | _stable_ | _stable_ |
| `save`, `latest`, `list`, `bridge`, `path` | pre-lens; still supported | _stable_ | _stable_ |

All `--json` output flows through the canonical envelope
(`_envelope.py`) — read `data.<field>` per the output schema; route on
`verdict` for go/no-go; check `counts` for severity buckets.

---

## Command: `create`

You are wrapping up the current session. Goal: produce a thorough but
**concise** handoff document so another agent (or you in a fresh
session) can resume without re-deriving context.

Two paths — pick based on whether you have the full structured
payload ready or need an incremental fill:

### Path A — `scaffold` then edit (default, interactive)

For when the YAML's qualitative content (decisions / findings /
worked / failed / next) is forming as you write. Saves ~20–50% of
manual token cost by pre-filling everything mechanical.

#### Step 1 — scaffold the YAML

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/handoff.py scaffold \
    --session "$(git rev-parse --show-toplevel 2>/dev/null | xargs -r basename)" \
    --goal  "one line — what this session accomplished. Shown in statusline." \
    --now   "one line — what the next session should do first. Shown in statusline." \
    --json
```

The scaffold subcommand:
- Derives the session name from `git rev-parse --show-toplevel`
  (override with `--session NAME`; falls back to ticket ID when
  you're working a ticket).
- **Mines the active Claude Code session JSONL** at
  `~/.claude/projects/<cwd-slug>/<sid>.jsonl` (most-recent-mtime
  file) to pre-fill:
  - `goal` ← latest `ai-title` line (the running session-summary
    AI maintains; usually a tight one-liner)
  - `now` ← top pending TaskList item (status pending/in_progress)
  - `done_this_session` ← per-completed-task entries (one per
    TaskUpdate→completed flip; subjects from the originating
    TaskCreate)
  - `next` ← pending TaskList items in creation order
  - `--since` default ← session_started_at (first JSONL timestamp,
    more accurate than 7.days.ago for in-session work)
  - `--goal` / `--now` flags become OPTIONAL — supply them only
    when overriding the mined defaults. Pass `--no-session-mine`
    to skip the JSONL pass (git-only pre-fill).
- Reads git state (`log --since`, `--diff-filter=A`, `--name-only`)
  to pre-fill `date`, `files.created`, `files.modified`.
- Writes the partial YAML to
  `<handoffs_dir>/<session>/YYYY-MM-DD_HH-MM_<slug>.yaml`.
  Slug auto-derived from `--goal` (kebab-case, ≤40 chars) unless
  `--description-slug` overrides.
- Returns envelope with `yaml_path`, `prefilled_sections[]`,
  `agent_must_fill[]` (typically reduced to `test`, `decisions`,
  `findings`, `worked`, `failed` when JSONL mining hit), `stats`,
  and `mined_summary` (ai_title / completed_count / pending_count /
  files_touched / skills_used / session_started_at) when mining
  succeeded.

Read the returned `agent_must_fill[]` — it lists exactly which
sections you have to write (typically `goal`, `now`, `test`,
`decisions`, `findings`, `worked`, `failed`, `next`).

#### Step 2 — fill the qualitative sections via Edit

Open the scaffolded YAML at `yaml_path` and Edit each field in
`agent_must_fill[]`. Keep the schema constraints in mind:

- `goal` + `now` — required, statusline-visible. **Do not** rename
  to `session_goal` / `objective` — the statusline parser only
  matches `goal:` and `now:`.
- `status:` + `outcome:` — leave as `partial` / `IN_PROGRESS`
  placeholders. Step 4's `auto-finalize` writes the real values.
- **No raw `: ` (colon-space) inside a prose value.** YAML reads it
  as a nested mapping and the body fails to parse. Use ` — ` or
  `;`, or quote the value. `file.rs:222` is fine (no space after
  the colon).
- Prefer file-path-with-line references (`crates/core/src/x.rs:222`)
  over inline code blocks.

#### Step 3 — get an outcome recommendation via `assess`

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/handoff.py assess \
    --file <yaml_path> \
    --test-delta <tests-after - tests-before, default 0> \
    --json
```

`assess` reads the YAML, computes 5 mechanical signals
(`done_count`, `blocker_count`, `next_blocking_count`,
`completed_ratio`, `test_delta`), walks
`domain/outcome-rubric.yaml`, and returns:

- `bucket` ∈ {SUCCEEDED, PARTIAL_PLUS, PARTIAL_MINUS, FAILED,
  NEEDS_AGENT}
- `method` ∈ {deterministic, fallback}
- `confidence`, `rationale`, full `signals` dict

When `method == "deterministic"` use the bucket as-is. When
`bucket == "NEEDS_AGENT"` (rubric fell through), self-assess against
the rubric in `domain/outcome-rubric.yaml` and pick the bucket
that fits — bias to the more conservative one when on the line.

See the **`decision-rubric`** skill for the rubric pattern in detail.

#### Step 4 — auto-finalize

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/handoff.py auto-finalize \
    --file <yaml_path> \
    --outcome <SUCCEEDED|PARTIAL_PLUS|PARTIAL_MINUS|FAILED> \
    --justification "one line — links outcome to evidence (test counts, task ratios, blocker shape)" \
    --json
```

What it does atomically:
1. Rewrites the YAML frontmatter (`status`, `outcome`,
   `outcome_assigned_by`, optional `outcome_justification`)
   tempfile-then-rename; body preserved byte-for-byte.
2. Re-indexes into the SQLite store via the same upsert as `save`.

Defaults: `--status complete`, `--assigned-by agent`. Set
`--assigned-by user` only when the user explicitly overrode your
pick via AskUserQuestion (rare — usually only when they ask for
sign-off).

**Subagent + autonomous contexts** (`/loop`, `/schedule`, ≥90% context
pressure): set `KAIZEN_HANDOFF_AGENT=1` to mark the agent-assigned
intent in the audit trail. The behavior is identical; the env knob
is documentation.

### Path B — `create` (one-shot, scripted)

For when you already have the full structured payload (e.g. a
sub-agent that returns a dict; an automated run; a previously
drafted handoff). Collapses scaffold + Step 2 into one call.

```bash
echo '{
  "session":   "demo",
  "goal":      "what this session accomplished",
  "now":       "what next session does first",
  "test":      "python3 -m unittest tests.test_x",
  "done_this_session": [
    {"task": "wrote tests", "files": ["tests/test_x.py"]},
    {"task": "shipped feature", "files": ["src/feature.py"]}
  ],
  "blockers": [],
  "questions": [],
  "decisions": [{"adopted-X-pattern": "rationale"}],
  "findings":  [{"key-finding": "details"}],
  "worked":   ["approach that worked"],
  "failed":   ["approach that failed and why"],
  "next":     ["first next step", "second"],
  "files":    {"created": ["..."], "modified": ["..."]}
}' | python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/handoff.py create --stdin --json
```

The `create` subcommand validates the payload against
`schemas/create-in.json` (required: `session`, `goal`, `now`),
generates valid YAML (handles `: ` colon-space escaping
automatically via `_quote_if_unsafe`), atomic-writes it, and indexes
in one shot. Returns `file_path`, `session_id`, `db_id`, `status`.

Then continue with **Step 3** (`assess`) and **Step 4**
(`auto-finalize`) from Path A.

### Step 5 — Bridge durable learnings to brain

A handoff's `decisions` / `findings` / `worked` / `failed` sections
are durable learnings — exactly what the brain (long-term memory)
wants. The session-ephemeral sections (`goal` / `now` /
`done_this_session` / `next` / `blockers`) are deliberately NOT
bridged.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/handoff.py bridge \
    --file <yaml_path>
```

This lists capture-candidates. **Review them** — capture the genuinely
durable ones (real decision, confirmed pattern, lesson-from-failure)
via `brain.py capture "<text>"`. Skip the ones that were only true for
this session. `bridge --apply` captures the whole set at once — use it
only when you're confident every candidate is brain-worthy.

### Step 6 — Confirm completion to the user

```
Handoff saved: <yaml_path>
Outcome: <BUCKET> (method=<deterministic|fallback>)

Resume in a new session by pointing it at that path, or run the
`resume` command with no args — it reads the latest handoff
straight from the store.
```

---

## Command: `resume`

You are resuming work from a prior handoff. Goal: load the latest
(or specified) handoff, **verify the codebase still matches**, then
propose a continuation plan.

### Step 1 — Locate the handoff

Three input modes:

**Mode A — Explicit path provided:** Skip the lookup. Read that
file in full immediately.

**Mode B — Ticket number provided** (e.g. `ENG-2124`):

```bash
ls -t ~/.claude/handoff/{TICKET}/ 2>/dev/null
```

- Zero files / dir doesn't exist → *"I can't find a handoff for
  that ticket. Provide a path or run with no args to use the latest
  DB entry."*
- One file → use it.
- Multiple → use the most recent (filename starts with
  `YYYY-MM-DD_HH-MM`).

**Mode C — No args:** Query the store for the most recent entry:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/handoff.py latest --json
```

- `data.handoff.file_path` → read in Step 2.
- `data.handoff == null` → store is empty. Fall back to
  `ls -t ~/.claude/handoff/*/*.yaml | head -5`.

Use `handoff.py list [--limit N] [--session SID]` to browse beyond
just the latest.

### Step 2 — Read the handoff fully + its references

Use **Read** without `limit`/`offset` so you get the whole thing.
Then read every artifact it links (research docs, plan docs,
mentioned files). Do this directly.

### Step 3 — Verify codebase state via `verify`

**This step replaces the legacy sub-agent fan-out.** One subcommand
returns a typed verification report (~1K tokens) instead of running
3–5 sub-agents (25–100K tokens):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/handoff.py verify \
    --file <yaml_path> \
    --json
```

The envelope's `data` matches `schemas/verify-report.json`:

- `file_checks[]` — per `done_this_session.files`:
  `{path, status, severity}` where status ∈ `{present, missing,
  modified, deleted}`. `severity: warn` for missing files.
- `pattern_checks[]` — per `worked:` / `failed:` entry:
  `{section, pattern, hit_count, severity, verdict}`. Verdict
  ∈ `{confirmed, stale, reintroduced, clean}`.
- `commit_delta` — `{count, since, commits[]}` covering the range
  from the handoff's `date` to HEAD.
- `qualitative_residue[]` — `{section, reason, items}` for sections
  the script cannot verify mechanically (`next`, `questions`,
  `decisions`, `findings`). **These are the items requiring your
  attention.**
- `verdict` ∈ `{clean, drift, regression}` — rolled up from
  severities per `verify-rules.yaml::verdict_rollup`.

Routing on the verdict:
- `clean` → proceed straight to Step 5 (the handoff's `next:` items
  are still valid).
- `drift` → reconcile in Step 4; surface the missing/stale items.
- `regression` → STOP. Surface to the user before any code change —
  a `failed:` pattern reappeared.

Only delegate to a sub-agent for genuinely qualitative checks
("is this finding still applicable?" — rare).

### Step 4 — Synthesize and present analysis

```
I've analyzed the handoff from {date}. Current situation:

**Original goal:** {goal from handoff}
**Original next step:** {now from handoff}

**Verify verdict:** {verdict}
- {N missing files, N modified, N commits since handoff}

**Done this session — verification:**
- {path}: {present | missing | modified}

**`worked:` patterns:** {N confirmed, N stale}
**`failed:` patterns:** {N clean, N reintroduced} ← escalate if any

**Qualitative residue (needs your attention):**
- next: {items}
- questions: {items}
- decisions: {items still in force?}
- findings: {items still valid?}

**Recent codebase changes since handoff** ({commit_delta.count} commits):
- {sha} {subject}
- ...

**Recommended next actions:**
1. {most logical next step from handoff `next:`}
2. {second priority}
3. {newly discovered task, if any}

**Issues identified:**
- {regression / conflict / missing dep, if any}

Shall I proceed with {recommended action 1}, or would you like to adjust?
```

### Step 5 — Get confirmation, then create the action plan

After the user confirms direction:

1. Use **TaskCreate** to convert handoff `next:` items + newly
   discovered tasks into trackable tasks.
2. Begin execution. **Mark each task `in_progress` when starting,
   `completed` immediately when done** (no batching).
3. Apply `worked:` patterns; avoid `failed:` ones.
4. Reference the handoff path in commits:
   `Refs: ~/.claude/handoff/.../X.yaml`.

### Common scenarios

| Scenario | Action |
|---|---|
| `verify` verdict=clean — nothing diverged | Proceed with handoff's `next:` items as written. |
| `verify` verdict=drift — files missing | Reconcile. Surface to the user before touching code. |
| `verify` verdict=regression — `failed:` pattern reappeared | STOP. Show the user the reintroduced pattern + ask before continuing. |
| Stale handoff — significant time / refactoring since | `commit_delta.count` will be large. Treat handoff as historical context, not the plan. |

---

## Notes for both commands

- **Be thorough**: more information beats less. Include both
  top-level objectives and lower-level details.
- **Avoid large code blocks / diffs**. Use `path/to/file.ext:line`
  references the next agent can follow when ready.
- **Resume verifies, never assumes.** `verify` is the new
  authoritative check; trust its typed report. Re-run it after any
  mid-resume changes to confirm verdict.
- **Create flow is subagent-compatible.** `auto-finalize` writes the
  outcome without `AskUserQuestion`. Subagent contexts AND
  `KAIZEN_HANDOFF_AGENT=1` interactive sessions use this path
  exclusively.
- **The store is plugin-owned + self-contained.** `handoff.py` +
  `_handoff.py` + `handoff.db` (at `~/.claude/.kaizen/data/handoff.db`;
  override `KAIZEN_HANDOFF_DB`) ship with the plugin — no external
  `~/.claude/scripts/` dependency. The YAML files remain the durable
  system of record; the store is the queryable index.
- **Handoff and brain are distinct, bridged — not merged.** A
  handoff is verbose, time-bound *session-state*; brain holds
  distilled, durable *knowledge*. They have separate
  systems-of-record and query models, so they stay separate
  features. The `create` Step 5 bridge moves only what's durable
  (decisions / findings / worked / failed) across — it never
  collapses the two concerns into one store.

## Related skills

- **`schema-driven-cli`** — the lens runtime + v2 manifest pattern.
  Read this if extending the handoff subcommand surface.
- **`decision-rubric`** — the rubric pattern that drives `assess`.
  Read this if tuning `outcome-rubric.yaml` or building a similar
  classifier.
