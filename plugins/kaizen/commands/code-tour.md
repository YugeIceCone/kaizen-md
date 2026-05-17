---
name: code-tour
description: "Scaffold a CodeTour .tour walkthrough — persona-targeted, step-by-step, file+line anchored. Triggers on \"create a tour\", \"onboarding tour\", \"architecture tour\", \"PR review tour\", \"explain how X works\", \"vibe check\", \"RCA tour\", \"contributor guide\". Thin router to the kaizen:code-tour skill."
argument-hint: "[persona] [depth]   e.g. /kaizen:code-tour newcomer quick"
allowed-tools: ["AskUserQuestion", "Read", "Glob", "Grep", "Write", "Bash(git log:*)", "Bash(git status:*)"]
---

# /kaizen:code-tour — scaffold a persona-targeted walkthrough

Load `Skill(kaizen:code-tour)` and follow its workflow to produce a
`.tours/<slug>.tour` JSON for the repo at the user's request.

## Argument parsing

`$ARGUMENTS` may contain `<persona> <depth>` (both optional). When
omitted, ask the user one AskUserQuestion before scaffolding:

  Q: "Who is this tour for, at what depth?"
  options drawn from:
    - personas: `skills/code-tour/domain/personas.yaml` (newcomer / contributor / reviewer / on-call / security / archaeologist)
    - depths: `skills/code-tour/domain/depths.yaml` (quick / standard / deep)

## Process

1. Discover the repo (root, README, entry points, language).
2. Map persona → focus (the personas.yaml describes each).
3. Compose 5-15 ordered steps per `step-types.yaml`. Each step:
   - `file: <relative path>` — must exist
   - `line: <1-based>` — verify with Read
   - `title: <short>` — the narrative beat
   - `description: <markdown>` — the why
4. Validate every file path is real (Read each before writing).
5. Write `.tours/<slug>.tour` JSON conforming to the CodeTour schema.

## Output

One JSON file under `.tours/`. Print a one-line confirmation with the
path + step count. **Do not** modify any source files.

## Iron laws

- Never invent file paths — every step's file must exist + line must
  be readable. Use Read or `cat -n` to verify before adding the step.
- Tour titles + descriptions are markdown but the JSON itself is
  CodeTour-spec — keep it valid (linter will catch malformed JSON).
- Persona + depth selection is recorded in the tour's `description`
  field so future readers know who it's for.

See `skills/code-tour/SKILL.md` for the full discipline + the
domain yamls for the personas / depths / step-type vocabulary.
