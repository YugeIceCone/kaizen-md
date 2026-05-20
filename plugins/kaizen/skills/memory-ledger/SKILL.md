---
name: memory-ledger
description: "Catalog + status of every memory and continuity-of-session surface in kaizen. Verbs - catalog | status | flow. Triggers - 'memory ledger', 'memory surfaces', 'what's in memory', 'continuity flow', 'memory audit', 'where does memory live', 'project vs global state'."
metadata:
  version: "1"
---

# Memory Ledger

Single point of truth for **where memory lives** and **how
continuity flows** across a kaizen session. The ledger is
**observability-only** — it does not own, mutate, or consolidate
the underlying data; each surface keeps its own owner feature
(brain / backlog / handoff / gold / dxm / trace / inbox / chatlog).

Read the body in full before applying any verb. (Persona Directive:
skills must be read end-to-end.)

## Why a ledger?

Memory + continuity surfaces grew organically across 30+ features.
An agent asking "where does my state live?" or "what gets loaded at
session start?" used to have to read 8 SKILL.md files. The ledger
answers in one place via a declarative manifest
(`domain/memory-surfaces.yaml`) walked by the CLI.

Companion bounded-context discipline (BK-024): every surface
declares its `scope: project | global` so future features stop
leaking project-scoped data into global paths.

## Verbs

| Verb | What it does |
|---|---|
| `catalog` | Print every declared surface — name / owner / scope / path / auto-load status. Read-only. |
| `status` | Sample each surface on disk: exists? size? mtime? Flag drift between manifest + reality. |
| `flow` | Describe the continuity-of-session flow phase-by-phase — what loads at session start, mid-work, end-of-session, between sessions. |

All verbs support `--json` for machine-readable envelopes.

## The declared surfaces (today)

Sixteen surfaces across nine owner features:

- **brain** — Persona.md (global, auto-load), Notes/ (global), Journal/ (global)
- **better-memory** — MEMORY.md index (project, auto-load), `{project,feedback,user,reference}_*.md` entries (project)
- **backlog** — `backlog_ledger.md` (project, auto-load via memory siblings), `backlog.json` (project, source-of-truth)
- **handoff** — `handoff.db` SQLite (global, queryable index), `<session>/*.yaml` (global, system-of-record)
- **gold** — `<repo>/.kaizen/gold/*.md` (project)
- **dxm** — `<session>/events.jsonl` per-session (project)
- **trace** — unified `trace.jsonl` (project)
- **inbox** — `<repo>/.kaizen/inbox/` (project)
- **chatlog** — `<repo>/.kaizen/chatlog/<date>.md` (project)
- **project / global** — `CLAUDE.md` (project, auto-load) + `~/.claude/CLAUDE.md` (global, auto-load)

`catalog --json` returns the full structured list. `status` samples
each path; missing-when-expected, present-but-stale, and
scope-mismatch findings surface there.

## Scope discipline

Every surface declares `project` or `global`. The ledger is the
audit harness for keeping scope correct:

- **project**: `<repo>/.kaizen/` OR `~/.claude/projects/<repo-slug>/memory/`
- **global**:  `~/.claude/.kaizen/`

A surface with `scope: project` writing to a global path is a bug
(future iron-law candidate per BK-024 — the manifest is the data the
lint walks).

## Continuity flow (phase-by-phase)

`memory-ledger flow` walks the `continuity_flow:` block in the
manifest:

1. **session_start** — CC loads `claude-md-global`, `claude-md`,
   `brain-persona`, `auto-memory-index`, `backlog-ledger`.
2. **orientation** — agent reads handoff yaml + verifies state.
3. **mid_work** — gold / inbox / trace capture; backlog tracks.
4. **end_of_session** — handoff captures; bridge moves durables to brain.
5. **between_sessions** — daemon consolidates gold → brain;
   regens auto-memory index.

## What it deliberately does NOT do

- **Does not own data.** Each surface keeps its existing owner feature.
- **Does not mutate.** Read-only audit. Mutation lives in owner CLIs (`kaizen-brain`, `kaizen-backlog`, `kaizen-handoff`, etc.).
- **Does not consolidate paths.** Moving where data lives breaks the no-deletion rule + risks user-data loss. Catalog the layout, don't fork it.
- **Not a router.** `kaizen-memory-ledger catalog` returns paths; the agent invokes the owner CLI directly. Discovery + cluster orientation lives in `Skill(agent-brief)` (fresh agents) or `/kaizen:help` (surface inventory).

## Pairing with related features

- **brain** (`kaizen-brain`) — the most-referenced owner feature; the
  durable knowledge layer.
- **handoff** (`kaizen-handoff`) — owns the session-boundary
  continuity (resume / create / verify).
- **backlog** (`kaizen-backlog`) — owns the active-work ledger
  (BK-N items + memory-resident summary per BK-023).
- **better-memory** — owns the auto-memory dir; the daemon ticks
  `regen-index` to keep MEMORY.md in sync.
- **plugin-development** (`/kaizen:plugin-development`) — when adding
  a new persistent surface, register it here BEFORE shipping (or as
  part of the same commit) so the scope discipline is captured.

## Bypass

`KAIZEN_MEMORY_LEDGER_DISABLE=1` — silent no-op for any verb. Useful
in sandboxes that don't want the side-effect of scanning the user's
real memory dirs.
