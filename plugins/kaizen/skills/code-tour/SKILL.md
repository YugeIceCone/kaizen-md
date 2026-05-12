---
name: code-tour
description: Use when the user asks to create a CodeTour .tour file — persona-targeted, step-by-step walkthroughs that link to real files and line numbers. Triggers on "create a tour", "onboarding tour", "architecture tour", "PR review tour", "explain how X works", "vibe check", "RCA tour", "contributor guide", or any structured code walkthrough request. Pairs with `kaizen:explore` (initial mapping) and `kaizen:handoff` (durable artifact for session handoff). Adapted from claude-code-skills/engineering/code-tour, sanitized + integrated into the kaizen workflow.
version: 1.0.0
---

# Code Tour

Create **CodeTour** files — persona-targeted, step-by-step walkthroughs of a codebase that link directly to files and line numbers. Tour files live in `.tours/` and work with the [VS Code CodeTour extension](https://github.com/microsoft/codetour).

A great tour is a **narrative** — a story told to a specific person about what matters, why it matters, and what to do next. Only create `.tour` JSON files. Never modify source code.

## When to use

- User asks to create a code tour, onboarding tour, or architecture walkthrough
- "tour for this PR", "explain how X works", "vibe check", "RCA tour"
- Contributor guide, security review, or bug investigation walkthrough
- Any request for a structured walkthrough with file/line anchors

## How this slots into kaizen

- **Pairs with `kaizen:explore`** — explore maps structure; code-tour writes the durable artifact
- **Pairs with `kaizen:handoff`** — tour file becomes part of the handoff bundle for the next session
- **Plays well with the `audit` routine** — `code-tour` can run after `explore` and before `analyze` to produce a navigation aid for the audit report
- **New routine candidate** — `tour-build` (explore → detect-stack → tour-author → validate)

## Core workflow

### 1. Discover the repo

In parallel: list root directory, read README, check config files. Then identify language(s), framework(s), project purpose. Map folder structure 1–2 levels deep. Find entry points — every path in the tour must be real.

If the repo has fewer than 5 source files, create a quick-depth tour regardless of persona — there's not enough to warrant a deep one.

### 2. Infer the intent

Infer persona, depth, and focus silently. One message should be enough.

Common mappings (use bullet form, no live tables):

- "tour for this PR" → persona `pr-reviewer`, depth `standard`
- "why did X break" / "RCA" → `rca-investigator`, `standard`
- "onboarding" / "new joiner" → `new-joiner`, `standard`
- "quick tour" / "vibe check" → `vibecoder`, `quick`
- "architecture" → `architect`, `deep`
- "security" / "auth review" → `security-reviewer`, `standard`
- no qualifier → `new-joiner`, `standard` (most generally useful default)

### 3. Read actual files

**Every file path and line number must be verified.** A tour pointing to the wrong line is worse than no tour. Read each file before claiming a line range.

### 4. Write the tour

Save to `.tours/<persona>-<focus>.tour`:

```json
{
  "$schema": "https://aka.ms/codetour-schema",
  "title": "Descriptive Title — Persona / Goal",
  "description": "Who this is for and what they'll understand after.",
  "ref": "<current-branch-or-commit>",
  "steps": []
}
```

### Step types

- **Content** — intro/closing only, max 2 per tour. Shape: `{ "title": "Welcome", "description": "..." }`
- **Directory** — orient to a module. Shape: `{ "directory": "src/services", "title": "..." }`
- **File + line** — the workhorse. Shape: `{ "file": "src/auth.ts", "line": 42, "title": "..." }`
- **Selection** — highlight a code block. Shape: `{ "file": "...", "selection": {...}, "title": "..." }`
- **Pattern** — regex match for volatile files. Shape: `{ "file": "...", "pattern": "class App", "title": "..." }`
- **URI** — link to PR, issue, doc. Shape: `{ "uri": "https://...", "title": "..." }`

### Step counts by depth

- **Quick** (5–8 steps) — vibecoder, fast exploration
- **Standard** (9–13 steps) — most personas, default
- **Deep** (14–18 steps) — architect, RCA

### SMIG description formula

Each step description should answer:

- **S — Situation**: what is the reader looking at?
- **M — Mechanism**: how does this code work?
- **I — Implication**: why does this matter for this persona?
- **G — Gotcha**: what would a smart person get wrong here?

### 5. Validate

- Every `file` path relative to repo root (no leading `/` or `./`)
- Every `file` confirmed to exist on disk
- Every `line` verified by reading the file
- First step has `file` or `directory` anchor (not content-only)
- At most 2 content-only steps per tour
- `nextTour` matches another tour's `title` exactly if set

## Personas

- **Vibecoder** — get the vibe fast. Entry point, main modules. Max 8 steps.
- **New joiner** — structured ramp-up. Directories, setup, business context.
- **Bug fixer** — root cause fast. Trigger → fault points → tests.
- **RCA investigator** — why did it fail. Causality chain, observability anchors.
- **Feature explainer** — end-to-end. UI → API → backend → storage.
- **PR reviewer** — review correctly. Change story, invariants, risky areas.
- **Architect** — shape and rationale. Boundaries, tradeoffs, extension points.
- **Security reviewer** — trust boundaries. Auth flow, validation, secret handling.
- **Refactorer** — safe restructuring. Seams, hidden deps, extraction order.
- **External contributor** — contribute safely. Safe areas, conventions, landmines.

## Narrative arc

1. **Orientation** — `file` or `directory` step (never content-only first step — blank in VS Code)
2. **High-level map** — 1–3 directory steps showing major modules
3. **Core path** — file/line steps, the heart of the tour
4. **Closing** — what the reader can now *do*, suggested follow-ups

## Anti-patterns

- **File listing** ("this file contains the models") → tell a story; each step depends on the previous
- **Generic descriptions** → name the specific pattern unique to this codebase
- **Line number guessing** → never write a line you didn't verify by reading the file
- **Too many steps for quick depth** → actually cut steps
- **Hallucinated files** → if it doesn't exist, skip the step
- **Recap closing** ("we covered X, Y, Z") → tell the reader what they can now *do*
- **Content-only first step** → anchor step 1 to a file or directory

## Cross-links

- `kaizen:explore` — initial structure mapping (the upstream to this skill)
- `kaizen:handoff` — package the tour into a session handoff
- `kaizen:research` — for broader topical research beyond the codebase
- CodeTour extension: [microsoft/codetour](https://github.com/microsoft/codetour)
- Reference real tour: [coder/code-server contributing.tour](https://github.com/coder/code-server/blob/main/.tours/contributing.tour)
