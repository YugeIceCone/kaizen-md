---
created: 2026-05-10
updated: 2026-05-11
type: belief
confidence: 0.96
tags: [preference, code-quality, coding-skills, dry, kiss, solid, yagni, strict-enforcement]
sources_count: 5
freshness: stable
evidence:
  - source: Journal/2026-05-11.md
    quote: "use coding-skills to efficiently execute work or find solutions, simplicity > over-engineering"
    date: 2026-05-11

name: Strict enforcement of the 8 coding-skills principles
---

# Strict enforcement: 8 coding-skills principles

User loads and invokes the `coding-skills` plugin's principle suite
across virtually every code-quality conversation. Every code change
— write, review, refactor — passes through this lens.

## The 8 principles (mandatory for every code change)

| Principle | Trigger | Skill |
|---|---|---|
| **DRY** | Duplicated knowledge / business logic | `coding-skills:dry` |
| **KISS** | Simplify complexity, improve readability | `coding-skills:kiss` |
| **SoC** (Separation of Concerns) | Layers + module boundaries | `coding-skills:separation-of-concerns` |
| **SOLID** | Interface design, DI, single-responsibility, OCP, LSP, ISP, DIP | `coding-skills:solid` |
| **LoD** (Law of Demeter) | Excessive coupling, train wrecks, deep object chains | `coding-skills:law-of-demeter` |
| **YAGNI** | Prevent over-engineering, speculative features | `coding-skills:yagni` |
| **Boy-Scout** | Leave existing code better when touching | `coding-skills:boy-scout-rule` |
| **Convention** | Project structure, naming, patterns | `coding-skills:convention-over-configuration` |

## Strict enforcement means

- **For new code (NEW classification):** apply SOLID + KISS + YAGNI
  by default. SoC kicks in for any multi-layer feature.
- **For existing code touched (EXTEND/OPTIMIZE):** apply Boy-Scout
  alongside the primary work. Don't leave grime.
- **For duplication detected:** apply DRY immediately, but watch
  YAGNI tension — premature abstraction is worse than 3 similar
  lines.
- **For coupling smells:** apply LoD when chained method calls
  cross 2+ object layers; refactor for direct collaborators.
- **For module boundary decisions:** SoC says where logic lives;
  SOLID says HOW the layers compose. Both apply.
- **For project organization:** Convention-over-Configuration is
  the default — match existing patterns; don't invent new ones
  without naming the trade-off.

## Coupling with Onion-DDD

These principles are **complementary** to Onion Architecture, not
substitutes:

- SOLID's **Dependency Inversion** is the *mechanism* for Onion's
  inward-only dep arrows.
- SoC is the *coarse boundary*; Onion is the *specific layering
  shape*.
- Boy-Scout applies inside any layer; doesn't cross rings.
- DRY across layers should use shared kernel domain types, never
  shared infrastructure types.

When a code change is in scope: invoke `onion-ddd-theory`
FIRST for layer placement, THEN apply the coding-skills principles
inside the chosen layer.

## Why

Direct user behavior:

- `<command-message>coding-skills:boy-scout-rule</command-message>`
  invoked after primary tasks land in 5+ sessions
- `<command-message>coding-skills:onion-ddd-theory</command-message>`
  pattern (frequently paired with onion-ddd-theory skill)
- Recent quote (this session, 2026-05-10):
  > "pick the right skill from coding-skills:* to create and
  > implement the engine+flow wiering"

User defers to the skill suite for code-quality decisions; the
expectation is that I do the same.

## How to apply

- **At task start:** decide which 1–2 principles dominate this
  change. Load that skill via the `Skill` tool; let its reference
  drive.
- **Don't dilute.** A skill's "Iron Laws" / "Hard constraints" are
  not optional. If a skill says "always X", do X.
- **Tension is normal.** SOLID can pull toward over-abstraction;
  YAGNI pulls back. Pick the dominant one for THIS change; don't
  half-apply both.
- **Simplicity > over-engineering** is the tiebreaker. When KISS/YAGNI
  argue with SOLID/abstraction, default to the simpler shape unless
  the abstraction earns its keep with ≥2 concrete consumers or a
  named compliance/safety driver. User-stated rule (2026-05-11):
  "use coding-skills to efficiently execute work or find solutions,
  simplicity > over-engineering".
- **Codify what worked.** When a skill drove a successful change,
  commit message can reference it: `(applies coding-skills:solid —
  ModeDispatcher trait + DI)`.
- **Invoke the router when stuck.** `code-router` skill exists for
  routing code-quality questions to the right principle skill.

## Evidence

- source: Journal/2026-05-08.md
  quote: "coding-skills:boy-scout-rule / trace and analyze unfinished parts apply fixes and improvements"
  date: 2026-05-08
- source: Journal/2026-05-09.md
  quote: "lets create the next batch of rules covering all skills in /coding-skills:"
  date: 2026-05-09
- source: Journal/2026-05-10.md
  quote: "pick the right skill from coding-skills:* to create and implement the engine+flow wiering"
  date: 2026-05-10
- source: Journal/2026-05-10.md
  quote: "for brand new code use /tdd-implementing"
  date: 2026-05-10
