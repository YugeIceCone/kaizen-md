---
name: kaizen-agent
description: Catalog + dispatch rubric for the 7 specialized kaizen subagents (backlog-curator / debt-auditor / implementer / karpathy-reviewer / memory-analyst / reviewer / skill-extractor). When agent dispatch is needed and the choice isn't obvious, load this skill — it maps task shape to the matching agent + provides the canonical Agent() prompt template. Pairs with subagent-driven-development (parent discipline) and dispatching-parallel-agents (when fan-out matters). Triggers on "which kaizen agent", "dispatch a kaizen subagent", "kaizen agent catalog", "should I use implementer or reviewer", "agent rubric", "which kaizen-* agent", "kaizen subagent picker".
---

# kaizen-agent — Subagent Catalog + Dispatch Rubric

## ⚠ Iron Law — read in full

Skip nothing. Each agent has narrow safety guarantees (kaizen-implementer
blocks destructive git ops; kaizen-memory-analyst is read-only; etc.).
Picking the wrong agent risks unsafe execution or wasted spawn cost.

## The 7 agents

| Agent | Read+Write? | Trigger shape | Tool surface |
|---|---|---|---|
| **kaizen-backlog-curator** | Read-only | "mine session for backlog items", "what should I file", end-of-session sweep | Read, Grep, Glob, Bash |
| **kaizen-debt-auditor** | Read-only | "find architecture violations", "tech debt audit", pre-sprint scan | Read, Grep, Glob, Bash |
| **kaizen-implementer** | Read + Write | TDD-disciplined multi-phase feature work in isolated worktree | Read, Edit, Write, Glob, Grep, Bash (RESTRICTED — blocks destructive git), TaskCreate / TaskUpdate / TaskList / TaskGet (for tracking phase progress) |
| **kaizen-karpathy-reviewer** | Read-only | "karpathy check", "review my diff" against the 4 principles | Read, Grep, Glob, Bash (diff/log/status/python only) |
| **kaizen-memory-analyst** | Read-only | Brain/memory file analysis, stale-ref detection, consolidation candidates | Read, Glob, Grep |
| **kaizen-reviewer** | Read-only | Pre-commit staged-diff review against 10 kaizen gate rules | Read, Grep, Glob, Bash |
| **kaizen-skill-extractor** | Read + Write | Transform proven patterns → standalone kaizen skill (`plugins/kaizen/skills/<name>/`) | Read, Write, Edit, Glob, Grep |

## Dispatch rubric

### By task shape

| Task | Agent |
|---|---|
| "Implement this 5-phase feature TDD-style in an isolated worktree" | **implementer** |
| "Audit this codebase for the worst architectural debt" | **debt-auditor** |
| "Review my staged diff before I commit" | **reviewer** |
| "Run karpathy 4-principle check" | **karpathy-reviewer** |
| "What backlog items should I file from this session?" | **backlog-curator** |
| "Analyze my brain/memory for promotion candidates + stale refs" | **memory-analyst** |
| "Extract this pattern into a reusable kaizen skill" | **skill-extractor** |

### By safety profile

- **Need write authority + risk of destructive git ops?** → **implementer** (Bash is pattern-restricted to block `merge / reset --hard / push / checkout / rebase / clean`).
- **Read-only analysis?** → any of: backlog-curator, debt-auditor, karpathy-reviewer, memory-analyst, reviewer.
- **Need to write a new skill file?** → **skill-extractor** (write authority scoped to `skills/<name>/`).

### When the choice isn't obvious

If the task could fit multiple agents, prefer:
1. **Most-specialized first** — karpathy-reviewer over reviewer for diff review.
2. **Read-only over Read+Write** — reviewer before implementer for borderline edits.
3. **Single-purpose over umbrella** — debt-auditor for pure audit; not implementer with "audit + fix".

## Canonical Agent() invocation patterns

### Implementer (multi-phase TDD feature)

```
Agent({
  description: "Implement Phase N — <short>",
  subagent_type: "kaizen:kaizen-implementer",
  prompt: "Build the gold auto-miner MVP, 5 phases, TDD per phase, " +
          "isolated worktree. Spec lives at <path>. Commit per phase " +
          "with the canonical kaizen body template.",
  isolation: "worktree"
})
```

### Debt-auditor (read-only scan)

```
Agent({
  description: "Architecture debt audit",
  subagent_type: "kaizen:kaizen-debt-auditor",
  prompt: "Scan plugins/kaizen for Onion-DDD layering violations + " +
          "8 coding-skills principle violations. Severity-rank. Report " +
          "what's actually broken vs nitpick."
})
```

### Reviewer (pre-commit gate)

```
Agent({
  description: "Pre-commit review of staged diff",
  subagent_type: "kaizen:kaizen-reviewer",
  prompt: "Audit the staged diff against the 10 kaizen gate rules + " +
          "brain-sourced severity overrides. Return green/yellow/red " +
          "verdict with itemized findings."
})
```

## What this skill does NOT do

- **Does not dispatch agents** — that's `Agent()` tool call semantics.
- **Does not provide the agents' bodies** — those live in
  `plugins/kaizen/agents/<name>.md`.
- **Does not enforce the pre-commit gate** — that's `kaizen-gatekeeper`.

## Triggers (when to load this skill)

- About to dispatch a subagent and unsure which one fits
- Want the canonical Agent() prompt template for a kaizen agent
- Need to know an agent's safety guarantees (tool surface, read-only-ness)
- Designing a new specialized agent — reference for shape conventions

## DON'T load when

- The choice is obvious (you already know which agent)
- You're not actually dispatching an agent (no Agent() call coming)
- Working on agent BODIES (load `Skill(agent-formatting)` instead)
