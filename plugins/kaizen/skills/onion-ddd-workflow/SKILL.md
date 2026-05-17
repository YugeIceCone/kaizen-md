---
name: onion-ddd-workflow
description: Use when designing, auditing, or remediating layered codebases (Onion / Clean / Hexagonal / Ports & Adapters / DDD). Single skill consolidating the prior `onion-ddd-theory` + `onion-ddd-audit` + `onion-ddd-plan` chain. Triggers on "onion architecture", "clean architecture", "hexagonal architecture", "ports and adapters", "DIP vs DI", "Palermo's rule", "DDD layering", "domain layer", "bounded context", "anemic domain", "layer audit", "Onion remediation", "audit findings", "carve-out", "structural lint". Skill body MUST be read end-to-end before applying any section.
version: 3.0.0
---

# Onion / DDD — Workflow (Theory → Audit → Plan → Execute)

Single end-to-end skill for designing, auditing, and remediating layered
codebases where the **domain model is the core** and every other layer
exists to support it. Replaces the three-skill chain (`onion-ddd-theory`,
`onion-ddd-audit`, `onion-ddd-plan`) with one cohesive document.

## Required skills (load before applying this one)

This skill *uses* but does not *contain* the following — load each via
the `Skill` tool when you reach the matching section:

- **`coding-skills`** (the bundle: `coding-skills:kiss`, `:dry`, `:yagni`,
  `:solid`, `:separation-of-concerns`, `:law-of-demeter`,
  `:boy-scout-rule`, `:convention-over-configuration`).
  Required during every code edit produced by the plan/execute step.
  The four most load-bearing for layer-boundary work: SOLID (DIP is
  *the* Onion rule), YAGNI (don't introduce ports for hypothetical
  consumers), DRY (port duplication is the highest-leverage finding
  type — grep for parallel trait defs first), Boy-Scout (fix small
  layering smells next to symbols you're already touching).
- **`superpowers:writing-plans`** — turn the audit's findings into a
  phased plan with explicit file targets, code, and verification
  commands. Required before any code edits.
- **`superpowers:executing-plans`** (or `superpowers:subagent-driven-development`
  if subagents are available) — drives the plan task-by-task with
  verification at each step. Required for the execute step.
- **`superpowers:test-driven-development`** — the discipline. Or
  `tdd` / `tdd-implementing` for the full operational runbook
  (tiering / EDD / phase pipeline). Required during each task in the
  execute step. Onion remediation is a code-relocation operation that
  introduces architectural surface needing test coverage: new ports
  → contract tests, new adapters → impl-against-port tests, lifted
  ports → regression-as-RED on the existing suite, pure relocations
  → regression-as-RED only (no new test). See Part 3 step 3 for the
  per-finding-type breakdown.
- **`verify-before-execution`** — the RED-GREEN gate that wraps
  every architectural change in Part 3. Part 3 step ⓹ ("Verification
  commands") is the architectural-specific instantiation of this
  skill's GREEN matrix; the skill provides the general discipline
  (RED before apply, GREEN after, demote-with-named-failing-check on
  any gate failure) plus the integration rules across other flows.

Keep these on hand; they are referenced by section name below.

## End-to-end workflow trace

The full pipeline this skill drives, from a triggering prompt to a
verified architectural change:

```mermaid
flowchart TB
    trig["User prompt<br/>(triggers in description)"]
    load["Load this skill in full<br/>(Iron Law)"]

    subgraph p1["PART 1 — Theory"]
        t1["Internalise One Rule + DIP<br/>+ 4 Layers + decision rules<br/>+ Explicit Architecture extensions"]
    end

    subgraph p2["PART 2 — Audit"]
        a1["Run grep one-liners<br/>(domain framework imports,<br/>port mimicking SDK, etc.)"] --> a2["Classify findings<br/>P0 / P1 / P2 / P3"]
        a2 --> a3["Emit audit report<br/>(per output template)"]
    end

    decide{"P0 or P1<br/>findings?"}

    subgraph p3["PART 3 — Plan + Execute (sub-skill chain)"]
        direction TB
        s1["⓵ superpowers:writing-plans<br/>→ phased plan w/ verification cmds"]
        s2["⓶ superpowers:executing-plans<br/>→ task-by-task execution"]
        s3["⓷ superpowers:test-driven-development<br/>→ RED-GREEN per task<br/>(new port → contract test;<br/> lifted port → regression-as-RED;<br/> new adapter → impl-against-port test;<br/> pure relocation → regression-only)"]
        s4["⓸ coding-skills:{kiss,dry,yagni,solid,<br/> separation-of-concerns,law-of-demeter,<br/> boy-scout-rule,convention-over-configuration}<br/>→ applied per edit"]
        s5["⓹ Verification commands<br/>(leaf-pure grep, dep-graph diff,<br/> port-uniqueness check, lint-rule scan)"]
        lint["Author structural lint rule<br/>in the same commit as the carve-out<br/>(forbidden-import / topology / port-uniqueness)"]

        s1 --> s2 --> s3 --> s4 --> s5 --> lint
        lint -. next task .-> s2
    end

    done(["Architectural change<br/>VERIFIED done"])
    ship(["Ship as-is<br/>(no plan needed)"])

    trig --> load --> p1 --> p2 --> decide
    decide -- "yes" --> p3
    decide -- "no" --> ship
    p3 --> done

    classDef partbox fill:#f5f5f5,stroke:#666,stroke-width:1px;
    classDef gate fill:#fff3e0,stroke:#e65100,stroke-width:2px;
    classDef terminal fill:#c8e6c9,stroke:#1b5e20,stroke-width:2px;
    class p1,p2,p3 partbox
    class decide gate
    class done,ship terminal
```

**Inputs / outputs at each stage:**

| Stage | Consumes | Produces |
|---|---|---|
| PART 1 (Theory) | none — read in full | mental model: layers, deps, ports, adapters, Application Core, primary/secondary, components |
| PART 2 (Audit) | code under review | findings list (file:line + severity + fix-shape) |
| PART 3 step ⓵ (`writing-plans`) | findings list | phased plan file with explicit file targets + verification cmds |
| PART 3 step ⓶ (`executing-plans`) | plan file | tasks executed one-at-a-time; deviations flagged |
| PART 3 step ⓷ (TDD) | port/adapter/relocation shape | RED → GREEN per task; regression suite stays green |
| PART 3 step ⓸ (`coding-skills`) | code edit-in-progress | edit improved per principle (DRY for parallel ports, YAGNI for premature abstractions, etc.) |
| PART 3 step ⓹ (verification) | claim ("Domain is leaf-pure", etc.) | passing grep / dep-graph / lint scan — or RED state to fix |
| Lint rule authored | locked boundary | `rules/lints/onion-*.yml` committed alongside the carve-out |

**Where the workflow can short-circuit:**

- After PART 2 if all findings are P3 cosmetic only → ship the audit, skip PART 3.
- After PART 2 if the change is purely additive + < 10 LOC → can skip the formal plan file but **must still** run PART 3 step ⓹ (verification) before claiming done.
- Mid-PART-3 if `executing-plans` flags a deviation that contradicts a Theory invariant → loop back to PART 1 to re-ground, then re-plan.

## ⚠ Read-in-full discipline (Iron Law)

**This skill body MUST be read end-to-end before applying any section.**
Theory grounds the audit; the audit produces inputs for the plan; the
plan/execute discipline catches the failure modes ad-hoc edits hit.
Skipping any section turns the workflow into a partial application of a
discipline that was authored as a whole.

Specifically:

- Don't skim to "Decision rules" without reading "The One Rule" + "DIP".
  The decision table is meaningless without the dependency-direction
  invariant it implements.
- Don't skim to the "Audit lens" tables without reading the "Four
  Layers" section first — audit findings are descriptions of layer
  violations and cannot be diagnosed without knowing what the layers
  contract for.
- Don't skim to "Why each step is required" without reading the chain
  diagram. The argument is *why ad-hoc edits fail*, not a footnote.
- Don't lift any one section's table out of context. The sections only
  hold *together*.

If the file is too long, that's a signal you need the workflow more,
not less. **No exceptions.** No "I already know this skill" shortcut —
skills evolve; re-read every time.

# PART 1 — THEORY (the *why*)

> **Extracted to `references/theory.md`** (~6,000 tokens; load on demand).
> Covers: Palermo's One Rule, DIP (the engine), Database externalization,
> the Four Layers + decision rules, Anemic Domain detection, Testing
> strategy by layer, When NOT to use Onion, Scaling (microservices /
> event-driven / modular monolith), Explicit Architecture (Graça
> synthesis: Primary/Secondary adapters, Application Core, App vs
> Domain Services, CQRS placement, Domain Events + Shared Kernel,
> Components orthogonal to layers), and the Project structure template.
>
> Read it in full before authoring code in this discipline. The
> remaining parts (AUDIT / PLAN / EXECUTE) stay inline below — those
> are the action-oriented surfaces that fire most often.

# PART 2 — AUDIT (the *how to spot violations*)

Theory in hand, apply it to existing code: produce a findings list, route remediation to Part 3.

## What this section produces

An **audit report** with:
1. List of violations, each with severity (P0 architectural / P1 boundary leak / P2 smell / P3 cosmetic).
2. Per-violation: file:line citation + verbatim code excerpt + theory rule it breaks.
3. Per-violation: remediation suggestion (one line — the fix shape, not the full plan).
4. Summary: dep-direction green/red verdict, count of leaks per layer.

This section **does not edit code.** When remediation should land, route to Part 3.

## Layer-placement violations

| Symptom | Likely violation | Severity |
|---|---|---|
| `import { db } from "../infrastructure/db"` in a domain file | Domain pollution | **P0** |
| `use sqlx::*` / `use tokio::*` / `use express::*` in a domain entity | Domain pollution | **P0** |
| Domain importing `serde::Deserialize` for HTTP wire format | Wrong-layer concern | **P1** |
| A "model" file with both `password` (domain) and `password_hash_column_name` (persistence) | Anemic + persistence-coupled domain | **P0** |
| Repository interface returns ORM rows or HTTP responses | Leaky port | **P0** |
| Application code constructs concrete adapters in the use-case body | DI bypass | **P1** |
| Controller calls a repository directly, skipping application services | Use case never coalesced | **P1** |
| Domain service calls another domain service that calls infrastructure | Domain reaching outward | **P0** |

## Anemic domain detection

| Symptom | Diagnosis |
|---|---|
| Entities have only getters/setters | Anemic domain model |
| Services contain `if entity.field == X { entity.field = Y }` instead of `entity.method()` | Logic should be on entity |
| "Validation" lives in service code, not entity constructors | Invariants leaked out |
| Entity constructor accepts any input and persists it raw | Missing invariant enforcement |

**Fix shape:** push invariants and state transitions onto the entity. Service becomes thin coordinator.

## Cross-layer leaks

| Symptom | Severity |
|---|---|
| Application service signature uses `axum::Json<T>` / `express.Request` | **P1** — Application has bound to Presentation framework |
| Infrastructure adapter calls into Application services | **P1** — wrong direction (Infrastructure should depend only on Domain) |
| Presentation imports from Infrastructure directly (skips Application) | **P1** — composition root violated |
| `tokio` / `runtime` types in Domain | **P0** — Domain must compile against std alone |
| Test code in production module's `src/` instead of `tests/` outer ring | **P2** — outer-ring violation, mostly cosmetic |
| Application service has 30+ dependencies | **P1** — use case is doing too much, OR dependencies are too granular. Look for a **missing aggregate** that should bundle several into one transactional boundary |
| Cyclic dependency between two bounded contexts (`Orders` ↔ `Inventory`) | **P0** — bounded contexts must communicate via an **anti-corruption layer (ACL)** or a **shared kernel**, never by importing each other's internals. The cycle is the symptom; the missing ACL is the cause |
| Port signature mirrors the vendor SDK (e.g. `trait Db { fn execute(sql: String) -> Vec<Row>; }`) | **P1** — *port mimics the tool* (Graça). Re-design the port from the consumer's call sites: domain operations, not SQL. |
| Domain Service calls a repository | **P0** — Domain reaching outward; promote the repo call to an Application Service that loads the aggregate(s) and delegates the cross-entity logic to the Domain Service. |
| Query Handler returns a domain entity | **P1** — domain shape leaking into Presentation. Map to a DTO inside the handler. |
| Command Handler mutates two or more aggregates in one call | **P1** — usually a missing Domain Service (cross-entity rule) or, for cross-aggregate consistency, a missing saga / process manager. Don't merge the aggregates as a fix. |
| Aggregate / Service added to the Shared Kernel | **P0** — Shared Kernel should hold value objects, IDs, and cross-context Event definitions only. Move it to its owning context; let other contexts reach via ACL. |
| Event published from an Infrastructure adapter (not from the Application Service that completed the use case) | **P1** — emission point breaks the use-case → side-effect contract; Application Events belong in the Application Layer. |
| Primary adapter (Controller, CLI, Bus) implements business logic instead of translating | **P1** — fat-controller anti-pattern; lift to an Application Service. The adapter's job is "translate inbound → call port". |
| Secondary adapter doesn't implement a port (just a free-function `pg_save(...)`) | **P1** — DIP violated; adapter must implement an interface defined in the Application Layer. |

## Boundary smell — composition root

The composition root (`main.rs`, `wire.go`, DI container) is the *only* place where concrete adapters get constructed.

| Symptom | Severity |
|---|---|
| `PostgresRepo::new(...)` called inside Application service | **P1** — DI bypass |
| Multiple composition roots scattered across the codebase | **P1** — wiring fractures, tests can't substitute |
| Composition root accepts no config (hardcoded) | **P2** — testability suffers but not architectural |
| Composition root inside a non-binary crate | **P0** — application crate should not assume runtime |

## Audit checklist (paste into PR review)

- [ ] Domain has zero non-stdlib imports (or only data primitives like `chrono`, `uuid`).
- [ ] Repository interfaces are defined in Domain (or Application), implemented in Infrastructure.
- [ ] Application services depend on interfaces, not concrete adapters.
- [ ] Presentation translates between transport and Application commands/results — no business logic.
- [ ] Entities have behavior, not just getters/setters. Invariants enforced inside the entity.
- [ ] Cross-context communication via ACLs or domain events, not direct imports.
- [ ] Domain unit tests require no mocks.
- [ ] No cyclic dependencies between modules.
- [ ] Composition root is a single, identifiable seam.

## Anti-pattern fast-detect (one-liners)

```bash
# Domain framework imports (replace `<domain-path>` per project)
grep -rE '^use (sqlx|tokio|reqwest|axum|hyper|serde::Deserialize)' <domain-path>

# Repository interface returning ORM types
grep -rE 'fn .* -> .*Row|.*FromRow' <domain-path>

# Composition root duplication
grep -rE '::new\(' --include='*.rs' . | grep -E 'Repository|Adapter|Gateway' | grep -v 'main\.rs\|wire\.\|tests/'

# Layer-violating imports (Rust workspace)
grep -rE '^use crate::infrastructure' <domain-path>
grep -rE '^use crate::infrastructure' <application-path>
```

## Audit output template

```markdown
## Onion / DDD audit — <module / crate name>

**Dep-direction verdict:** ✅ green / ⚠ leaks / ❌ violated

### P0 — architectural violations
- `<file>:<line>` — <one-line description>
  ```<lang>
  <verbatim 1-3 line excerpt>
  ```
  **Rule broken:** <theory rule, e.g. "The One Rule — domain depends on infrastructure">
  **Fix shape:** <one-line — e.g. "extract `UserRepository` trait into domain/ports; impl in infrastructure">

### P1 — boundary leaks
(same format)

### P2 — smells
(same format)

### Summary
- Layers audited: domain, application, infrastructure, presentation
- Violations by layer: domain=N, application=N, infrastructure=N, presentation=N
- Recommended next step: Part 3 plan/execute (if P0/P1 present), else "ship as-is".
```

## Common audit failure modes

| Failure | Reality |
|---|---|
| "I read 3 files, looks fine" | Audit needs the *whole* layer surface, not a sample. Grep for forbidden imports first. |
| "The compiler caught nothing → it's correct" | The compiler can't see "depends inward only". A compile-clean tree can still violate layering. |
| "I'll skip the boring composition root" | Composition root is where DI either works or doesn't. It's the most-leveraged 50 LOC in the codebase. |
| "Anemic models are fine, the services have the logic" | The architecture *looks* layered but isn't — see "Anemic Domain Model" above. |
| "I'll just fix the violations as I find them" | DON'T. Audit produces findings; route fixes to Part 3 so the change is sequenced + verified. Improvised fixes hit cycle traps. |

# PART 3 — PLAN + EXECUTE (the *remediation chain*)

Take the audit's findings, turn them into a phased plan, execute task-by-task with TDD + coding-skills, and verify the architectural claim with concrete commands — not improvised edits.

## The canonical chain

This is one pipeline, not a menu. Stopping anywhere before `done`
leaves the architectural change unverified. **Each step requires the
matching skill from "Required skills" above:**

```mermaid
flowchart LR
    audit["Part 2<br/>(findings input)"]
    plans["superpowers:<br/>writing-plans"]
    exec["superpowers:<br/>executing-plans"]
    coding["coding-skills<br/>(KISS · DRY · YAGNI · SOLID · ...)"]
    verify["Verification commands<br/>(see table below)"]
    done([architectural<br/>change done])

    audit --> plans
    plans --> exec
    exec --> coding
    coding --> verify
    verify --> done
```

1. **REQUIRED SUB-SKILL:** `superpowers:writing-plans` — turn Part 2's findings list into a phased plan with explicit file targets, code, and verification commands. The audit's violations + remediation sections are the spec input.
2. **REQUIRED SUB-SKILL:** `superpowers:executing-plans` (or `superpowers:subagent-driven-development` if subagents are available) — run the plan task-by-task with verification at each step.
3. **TDD discipline applies during each task.** Onion remediation introduces architectural surface that needs test coverage:
   - **New port** (trait in Domain) → write a contract test asserting the trait's required behavior, run RED first against an unimplemented impl, then satisfy with the impl in Infrastructure (GREEN).
   - **Lifted port** (trait moved Crate A → Crate B) → existing tests should still pass; if they fail post-move, the lift broke something. Treat existing-suite green as the GREEN gate; do not modify those tests to make the move "pass".
   - **New adapter** (Infrastructure impl of an existing port) → write the contract test against the trait, then write the impl. Mock-at-boundary applies; the trait IS the boundary.
   - **Pure relocation with no signature change** → no NEW test needed, but RED-GREEN still applies to the regression suite. If `cargo check` passes but a test from the old location fails, that's a real RED state to fix, not a noise to suppress.
4. **REQUIRED SUB-SKILL:** `coding-skills` (the bundle: `coding-skills:kiss`, `:dry`, `:yagni`, `:solid`, `:separation-of-concerns`, `:law-of-demeter`, `:boy-scout-rule`, `:convention-over-configuration`) — apply during each code edit produced by step 2. Onion remediation is a code-relocation operation — every move between layers is an opportunity to either improve or degrade the touched code. The four most load-bearing principles for layer-boundary work:
   - **SOLID** (DIP specifically) — *is* the Onion rule. Verify the port lives in the inner layer; only the impl moves outward.
   - **YAGNI** — don't introduce a port for a hypothetical second consumer. One impl + a direct dep is fine until a second appears. Premature ports create the same dep-graph noise Onion exists to remove.
   - **DRY** — port duplication across crates is the single highest-leverage finding type. Grep for parallel trait definitions before writing new ones.
   - **Boy-Scout Rule** — if you're touching a file to relocate a symbol, fix the small layering smell next to it. Don't enlarge scope, but don't leave decay either.
5. **Verification commands** — see table below. Architectural claims are *checkable*, not vibes — confirm them with the commands the audit specified.

## Why each step is required

| Skip | What you lose |
|---|---|
| `writing-plans` | Ad-hoc edits miss inverted-dep cycle traps. Moving a `From` impl from the inner crate to the outer crate creates a `core ↔ utils` cycle that only manifests when both Cargo.tomls have been touched — a planning step catches the ordering constraint; improvisation hits the cycle, rolls back, retries. |
| `executing-plans` | You write a plan, then silently deviate when reality contradicts it. The plan's risk register and "stop and re-evaluate when verification fails" discipline exists to catch wrong assumptions (e.g. "this `From` impl is dead code" turning out to be 18 active call sites). Without execution discipline, deviations don't get flagged or justified. |
| TDD discipline | New ports ship with no behavioral contract tests — the trait compiles but no test pins what it promises, so the first impl silently defines its own loose semantics. Lifted ports get green compiles even when the move broke an obscure call path, because the test suite was never re-run between RED and GREEN. The post-fix dep graph looks correct, but the layer's behavior is now under-specified. |
| `coding-skills` | Code gets *relocated* but not *improved*. Layer moves silently propagate YAGNI violations (ports for one consumer), DRY violations (duplicate trait defs across crates — the canonical Onion remediation finding type), and SOLID violations (Liskov-breaking subtype substitution at the new layer boundary). The dep-graph looks correct on the audit's grep checks, but the code at the seams gets worse. |
| Verification | "The database is not the center" is a *checkable* claim. Onion fixes need their own checks beyond `cargo check` / `tsc --noEmit`: did the dep-direction actually invert? Is the Domain layer actually leaf? Run the grep / dep-graph command, not just the type-checker. A green compile does not prove the architectural claim — it only proves syntactic well-formedness. |

## Verification commands by claim

These are the kinds of checks that should run for an Onion fix. The compiler will not catch any of these; you must invoke them explicitly.

| Claim | Check |
|---|---|
| "Domain is leaf-pure" | Confirm zero internal/workspace deps from the domain crate/package. **Rust:** `grep '^<workspace-prefix>-' <domain>/Cargo.toml` (where `<workspace-prefix>` is your workspace's crate-name prefix). **Go:** `go list -deps ./<domain> \| grep <module-prefix>`. **Node:** `jq '.dependencies' <domain>/package.json` and verify no internal package names. **Python:** `pip show <domain>` + check `pyproject.toml` for first-party deps. |
| "Dep direction is outer → inner only" | dep-graph tool — render Mermaid + visual inspection, or maintain a CI job that diffs against a golden topology. Inversions show as edges pointing from a deeper layer to a shallower one. **Rust workspace:** `cargo tree -p <crate> --depth 1` for forward deps; `cargo metadata --format-version 1 \| jq '.packages[] \| select(.dependencies[]? .name == "<dep>") .name'` for reverse-deps. |
| "Repository port is implemented in Infrastructure" | grep for the trait/interface in Domain + grep for the `impl <Trait> for <ConcreteType>` (or equivalent) in Infrastructure — both must exist, in different layers, in opposite directions of the dep graph. |
| "Domain has no framework imports" | grep for forbidden imports in domain files (`use express`, `import { db }`, `tokio::process`, `from sqlalchemy`). The forbidden list is project-specific; codify it once in CI. |
| "Cycle was broken cleanly" | `cargo check --workspace` (or the equivalent) — but **also** the leaf-pure grep above. The compiler accepts non-cyclic graphs that still violate the dep-direction rule (e.g. cousin-dep at the same layer). |

## Codifying boundaries with structural lint rules

Every locked architectural boundary should land with a structural lint rule that prevents regression. The compiler can't see "depends inward only"; a structural linter can. **Author the rule as part of the carve-out commit, not as a follow-up** — the boundary then cannot regress before its first PR.

### Three rule families that cover most Onion boundaries

| Family | Catches | Naming pattern (suggested) |
|---|---|---|
| **Forbidden-import** | An outer-ring dependency leaking into Domain or Application (e.g. an HTTP client in Domain, an ORM in Application). | `onion-no-<dep>-in-<layer>` — one rule per dep × layer pair. |
| **Topology / graph-level** | The Domain crate growing internal deps; a layer importing across-and-down instead of inward. | `onion-<layer>-no-internal-deps`, `onion-no-<consumer>-import-from-<forbidden-source>`. |
| **Port uniqueness** | A trait/interface lifted to Domain getting silently re-declared in an outer ring (Liskov-breaking parallel definitions). | `onion-no-redefine-<port>` — one rule per canonical port. |

Stack-specific tools to author them in:

- **Rust / TypeScript / Python / Go** → `ast-grep` (language-agnostic, YAML rule files, CI-friendly). One rule per file under a project-local rules tree (e.g. `rules/lints/`, `.ast-grep/`, or `tools/lint/`); name files `onion-<family>-<subject>.yml` so the scan filter `--filter 'onion-*'` selects them as a set.
- **TypeScript** → ESLint custom rules or `import/no-restricted-paths` for forbidden-import / topology rules; `ast-grep` for port-uniqueness.
- **Python** → `import-linter` (contract files) for topology; `ast-grep` for forbidden-import + port-uniqueness.
- **Java / Kotlin** → ArchUnit (test-time architectural rules — same three families, expressed as test code).
- **Go** → `go-arch-lint` config for topology; `ast-grep` for forbidden-import.

### Rule-shape skeleton (ast-grep, language-agnostic)

```yaml
id: onion-no-<dep>-in-<layer>
language: <rust|typescript|python|go>
rule:
  pattern: <import statement of the forbidden dep>
  inside:
    has:
      kind: source_file
      stopBy: end
files:
  - <glob for the layer>
message: |
  <Layer> must not depend on <dep> — it belongs in <correct layer>.
  Add a port (trait/interface) here, implement it in <correct layer>.
severity: error
```

Port-uniqueness rules use a `pattern: trait <PortName>` (or the language's interface keyword) with a `not.inside` clause excluding the canonical Domain location.

### Required hygiene

- **Snapshot tests** — every rule has a fixture demonstrating *what it rejects* AND *what it accepts*. A rule with no accept-fixture is a rule waiting to false-positive into being disabled.
- **CI gate** — the lint scan runs on every PR (`ast-grep scan --filter 'onion-*'` or equivalent). Local pre-commit too if the project has a hook.
- **Architecture log entry** — the carve-out commit's architecture-log row names the new rule file by id. Makes "when did this rule land?" answerable via grep.

### What goes in the *project's* CLAUDE.md vs. the rule files

This skill intentionally does NOT enumerate specific projects' rule catalogs — those are project state, not durable rules. The convention belongs here; the live list ("we currently have N onion lints, named X / Y / Z") belongs in the project's CLAUDE.md or its memory. When the project's audit-log row references a rule by name, the rule file IS the source of truth — don't duplicate its body into prose.

## When the chain is unnecessary

- The audit confirms the architecture is already correct → stop after Part 2; no plan, execution, or verification needed.
- The audit recommends a change that is purely additive (new port, new value object, no migration, no code moves) and < 10 LOC → can skip `writing-plans` for the formal plan document, but **must still** verify the architectural claim with the commands above before claiming done.
- The user explicitly invoked the workflow for *teaching / review only* with no intent to change code → stop after Part 2; the chain is for code changes, not learning.

In every other case — every refactor, every dep-direction fix, every layer reassignment — the five-step chain is required.

## Common rationalizations for skipping the chain

| Excuse | Reality |
|---|---|
| "The audit findings are obvious enough to fix directly" | Obvious to write != obvious to sequence. The cycle trap (above) bites improvised edits, not planned ones. |
| "It's just one file change" | Then the plan is one task. Cost: ~3 minutes. Benefit: caught risk register entries and a verification gate. |
| "`cargo check` / `tsc --noEmit` passing means I'm done" | The compiler can't see "depends inward only". A compile-clean tree can still have a `Domain → Infrastructure` edge — the architectural violation Onion exists to prevent. |
| "I already verified mentally that the dep direction is right" | Mental verification is exactly the failure mode the verification step exists to prevent. Run the grep. |
| "The user told me to execute immediately, so I'll skip the plan" | "Execute immediately" means *execute the plan immediately*, not *skip the plan*. Plan + execute + verify is one atomic flow at execution time; the workflow is the structure, the user's "immediately" is the cadence. |
| "Coding-skills is for new feature work, not for moving existing code" | Wrong frame. The most damaging Onion violations enter the codebase *during refactors*: a port lifted to Domain that no longer matches its sole impl's signature (SOLID/LSP), a trait duplicated across two infrastructure crates because the auditor didn't grep first (DRY), a port introduced "for the future second consumer" that never arrives (YAGNI). Coding-skills is precisely the discipline that catches these at edit time. |
| "TDD doesn't apply to relocations — there's no new behavior to test" | Half right, fully wrong. Pure relocations don't need a NEW failing test, but they DO need the existing suite to run between the old-location-removal and the new-location-addition — that's the regression-as-RED check. New ports always need a contract test (the trait's promise is the test's assertion). New adapters always need an impl test against the port. "No new test" almost always means "I moved code without exercising it." |

## Red flags — STOP and route through the chain

- About to edit a `Cargo.toml` / `package.json` / `go.mod` to add or remove an internal dep
- About to move a trait/interface between crates/modules/packages
- About to introduce or remove a port (interface in Domain, impl in Infrastructure)
- About to claim "this layer no longer depends on that one" without running a check
- About to commit an architectural fix with `cargo check` / `tsc` as the only evidence

All of these mean: write a plan (`superpowers:writing-plans`), execute it (`superpowers:executing-plans`), apply `coding-skills` per edit, run the verification commands the plan specified.

# References

- `references/typescript-example.md` — TypeScript/Node example mapping the four layers onto Express + repository pattern.
- `references/rust-example.md` — Rust example mapping onto traits + tokio.

# Canonical sources

- **Jeffrey Palermo, *The Onion Architecture: Part 1* (2008)** — original articulation of the pattern. Source of the "all coupling is toward the center" rule and the database-externalization principle.
  <https://jeffreypalermo.com/2008/07/the-onion-architecture-part-1/>
- **Robert C. Martin, *Dependency Inversion Principle*** — the structural principle Onion is built on.
  <https://en.wikipedia.org/wiki/Dependency_inversion_principle>
- **Eric Evans, *Domain-Driven Design* (2003)** — origin of Entity, Value Object, Aggregate, Domain Service, Repository terminology used throughout.
- **Vaughn Vernon, *Implementing Domain-Driven Design* (2013)** — modern DDD practice; placed repository interfaces inside the Domain layer.
- **Robert C. Martin, *Clean Architecture* (2017)** — adjacent pattern with the same dependency-inversion engine; uses 4+ rings (Entities, Use Cases, Interface Adapters, Frameworks). Onion's four-layer simplification maps onto Clean's outer three rings + Entities.
- **Alistair Cockburn, *Hexagonal Architecture / Ports and Adapters* (2005)** — sister pattern; Onion's "ports" terminology is borrowed. Same dependency-inversion engine, different visualisation. Source of the **primary (driving) vs secondary (driven) adapter** distinction this skill uses.
- **Herberto Graça, *DDD, Hexagonal, Onion, Clean, CQRS, … How I put it all together* (2017)** — *Explicit Architecture*. Synthesises DDD + Hexagonal + Onion + Clean + CQRS into one coherent model. Source of the **Application Core** wrapping (Application + Domain), the **package-by-component** vs package-by-layer guidance, the **Shared Kernel for cross-component event coordination**, and the **"ports designed for App Core needs, not tool APIs"** rule. Folded into PART 1 § "Explicit Architecture extensions".
  <https://herbertograca.com/2017/11/16/explicit-architecture-01-ddd-hexagonal-onion-clean-cqrs-how-i-put-it-all-together/>

# Supersedes

This single skill replaces the prior three-skill chain:

- `onion-ddd-theory` → folded into Part 1 above.
- `onion-ddd-audit` → folded into Part 2 above.
- `onion-ddd-plan` → folded into Part 3 above.

The three old skill files now contain redirect shells pointing here.
