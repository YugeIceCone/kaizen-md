---
name: self-improving
description: Use to curate Claude Code's auto-memory into durable project knowledge. Analyze MEMORY.md for promotion candidates, graduate proven learnings to CLAUDE.md / .claude/rules/ / `~/.claude/brain/Notes/pref-*.md`, extract recurring solutions into reusable kaizen skills. Triggers on "review memory", "promote this learning", "extract a skill from", "graduate this pattern", "what has Claude learned", "memory health", "curate auto-memory". Pairs with `kaizen:remember` (capture), `kaizen:evolve` (consolidate), `kaizen:reflect` (think). Adapted from claude-code-skills/engineering-team/self-improving-agent — kaizen-namespaced and rewired to consume the brain/Persona/Notes structure already present.
version: 1.0.0
tags: [memory, curation, promotion, self-improvement, brain, rules]
---

# Self-Improving — auto-memory curator

Auto-memory captures. This skill curates.

Claude Code's auto-memory (v2.1.32+) automatically records project patterns, debugging insights, and your preferences in `~/.claude/projects/<slug>/memory/MEMORY.md`. The kaizen brain (`~/.claude/brain/`) adds a durable second layer. This skill adds the intelligence layer in between: analyze what Claude has learned, promote proven patterns into project rules, and extract recurring solutions into reusable skills.

## How this slots into kaizen

The brain / memory stack already has:

- **`kaizen:remember`** — explicit single-thought save: `/kaizen:remember <thought>` to inbox
- **`kaizen:process`** — mine unprocessed session jsonls into beliefs
- **`kaizen:evolve`** — weekly LLM-driven consolidation/reflection
- **`kaizen:reflect`** — think and consolidate
- **`kaizen:synthesize`** — pattern recognition across sessions
- **`kaizen:status`** — brain stats

`self-improving` adds the **promotion lifecycle** that connects auto-memory (ephemeral) → brain Notes (durable) → CLAUDE.md (enforced rule). The other kaizen brain skills are about *capturing* and *thinking*. This one is about *graduating* knowledge from notes to rules.

## Memory architecture (kaizen-augmented)

Where things live, in priority order:

- **`~/.claude/CLAUDE.md`** — global preferences. You write. Full-file load every session.
- **`./CLAUDE.md`** (project root) — project rules. You + `/kaizen:self-improving promote` write. Full-file load every session.
- **`~/.claude/brain/Persona.md`** — load-bearing directives + Top Beliefs. Loaded every session via SessionStart hook.
- **`~/.claude/brain/Notes/pref-*.md`** — beliefs with `confidence` + `sources_count` + `freshness`. Linked from Persona.md `## Top Beliefs`.
- **`~/.claude/projects/<slug>/memory/MEMORY.md`** — project learnings. Claude (auto) writes. First 200 lines loaded.
- **`~/.claude/projects/<slug>/memory/feedback_*.md`** — corrections specific to one project.
- **`.claude/rules/*.md`** — scoped rules. Loaded when matching files open.

The kaizen brain (`~/.claude/brain/`) is itself a git repo, so promotion to a `Notes/pref-*.md` is a tracked, reversible action.

## Promotion lifecycle (the core flow)

```
1. Claude discovers pattern → auto-memory (MEMORY.md)
2. Pattern recurs ≥2 sessions → review flags it as promotion candidate
3. You approve → promote graduates it:
     a. Project-scope rule? → .claude/rules/<topic>.md OR <project>/CLAUDE.md
     b. Cross-project belief? → ~/.claude/brain/Notes/pref-<slug>.md + link in Persona.md ## Top Beliefs
     c. Reusable workflow? → extract into a new kaizen skill at skills/<name>/SKILL.md
4. Pattern becomes enforced (rule) or invokable (skill) — not just a note
5. MEMORY.md entry archived → frees space for new learnings
```

## Five sub-flows (invoke explicitly)

This skill exposes five named flows. Use them by describing intent — the skill body routes:

### review — analyze MEMORY.md + brain for promotion candidates

Read all project-memory `feedback_*.md` + `audit_*.md` files plus `brain/Notes/pref-*.md`. Identify:

- Entries that recur across sessions (promotion candidates)
- Stale entries referencing deleted files / removed plugins / renamed paths
- Related entries that should be consolidated into one note
- Gaps between what MEMORY.md *knows* and what CLAUDE.md / Persona.md *enforces*

Output: a markdown report with recommendations. No writes.

### promote — graduate a learning

Take a specific learning from auto-memory or feedback notes and move it up the priority chain:

- Project-scope correction → `<project>/CLAUDE.md` OR `.claude/rules/<topic>.md`
- Cross-project belief → `~/.claude/brain/Notes/pref-<slug>.md` + link from Persona.md `## Top Beliefs`
- Codified rule → `kaizen:workflow::domain/git-discipline.yaml::pre_commit_gates[]` if it's enforceable

Each promotion:

1. Writes the destination file with proper frontmatter (`confidence` / `sources_count` / `freshness` for brain notes)
2. Removes or archives the auto-memory source
3. Updates Persona.md `## Top Beliefs` linkage if applicable
4. Records the promotion in `Persona.md ## Evidence Log` with a dated quote

### extract — turn a proven pattern into a kaizen skill

When a workflow recurs ≥3 times and warrants automation, extract it into a new skill under `kaizen/skills/<name>/`:

1. Identify the trigger phrases the user actually uses
2. Author SKILL.md with kaizen frontmatter conventions (name / description / triggers)
3. Add to `skills/workflow/domain/routines.yaml` if it becomes a routine stage
4. Cross-link from related kaizen skills
5. Run codegen + smoke /reload-plugins

### status — memory health dashboard

- Line counts (MEMORY.md vs 200-line cap; brain Notes total)
- Note freshness distribution (hardened / stable / fresh / stale)
- Promotion velocity (notes promoted in last N days)
- Stale candidates (notes with `sources_count=1` older than 30 days)

### remember — explicit save (delegates to `kaizen:remember`)

Don't duplicate. Use `/kaizen:remember <thought>` directly — that skill already owns capture.

## Sub-agents (for parallel dispatch)

- **`memory-analyst`** — read-only scan of MEMORY.md + brain. Returns the review report.
- **`skill-extractor`** — takes a promotion-ready pattern and authors the SKILL.md + frontmatter + references scaffold.

Both are dispatched via the Task tool with `subagent_type=general-purpose` and the named persona in the prompt.

## When to invoke

- After 5+ sessions on a project — review for accumulated promotion candidates
- When you notice yourself correcting Claude the same way twice — promote the correction
- When a debugging session yielded a reusable insight — extract it as a skill
- Before a major refactor — review what Claude already knows about the area
- Monthly maintenance — status check + prune stale notes

## Anti-patterns

- **Promote everything.** Most auto-memory entries are temporary context. Promote only what recurs ≥2 sessions.
- **Skip the evidence trail.** A promoted note without an Evidence Log entry has no recoverable rationale. Always link.
- **Skill-extraction for one-off solutions.** Extract only when the pattern recurs ≥3 times AND has clear trigger phrases.
- **Edit MEMORY.md by hand.** Claude writes it. Use this skill's promote flow instead.
- **Promote into a generic skill name.** A skill called "fix-things" gets nothing; one called "rust-orphan-module-detection" gets invoked.

## Related kaizen skills

- `kaizen:remember` — capture inbox
- `kaizen:process` — mine sessions for capture candidates
- `kaizen:evolve` — weekly LLM-driven consolidation
- `kaizen:reflect` — think
- `kaizen:synthesize` — cross-session pattern recognition
- `kaizen:workflow` — for promoting a rule into git-discipline.yaml or routines.yaml

## References

- Claude Code memory docs — Memory Architecture in CLAUDE.md / global / per-project
- `pskoett/self-improving-agent` — the upstream concept this skill adapts
