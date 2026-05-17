---
name: self-improving
description: "Curate Claude Code's auto-memory into durable project knowledge. `review` flags promotion candidates, `promote` graduates one, `extract` turns a recurring pattern into a kaizen skill, `health` shows memory metrics. Triggers on \"review memory\", \"promote this learning\", \"extract a skill from\", \"what has Claude learned\", \"memory health\", \"curate auto-memory\", \"self-improve\"."
argument-hint: "review | promote <slug> | extract <pattern> | health"
allowed-tools: ["Read", "Glob", "Grep", "Write", "Edit", "Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-brain:*)"]
---

# /kaizen:self-improving — auto-memory curator

Load `Skill(kaizen:self-improving)` and follow its promotion-lifecycle
flow for the chosen subcommand.

## Subcommand: `$ARGUMENTS`

Parse the first token:

### `review` (no second arg)

Scan `~/.claude/projects/<slug>/memory/MEMORY.md` for promotion
candidates per `skills/self-improving/domain/lifecycle.yaml`. Emit
a ranked list:

```
candidate: <slug> (recurrence: 3 sessions, last: 2026-05-14)
  → suggested route: project rule | brain Note | new skill
  → why: <2-line summary of the pattern>
  → command: /kaizen:self-improving promote <slug>
```

Read-only. No mutation.

### `promote <slug>`

Graduate the named candidate per the route the user chose:

- **project rule** → write/append to `<project>/CLAUDE.md` or `.claude/rules/<topic>.md`
- **brain Note** → write to `~/.claude/.kaizen/brain/Notes/pref-<slug>.md` with full frontmatter (type, confidence, freshness, sources_count, evidence)
  - Then optionally link from `Persona.md ## Top Beliefs`
- **new skill** → run the `extract` flow (next subcommand)

Confirm with the user before any write that touches CLAUDE.md or
Persona.md.

### `extract <pattern>`

Convert a recurring solution into a new kaizen skill. Use
`Skill(kaizen:writing-skills)` for the scaffold; place under
`skills/<new-skill-name>/SKILL.md` per the canonical 11-file shape
in `skills/plugin-development/SKILL.md::Part 1`.

### `health`

Print memory metrics — entry count, last-modified, promotion-eligible
candidates, stale notes (no evidence in N days). Quick CLI:

```bash
kaizen-brain status   # via the consolidated brain CLI
```

Then summarize the relevant signals from `skills/self-improving/domain/lifecycle.yaml`.

## Iron laws

- **Never promote without user approval** when the target is
  CLAUDE.md or Persona.md — those are load-bearing.
- **Don't duplicate kaizen:remember/process/evolve** — this skill
  ADDS the promotion lifecycle on top of those captures.
- **Cite the source** — every promoted Note has `evidence:` with the
  observation that triggered promotion.

See `skills/self-improving/SKILL.md` for the full lifecycle + memory
architecture (PARA dirs, note schema, evidence format).
