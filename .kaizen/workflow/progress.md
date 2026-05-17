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
| 2026-05-14 | refactor | ~0     | carved iron-laws.yaml + skeleton into new skills/iron-laws/ skill (iron-laws plan, phase 1)  |
| 2026-05-14 | feat     | ~+1.6k | iron-laws skill complete — SSOT registry + loader + codegen + checker + CLI + MCP + drift gate |
| 2026-05-17 | fix      | +50    | BK-013 — dxm-event.sh _session_jsonl fallback when stdin lacks session_id (fixes silent PreCompact/SessionEnd/SubagentStop/Notification drops) |
| 2026-05-17 | fix      | +25    | BK-014 — precompact-snapshot.sh runs backup sync + emits honest systemMessage with real tarball path (was backgrounded `&` + wrong hardcoded path) |
| 2026-05-17 | feat     | +85    | BK-015 — context.get_usage_summary peak-aware reader (walks all assistant turns, detects compact via isCompactSummary marker, returns current+peak+peak_pre_compact+compact_count) |
| 2026-05-17 | feat     | +35    | context_notifier consumes BK-015 — payload + envelope now include peak_tokens, peak_pct, peak_pre_compact, compact_count (post-compact red-zone signal survives current-zone drop) |
| 2026-05-17 | fix      | +5     | handoff verify — skip pattern_check for narrative bullets (em-dash separator). Real-world: 8 stale false-positives → 0 against handoff #8 |
| 2026-05-17 | feat     | +25    | BK-016 — handoff scaffold mined_summary carries peak_tokens, peak_context_pct, peak_pre_compact, compact_count from BK-015 (compact-resilient handoff signal) |
| 2026-05-17 | perf     | +30    | session-inject-context: UserPromptSubmit trims to git-only (workflow/handoff/plans/project-memory injected once at SessionStart). Saves ~1.4KB per prompt × N turns. |
| 2026-05-17 | refactor | +25    | _dxm_emit.emit_subcommand_complete DRY helper — migrate 8 callers in handoff.py + intent.py to centralized {tool,sub} naming convention. Rename + typo safety by construction. |
| 2026-05-17 | perf     | +15    | context.py `line` subcommand emits pre-formatted statusline segment in 1 spawn (was 5). 160ms → 100ms per statusline render (37% faster). |
| 2026-05-17 | perf     | +95    | pretooluse_trace.py — consolidates 4 python3 spawns into 1 per PreToolUse fire. ~120ms → ~25ms per tool call × 1000s of calls/session. |
| 2026-05-17 | perf     | +85    | posttooluse_trace.py — same fix on PostToolUse (4 spawns → 1). Companion hot-path saving. |
| 2026-05-17 | perf     | +120   | stop_backlog_reminder.py — Stop hook 3 spawns → 1. Also drops a redundant backlog.json double-read + adds KAIZEN_BACKLOG_DISABLE bypass for hook discipline parity. |
| 2026-05-17 | perf     | +60    | userprompt_inbox.py — UserPromptSubmit inbox capture 4 spawns → 1. KAIZEN_INBOX_DISABLE bypass parity. |
| 2026-05-17 | perf     | +80    | intent_userprompt.py — UserPromptSubmit intent matcher 3 spawns → 1. Existing test_intent_scan_hook.py passes unchanged. |
| 2026-05-17 | perf     | +130   | posttooluse_bash_commit.py — PostToolUse(Bash) git-commit suggester 4 spawns → 1. KAIZEN_BACKLOG_COMMIT_DISABLE bypass parity. |
| 2026-05-17 | perf     | +90    | subagentstop_trace.py — SubagentStop 5 spawns → 1. Emits both generic + detail trace events from one process. |
| 2026-05-17 | feat     | +220   | session-intake — SessionStart hook + session_mode CLI + bin wrapper. 1-time QA at session start asks agent to AskUserQuestion for mode (loop/workflow/neither); choice persisted in .kaizen/session-mode.json. KAIZEN_SESSION_INTAKE_DISABLE bypass. Gates: skips when mode set / loop active / workflow in-progress. |
| 2026-05-17 | feat     | +95    | session-intake bundles — Q2 added (multiSelect): Simplicity / Structure / Process / Karpathy. Structure expanded to full architecture family (SOLID, SoC, LoD, Onion-DDD, Hexagonal, Clean, DIP, Bounded-Contexts). --bundles flag expands to skills[] with dedupe. `bundles` subcommand for introspection. Fixed `sof` → `soc` typo. |
| 2026-05-17 | feat     | +60    | /kaizen:mode slash command — explicit alternative to auto-fire SessionStart intake. Takes `loop|workflow|neither` and routes to the disciplines QA (Q2 only); no-arg falls back to full QA. |
| 2026-05-17 | feat     | +90    | 3 new intent rules (start-loop / start-workflow / set-mode-generic) so the agent surfaces /kaizen:mode mid-session when user's phrasing implies it. Empirically fires on "iterate on this", "use a workflow", "harden the plugin", "configure this session", etc. |
