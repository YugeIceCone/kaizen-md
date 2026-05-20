---
name: brain
description: Capture, search, promote, audit, evolve, AND surgically edit the kaizen Second Brain. Schema-driven (yaml + jsonschema), Node+Flow engine, MCP-exposed, hook-automated. Block-level addressing via heading-path means zero-roundtrip memory edits — use `kaizen-brain blocks` / `show --block X` / `edit --block X` INSTEAD OF `Read`+`Edit` on Persona.md / Notes / Inbox files (8× fewer tokens per read). Triggers on "edit persona top beliefs", "show evidence log", "read memory section", "extract block from note", "kaizen-brain blocks", "kaizen-brain show", "kaizen-brain edit", "remember this", "save this to brain", "capture belief", "promote note", "audit memory", "brain status", "brain stats", "evolve brain".
---

# Brain — Schema-driven Second Brain inside kaizen

## ⚠ Iron Law — read in full

Skip nothing. The four entity types (world-fact / belief / observation /
experience) + tier rules (brain vs project-memory) + promotion criteria
only hold together. Skimming to a flowchart produces wrong-tier writes
and lost beliefs.

## What this skill provides

Five surfaces — slash command, bin wrappers, MCP tools, hooks,
schema:

### Capture

- `kaizen-brain capture <text>` — slash command
- `kaizen-brain capture <text>` — bin wrapper
- `brain_capture(text, type_hint?, confidence?, tier_hint?, subject?)` — MCP tool
- `UserPromptSubmit` hook — detects "remember this" / "save this" /
  "for the record" / "brain dump" triggers and surfaces a capture hint
  to the agent (advisory, no auto-write)

### Search + index

- `kaizen-brain status` / `brain_status` MCP — file counts per subdir
- `kaizen-brain index <subcommand>` (where subcommand ∈
  `index|search|stats|get|path|clear`) — SQLite +
  sentence-transformers over Notes / Projects / People / Areas
- `brain_search(query, top_k, type, subdir, min_confidence)` MCP
- `brain_index_build` / `brain_index_stats` MCP

### Promote (project-memory → brain)

- `kaizen-brain promote` (dry-run) / `--apply`
- `brain_promote_preview` / `brain_promote_apply` MCP
- Criteria: `sources_count >= 2` OR explicit `promote: true`

### Audit (end-of-session discovery)

- `kaizen-brain audit` (dry-run) / `--apply` (writes drafts to Inbox)
- `brain_audit(apply, limit_commits, limit_inbox)` MCP
- `SessionEnd` hook auto-fires (apply=true) — drafts land in
  `<brain>/Inbox/draft-<today>-<slug>.md`; user reviews next session.

### Evolve (consolidation + freshness)

- `kaizen-brain evolve --stale-days N`
- `brain_evolve(stale_days)` MCP
- Reports duplicates, freshness drift, Persona.md ↔ Notes drift.
  NO auto-writes — read-only report.

### Block ops — zero-roundtrip memory edits ⭐

**ALWAYS prefer these over `Read` / `Edit` for any file under
`~/.claude/.kaizen/brain/`.** Heading-path addressing lets you target
exactly one block of a Markdown file in one CLI call — no whole-file
load, no fragile `old_string` matching.

- `kaizen-brain blocks --file <md>` — list addressable heading-paths
  (returns `[{path, level, start, end}]`; ~10 lines for a Persona.md)
- `kaizen-brain show --file <md> --block "<path>"` — extract one block
  (e.g. `--block "Top Beliefs"` returns just those 14 lines, not the
  whole 70-line Persona.md)
- `kaizen-brain edit --file <md> --block "<path>" --replace "<body>"` —
  atomic in-place full-block swap (tempfile + rename)
- `kaizen-brain edit --file <md> --block "<path>" --append "<line>"` —
  append one list-item (caller supplies marker: `- foo` or `4. bar`)

Block path = heading text `/`-joined: `Persona/Top Beliefs`. Trailing-
segment match (just `Top Beliefs`) works when unambiguous.

**Token win:** `Read Persona.md` ≈ 1,250 tokens; `brain show --block
"Top Beliefs"` ≈ 150 tokens. **8.3× less** per memory read. Edits
similarly skip the Read→Edit roundtrip.

**When NOT to use:** files without Markdown headings (a `## section`
must exist to be addressable). Capture / search / promote stay on
their own subcommands above.

## Schema

Lives at `schemas/brain/`:

- `entity-types.yaml` — 4 types + target dirs + required frontmatter +
  detection triggers + priority order
- `routing.yaml` — tier rules (brain vs project-memory) + file rules
  (per-tier per-type destination templates) + promotion rules +
  capture/skip rules
- `schemas/note.schema.json` — JSON Schema for Note frontmatter;
  beliefs require `confidence` via `allOf if/then`

All routing decisions read from yaml. To change tier-selection rules
or add a new entity type, edit yaml — no code changes.

## Node+Flow engine

Every operation is a PocketFlow AsyncNode graph (`scripts/workflow/flow.py::AsyncNode`).
The flows are linear today but the engine supports action-key
branching when needed:

```text
capture:  ParsePrompt → DetectType → Journal → Route → Dedup → Write → Report
index:    Discover → Embed → Upsert → Report
promote:  Scan → Filter → Preview → Apply → Report
audit:    ScanSources → ExtractCandidates → Classify → Inbox → Report
evolve:   LoadNotes → FindDuplicates → CheckFreshness → ScanPersonaRefs → Report
```

Each node has one responsibility, three async methods (`prep_async`,
`exec_async`, `post_async`), and writes its outputs to the shared
`store` dict.

## Path resolution

```
Brain root:   KAIZEN_BRAIN_DIR (default ~/.claude/.kaizen/brain)
Index db:     <brain_root>/brain.db (mirrored as _paths.BRAIN_DB)
Project mem:  ~/.claude/projects/<cwd_slug>/memory
```

`KAIZEN_BRAIN_DIR` accepts literal `$HOME` references plus `~` expansion.
Legacy envs (`REMEMBER_BRAIN_PATH` / `KAIZEN_BRAIN_PATH` / `KAIZEN_BRAIN`)
are NO LONGER consulted as of v1.38.0 — single-user clean cut. To migrate
an existing brain from the legacy location, run `kaizen-brain migrate apply`.

## Capture decision tree (project-memory vs brain)

The routing flow walks `routing.yaml::tier_rules` in order; first
match wins:

1. **explicit-project-marker** — "for this project" / "in this codebase"
   → project-memory
2. **explicit-cross-project-marker** — "always X" / "every project" /
   "globally" → brain
3. **experience-and-observation-always-brain** — structurally only
   brain has the right shape for these → brain
4. **high-confidence-belief-goes-brain** — belief with confidence >=
   0.85 → brain
5. **low-confidence-or-narrow-fact-project** — default for narrow
   facts and beliefs → project-memory
6. **default** — catch-all → project-memory

The agent can override via `tier_hint=brain|project` or `type_hint=...`.

## Journal-first discipline

`JournalNode` appends the verbatim quote to
`<brain>/Journal/<today>.md` BEFORE any L2 file is written. The
journal entry's filesystem path becomes the `source` field on every
`evidence:` row added to L2 notes. This means:

- Every belief / fact can trace back to the conversation that
  produced it (audit trail).
- Re-deriving a belief produces a new evidence row, bumping
  `sources_count` (which is the promotion gate).
- The journal is the source-of-truth for "when / why did this
  belief land".

## Tests

Each module has its own test file:

- `tests/test_brain_core.py` — paths, config, type detection, fm
  parse/serialize (~30 tests)
- `tests/test_brain_capture.py` — full flow + routing + CLI (~18)
- `tests/test_build_index.py` — index build, search, stats (~13)
- `tests/test_brain_promote.py` — promotion criteria + apply (~10)
- `tests/test_brain_audit.py` — extraction patterns + sources (~8)
- `tests/test_brain_evolve.py` — duplicates / freshness / persona (~8)

Tests sandbox the brain root via `KAIZEN_BRAIN_DIR=<tmp>` so no
real-brain writes occur during CI.

## Hooks

- `SessionEnd`: `brain-session-end.sh` auto-fires the audit with
  `--apply`. Bypass: `KAIZEN_BRAIN_AUDIT_DISABLE=1`. Drafts land in
  `<brain>/Inbox/` for next session's review.
- `UserPromptSubmit`: `brain-user-prompt.sh` detects capture-intent
  phrases in the user prompt and surfaces a stderr hint. Bypass:
  `KAIZEN_BRAIN_PROMPT_DISABLE=1`.

## What this REPLACES

The retired `remember-md` plugin's Node.js scripts (~2030 LOC in
`scripts/{schema,build-index,promote,extract,append-evidence,
evolution-log,user_prompt,session_start,build-context,config}.js`).

The Node.js scripts remain in place under `scripts/` for back-compat
with the existing `init/process/evolve/reflect/synthesize` skills.
B5+ adds a `legacy-` rename pass; until then, BOTH stacks coexist.

## When NOT to use

- Single-file edit-and-go work without learnings to capture.
- Code-pattern questions ("how does X work in this codebase?") —
  use `kaizen-onboard` semantic search instead.
- Project-specific config / paths / commands — those live in CLAUDE.md,
  not the brain.

## Quick reference

```bash
# Capture
kaizen-brain capture "we decided to use sqlite for indexers"
kaizen-brain capture "user prefers terse output" --type belief --confidence 0.9 --tier brain

# Search
kaizen-brain index search "sqlite"
kaizen-brain index search "preference" --type belief --min-confidence 0.85

# Promote project entries that grew to sources_count>=2
kaizen-brain promote                    # dry-run preview
kaizen-brain promote --apply

# Audit last session for missed captures
kaizen-brain audit --apply              # writes drafts to Inbox

# Evolve — duplicates / freshness / persona drift
kaizen-brain evolve --stale-days 30
```
