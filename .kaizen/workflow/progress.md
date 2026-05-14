# Architecture Log

> Append-only structured log of architectural-shape changes to the kaizen
> plugin. Format + discipline: `plugins/kaizen/skills/workflow/domain/git-discipline.yaml`
> (`architecture_log` block + the `structural_change_logs_to_progress` gate).
>
> What goes in: new MCP server / skill / indexer, file-set carve between
> skills, locked rule, plan executed end-to-end, dep-direction reversal.
>
> What does NOT: doc-only edits, typo fixes, lint cleanups, test-only
> changes, lockfile bumps, commit-message-body details.
>
> Lookup: rows are `date | scope | Δ LOC | summary` with no sha column —
> `git log --grep="<keyword from summary>"` resolves a row to its commit.
>
> **Backfill note:** this log was created 2026-05-14, resolving an
> agent-self-audit finding — `.kaizen/.gitignore` reserved the slot but
> the file had never been created. Rows dated before 2026-05-14 are a
> best-effort backfill of the major structural events still load-bearing
> for open plans, not a complete history; the pre-existing commit backlog
> was not reconstructed.

| date       | scope    | Δ LOC  | summary                                                                                     |
|------------|----------|--------|---------------------------------------------------------------------------------------------|
| 2026-05-12 | refactor | ~-1.8k | workflow + workflow-routing merged into one schema-driven skill (workflow-merge plan)        |
| 2026-05-12 | feat     | +465   | lint MCP server (lint_mcp.py) — ruff + ty as 7 Claude-callable tools (kaizen-lint-mcp plan)  |
| 2026-05-14 | chore    | +27    | created this architecture log — `.kaizen/.gitignore` slot now backed by a real file         |
| 2026-05-14 | refactor | -171   | carved onboard_index schema DDL + 4 migration fns into new onboard_schema.py module          |
| 2026-05-14 | docs     | +157   | added repo-root CLAUDE.md — Claude Code onboarding rulebook for the marketplace              |
