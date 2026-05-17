---
created: 2026-05-10
updated: 2026-05-10
type: observation
tags: [workflow, onboarding, orientation]
sources_count: 2
name: Read named orientation files first
---

# User's standard orientation pattern: read named files first, then act

Before delegating substantive work in a session, user lists the
specific files to read for orientation. The shape is consistent:

1. **Read N specific files** (named explicitly, not inferred) — plan
   files, handoff docs, architecture-log entries, named source
   directories.
2. **Then apply quick wins / propose changes** — never propose
   before reading.
3. **For bigger work:** walk and read in full first, *then* write a
   plan.

The list of files is the user's curated context for the task —
treat it as load-bearing, not a suggestion.

## How to apply

- When the user opens with `orientation:` followed by a file list —
  drop everything else, read those files in full, summarize state,
  then ask or proceed.
- When the user gives a directory with the `@<path>/` file-reference
  convention — walk + read first, then propose changes. Don't
  propose-then-read.
- Never skip the orientation read. The named files encode the
  project's current state — speculation in their place is the
  common failure mode.
- The exact paths the user names will be **project-specific** (e.g.
  <project> uses `plans/<name>.md` + `.workflow/progress.md` defined in
  its `CLAUDE.md`; another project's orientation list will look
  different). The pattern is the same — the paths follow the
  project's own conventions, not a universal layout.

## Examples (illustrative — paths are project-specific)

<example project="<your project>">

> **[20:21] User:** orientation: plans/2026-05-10-session-handoff.md
> 2026-05-10-onion-f1-executive-carveout.md .workflow/progress.md

Three named files: a plan, a phase-specific plan, the architecture
log. Read all three in full before any proposal. (`.workflow/`
is <project>'s architecture-log directory, defined in its `CLAUDE.md`
— other projects will name theirs differently.)

</example>

<example project="<your project>">

> **[02:15] User:** ok lets not do that but apply quick wins then
> walk and read @crates/flows/src/ in full then write a new plan

The `@<dir>/` form is Claude Code's file-reference convention (not
<project>-specific) but the path `crates/flows/src/` IS — it's the
<your project>'s flows crate. The pattern (walk + read before
planning) generalizes; the path doesn't.

</example>

## Evidence

- source: Journal/2026-05-09.md
  quote: "orientation: plans/2026-05-10-session-handoff.md 2026-05-10-onion-f1-executive-carveout.md .workflow/progress.md"
  date: 2026-05-09
- source: Journal/2026-05-10.md
  quote: "ok lets not do that but apply quick wins then walk and read @crates/flows/src/ in full then write a new plan"
  date: 2026-05-10
