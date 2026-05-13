<!-- DO NOT HAND-EDIT.

Generated from skills/workflow/domain/intent_routing.yaml by
skills/workflow/application/codegen.py.

To change content, edit the yaml and run:
    python3 skills/workflow/application/codegen.py
or rely on refresh-cache.sh which invokes codegen before sync.
-->

# Code-principle routing

Routes code-quality and architectural questions to the appropriate `coding-skills:<name>` skill. Source-of-truth: `skills/workflow/domain/intent_routing.yaml`. Loader / matcher / CLI: `skills/workflow/application/route_intent.py`.

## Intent → skill

- **Over-engineering / speculative "might-need-later" features** → `coding-skills:yagni`
  cues: "do we need this", "just in case", "future-proof this", "is this over-engineered", "should I add an abstraction for", "we might want to"
- **Readability / simplicity on existing code** → `coding-skills:kiss`
  cues: "simplify this", "too complex", "hard to read", "what does this do", "can't follow this", "clean up this function"
- **Coupling via deep object chains** → `coding-skills:law-of-demeter`
  cues: "too coupled", "train wreck", "chained calls", "reaches too deep", "mocking is painful", "feature envy", "a.b().c().d()"
- **Layering / where-does-this-belong** → `coding-skills:separation-of-concerns`
  cues: "this function does too much", "fat controller", "fat model", "fat service", "mixed concerns", "where should this logic go", "separate the layers"
- **Class / interface / module shape** → `coding-skills:solid`
  cues: "how should I structure this class", "interface design", "dependency injection", "single responsibility", "hard to test because of coupling", "swap the backend"
- **Duplicated knowledge / single source of truth** → `coding-skills:dry`
  cues: "this is duplicated", "we have this in two places", "shotgun surgery", "single source of truth", "DRY this up"
- **First-time orientation in an unfamiliar repo (precedes any other principle skill on a fresh repo)** → `coding-skills:detect-stack`
  cues: "what's this codebase using", "what's the stack", "detect stack", "first time in this project", "what conventions"
- **Incremental improvement while in a file** → `coding-skills:boy-scout-rule`
  cues: "clean this up while I'm here", "tech debt", "should I fix this too", "incremental improvement", "while I'm in this file", "small cleanup"
- **Project structure, naming, reducing config overhead** → `coding-skills:convention-over-configuration`
  cues: "how should I organize this", "what's the convention", "too much config", "project structure", "naming pattern", "standardize this"

## Disambiguation

Pairs that overlap; tiebreaker rule wins.

- **separation-of-concerns vs solid** — SoC draws the LINE (auth here, db there); SOLID shapes the TYPES (what the auth interface looks like).
  - `separation-of-concerns`: fat controller
  - `solid`: interface has 12 methods
- **kiss vs yagni** — KISS is about code you ALREADY have (strip it down); YAGNI is about code you're ABOUT TO write (don't add the speculative layer).
  - `kiss`: simplify this
  - `yagni`: should I add a plugin system?
- **dry vs separation-of-concerns** — DRY = one source of truth for this KNOWLEDGE; SoC = each CONCERN lives in one place.
  - `dry`: tax calculation copy-pasted across UI and API
  - `separation-of-concerns`: tax calculation baked into a View controller
- **law-of-demeter vs solid** — LoD = the specific call chains the code is taking RIGHT NOW; SOLID = TYPE relationships.
  - `law-of-demeter`: mocking chains of 5
  - `solid`: mock setup is huge because one trait has too many methods
- **boy-scout-rule vs yagni** — Boy Scout asks 'while I'm here, should I improve this bit?'; YAGNI asks 'before I start, should I add this speculative feature?'
  - `boy-scout-rule`: fix a broken comment while bug-hunting
  - `yagni`: resist adding a plugin system 'because maybe later'
- **convention-over-configuration vs separation-of-concerns** — Convention-over-config = SAMENESS across the project (all routes in routes/); SoC = SEPARATION within the code.
  - `convention-over-configuration`: where do new controllers go?
  - `separation-of-concerns`: why is there a DB query inside this controller?

## Composition (multi-step)

Prompts that span two routes. Sequence is ordered; never simultaneous.

- **Unfamiliar repo + "fix this messy thing"** → `detect-stack` → `kiss`
  _Stack first, then the relevant principle once context is clear._
- **This is a mess + I'm editing it anyway** → `boy-scout-rule` → `kiss`
  _Boy-Scout governs SCOPE; the second skill is the technique. Load incremental-code-cleaning first._
- **Should I refactor this into X pattern** → `yagni` → `solid`
  _YAGNI gates (does the problem warrant the pattern?); SOLID shapes (if yes, what's the interface?). Only proceed to SOLID if YAGNI says the abstraction is justified._

**Cap:** `2` skills per turn. If code is deeply flawed, focus on one structural concern (SoC or SOLID) before any micro-cleanup (KISS, Boy-Scout).

## When NOT to route here

- **Structural find / rewrite (ast-grep)** → `ast-grep-router`
- **Code-graph questions (callers, dead code, blast radius, imports)** → `llm-tldr-router`
- **Running or debugging business logic** → (no skill — just answer)
  _Just help them. No principle skill is load-bearing._
- **Style / formatting (rustfmt / prettier / black)** → (no skill — just answer)
  _The formatter is authoritative._
- **Writing fresh unrelated code from scratch** → (no skill — just answer)
  _No principle skill is load-bearing here. Skip this router._

## Invocation protocol

1. Match the user's phrasing against the `routes[].cues` list (most prompts fit one cleanly).
2. If two routes overlap, consult `disambiguation` for the tiebreaker.
3. Invoke the matched skill and stop. Don't also answer the question directly from the router.
4. For composition cases (`composition` entries), invoke the FIRST skill now;
   queue the SECOND only if the user's next turn needs it.
5. Cap at `limits.max_skills_per_turn` per turn.
