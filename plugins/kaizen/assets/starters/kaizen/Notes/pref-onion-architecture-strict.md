---
created: 2026-05-10
updated: 2026-05-10
type: belief
confidence: 0.97
tags: [preference, architecture, onion, ddd, hexagonal, strict-enforcement]
sources_count: 5
freshness: stable
name: Onion-DDD architecture strict enforcement
---

# Strict enforcement: Onion Architecture / DDD layering

User invokes the Onion-DDD skill suite on virtually every
architectural conversation. The discipline is **mandatory**, not
optional, for any structural code change.

**Three-skill enforcement chain (split 2026-05-10):**

1. **`onion-ddd-theory`** — the theory base. Palermo's One Rule,
   DIP, four layers, anemic domain model, scaling patterns. **MUST
   be loaded first before either of the other two.**
2. **`onion-ddd-audit`** — the audit lens. Reviews existing code
   for Onion violations; produces findings list with severity +
   fix-shape suggestions. Routes remediation to `onion-ddd-plan`.
3. **`onion-ddd-plan`** — the remediation chain. Turns audit
   findings into a phased plan, executes task-by-task with TDD +
   coding-skills + verification. Owns the "Acting on the audit"
   canonical chain.

## What this means in practice

**Every layer-touching decision must respect inward-only dependencies:**

```
Domain (innermost)  ←  Application  ←  Infrastructure  ←  Presentation
```

- Domain layer: zero internal deps (leaf-pure kernel). Pure types
  + business logic, no I/O, no frameworks.
- Application: orchestrates domain via ports (traits). Talks to
  infrastructure only through trait abstractions.
- Infrastructure: adapters that fulfil port traits (database,
  HTTP, filesystem, LLM clients).
- Presentation: CLI, web handlers, IPC seams. Calls into
  application services.

**Forbidden patterns:**

- Domain types importing infrastructure (e.g. `Vec<RusqliteRow>` in
  a domain entity). Use port traits.
- Application code constructing infrastructure directly. Use
  dependency injection.
- Infrastructure depending on presentation. One-way only.
- Anaemic domain models — business rules belong in domain types,
  not in service classes.
- Repository methods that leak ORM types. Return domain types.

**Required when designing or refactoring:**

1. Identify which ring each new type belongs to BEFORE writing it.
2. Verify the import graph: only inward arrows.
3. New traits at boundaries (ports), new structs in adapters.
4. Bounded contexts get their own modules / crates; cross-context
   communication via published interfaces only.

**Structural lint rules MUST be authored** for every locked
architectural boundary, in the same commit as the carve-out. Three
families cover most cases: forbidden-import, topology / graph-level,
port-uniqueness. Tooling is project-specific (ast-grep,
import-linter, ArchUnit, go-arch-lint, custom ESLint) — the project's
own CLAUDE.md carries the naming convention and the live rule catalog.
The skill `onion-ddd-plan` carries the generic rule-shape skeleton.

## Why

User invoked `onion-ddd-theory` skill repeatedly across
2026-05-09 and 2026-05-10:

- "use the ast-grep skills to build rules covering and enforcing
  the concept of onion-architecture-ddd"
- "great lets create the next batch of rules covering all skills
  in /coding-skills:"
- Multiple skill invocations during games/, database/, runtime/
  carve-outs.

Pattern: every structural decision is preceded by an `onion-
architecture-ddd` skill invocation; every locked boundary gets an
ast-grep rule. Consistency across 5+ sessions.

## How to apply

- **Default to the skill chain.** When asked to design / refactor /
  review architecture: load `onion-ddd-theory` FIRST, then layer on
  `onion-ddd-audit` (for review) or `onion-ddd-plan` (for
  remediation) — depending on intent. Theory is required background
  for either of the other two; never skip it.
- **Verify dep direction in every PR-shaped review.** Run
  `ast-grep scan --filter onion-*` to catch boundary violations.
- **Lock new boundaries with ast-grep rules** as part of the
  carve-out commit, not as a follow-up.
- **Never silently soften the rule.** If a layer crossing seems
  necessary, surface it explicitly and ask before introducing it
  (anti-corruption layer, port extension, or rule revision).

## Evidence

- source: Journal/2026-05-09.md
  quote: "use the ast-grep skills to build rules covering and enforcing the concept of onion-architecture-ddd"
  date: 2026-05-09
- source: Journal/2026-05-09.md
  quote: "great lets create the next batch of rules covering all skills in /coding-skills:"
  date: 2026-05-09
- source: Journal/2026-05-10.md
  quote: "<command-message>onion-architecture-ddd</command-message> [invoked 4+ times]"
  date: 2026-05-10
- source: <your project> CLAUDE.md
  quote: "Workspace tree (canonical levels) ... Onion-DDD strict ... bounded-context boundary"
  date: 2026-05-09
- source: <project> rules/lints/onion-*.yml
  quote: "11 onion-* lint rules already in production use"
  date: 2026-05-08
