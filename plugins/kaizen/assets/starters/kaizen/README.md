# kaizen brain starter — `kaizen`

The maintainer's opinionated working principles, sanitized + bundled.
A more prescriptive starting point than `default` for developers who
want strong architectural conventions out of the box.

## When to use this vs `default`

| | `default` | `kaizen` |
|---|---|---|
| **Audience** | Anyone | Developers who like opinionated discipline |
| **Notes** | 3 (universal) | 13 (architecture + coding-skills + workflow patterns) |
| **Persona** | Minimal placeholders | Pre-filled `## Directives` (8 mandatory rules) |
| **Architecture stance** | Neutral | Onion-DDD strict |
| **TDD stance** | Recommended | Mandatory for net-new |
| **Discipline level** | Low ceremony | High ceremony |

If `default` feels too sparse and you want to start with a working
set of conventions you can tune down from, this is the starter.
If you prefer to author your own from scratch, use `default`.

## What's inside

```
kaizen/
├── Persona.md      — 8 directives + placeholders (name/timezone/...)
├── README.md       — this file
├── SessionNotes.md — running parking lot for ideas-for-later
└── Notes/
    ├── pref-no-deletions.md                  (from default)
    ├── pref-tdd-for-new-code.md              (from default)
    ├── kaizen-allow-log-deletions.md         (from default)
    ├── pref-coding-skills-strict.md          (8-principle suite)
    ├── pref-onion-architecture-strict.md     (Onion-DDD invocation)
    ├── pref-onion-tdd-strict.md              (TDD inside Onion layers)
    ├── pref-optional-feature-graceful-fallback.md  (Python lazy-load)
    ├── pref-orientation-pattern.md           (read-files-first)
    ├── pref-handoff-over-raw-log.md          (handoff > transcript)
    ├── pref-hard-gate-codification.md        (rules in HARD-GATE blocks)
    ├── pref-iteration-budget-framing.md      (autonomous-loop budget)
    ├── pref-no-tables-in-responses.md        (response-style preference)
    ├── pref-phased-work-commit-template.md   (atomic per-item commits)
    ├── pref-session-discovery-log.md         (capture as you go)
    ├── pref-async-over-sync-in-async-host.md (async runtime hygiene)
    └── pref-sizing-by-trace-not-hours.md     (sizing via trace + sem + grep)
```

## After seeding

1. Edit `Persona.md` — fill in `{{name}}`, `{{timezone}}`,
   `{{languages}}`, `{{role}}`. **Optionally** rewrite the `## Directives`
   section if you disagree with any of the 8 starter rules.
2. Skim every Note in `Notes/`. Each note is a complete belief with
   a `## Why` and a `## How to apply`. Keep what resonates;
   delete or re-author the rest.
3. `SessionNotes.md` is a top-level append-only "ideas for later"
   parking lot — write into it during sessions when something
   interesting surfaces but doesn't fit a Note yet. See the file
   header for the convention.
4. Schedule `kaizen-brain-evolve` weekly to promote high-confidence
   Notes into `Persona.md ## Top Beliefs`.

## Why these particular Notes?

This is what the maintainer has accumulated as load-bearing across
many projects, sanitized of project-specific identifiers. They're
all type=`belief` or type=`observation` — not facts about the world
but stable working principles. You can derive your own set from
patterns you keep re-explaining to teammates.

## Provenance

Distilled from `~/.claude/.kaizen/brain/Notes/` over multiple
project sessions (the maintainer's working brain). Specific paths,
project names, and personal references have been generalized
(`shodan workspace` → `<your project>`, `~/cherry86/` → `~/<user>/`,
etc.). The principle content is unchanged.
