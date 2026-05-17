---
name: Use HARD-GATE blocks to codify durable rules
description: When writing a rule that must be read in full (CLAUDE.md, SKILL.md, plan docs), wrap each rule in <HARD-GATE></HARD-GATE> with imperative language, explicit applies-to / does-NOT-apply-to clauses, and at least one counter-example. The wrapper signals "no skimming"; the structure signals "no ambiguity".
type: belief
confidence: 0.85
tags: [preference, documentation, hard-gate, claude-md, skills, codification]
sources_count: 1
freshness: stable
created: 2026-05-15
updated: 2026-05-15
---

# Use HARD-GATE blocks to codify durable rules

When a rule needs to be **read in full** — not skimmed, not partially
applied, not selectively quoted — wrap it in `<HARD-GATE></HARD-GATE>`
with imperative language and explicit scope clauses.

> **[2026-05-15] User:** use \<HARD-GATE\>\</HARD-GATE\> to force reads and make the language 100% accurate

The wrapper exists because LLMs (and humans) default to skim-and-jump
behavior: read the description, jump to the example, skip the prose
between. HARD-GATE blocks fight that default by signalling "this whole
block is load-bearing — read every line."

## Why

A regular markdown section invites:

- Read the heading, infer the rest from prior knowledge.
- Skim to the table or example, treat surrounding prose as decoration.
- Apply the rule selectively to the case at hand, ignoring its scope
  clauses.

HARD-GATE removes the ambiguity. The user observed this directly when
the first draft of `freebay/CLAUDE.md`'s code-organization section was
imprecise about pipeline-vs-adapter crate shape — "i dont see a flow.rs
in src" surfaced a reader (or future agent) being misled by a rule
that didn't bound its scope. Rewriting as HARD-GATE blocks with
explicit applies-to / does-NOT-apply-to clauses fixed it.

## How to apply

Every HARD-GATE block has four mandatory parts:

1. **Imperative subject heading** — names the rule, not the topic.
   `### Module-split threshold — UNIVERSAL`, not "Module Splitting".
2. **Scope clause** — `**Scope:** applies if and only if ...` OR
   `**Scope:** every X in every crate`. Bounds the rule's reach
   before stating the rule.
3. **The rule** — imperative, numbered conditions, no hedging
   ("MUST", "MUST NOT", not "should consider").
4. **Counter-example or live example** — at minimum a `**Live example:**`
   path. If the rule has a non-trivial scope, also include a
   `**Counter-example (correctly NOT in scope):**` path so the reader
   sees what the rule does NOT cover.

Example shape (from `freebay/CLAUDE.md`):

```markdown
<HARD-GATE>

### One impl per file — UNIVERSAL

**Scope:** every `pub mod` in every crate, regardless of crate role.

**Rule:** a single `.rs` file declares AT MOST ONE of:
- a `pub struct` + its `impl` blocks...
- a `pub trait` + its blanket impls + a single `Mock*` impl...

**Live example:** `crates/assets/src/nodes/` (one Node per file).

</HARD-GATE>
```

## When to use HARD-GATE vs plain markdown

| Use HARD-GATE | Use plain markdown |
|---|---|
| Architectural rule (forbidden imports, file layout) | Reference info (env vars, paths) |
| Discipline that must apply to every commit | Status / activity log |
| Pattern with a counter-example (when it does NOT apply) | Single-purpose how-to |
| Rule that has been violated before | Background prose / motivation |

The cost of HARD-GATE: visual weight. Reserve for rules the reader
genuinely cannot afford to skim. If everything is a hard-gate, nothing
is.

## Companion rule — strip volatile data

A HARD-GATE block describes durable shape, not point-in-time state.
Commit SHAs, LOC counts, date-stamped status — these belong in
`progress.md` / `git log` / `git notes`, not inside a HARD-GATE
block. The `freebay` pre-commit gate's `no_volatile_data_in_claude_md`
check enforces this; expect similar checks in other projects.

## Anti-patterns

- ❌ HARD-GATE without a scope clause — leaves the reader guessing
  whether the rule applies to their case.
- ❌ Counter-example missing when scope is non-trivial — the reader
  reaches the wrong conclusion in adjacent cases.
- ❌ HARD-GATE wrapping a status update or session-discovery note —
  dilutes the signal of all other HARD-GATE blocks in the file.
- ❌ Soft language inside HARD-GATE ("typically", "usually") — the
  whole point is unambiguous imperatives.

## Evidence

- source: Journal/2026-05-15.md
  quote: "use <HARD-GATE></HARD-GATE> to force reads and make the language 100% accurate"
  date: 2026-05-15
