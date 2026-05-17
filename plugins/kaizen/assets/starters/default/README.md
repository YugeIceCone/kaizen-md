# kaizen brain starter — `default`

A minimal but production-ready Second Brain. Seeded by
`/kaizen:brain seed default` (or `kaizen-brain seed default`).

## What you get

```
<your-brain>/
├── Persona.md       — your identity + directives (edit the placeholders)
├── REMEMBER.md      — capture/processing rules (template, customize freely)
├── Notes/
│   ├── pref-no-deletions.md             ← belief: never delete without explicit OK
│   ├── pref-tdd-for-new-code.md         ← belief: net-new code uses TDD
│   └── kaizen-allow-log-deletions.md    ← gate rule: *.log can be deleted
├── Inbox/           — drafts land here (brain-audit auto-fills)
├── Journal/         — daily entries (you write these or `/kaizen:brain capture`)
├── Projects/        — per-project beliefs / facts
├── People/          — per-person notes
├── Areas/           — long-running responsibilities
├── Resources/       — reference material
├── Tasks/           — active task tracking
├── Templates/       — note templates (project.md, person.md, ...)
└── Archive/         — retired notes
```

## After seeding

1. Edit `Persona.md` — replace `{{name}}`, `{{timezone}}`, `{{languages}}`,
   `{{role}}`. Optionally rewrite the `## Directives` section to match
   your own working principles.
2. Read the 3 starter Notes. Keep the ones that resonate, delete or
   re-author the ones that don't. They're STARTING POINTS, not rules.
3. Test the capture flow: open a session, say "remember this: <thing>"
   — kaizen's UserPromptSubmit hook should surface a capture hint.
4. Optionally schedule `kaizen-brain-evolve` weekly (cron or
   `/kaizen:daemon` cycle) to consolidate dupes + promote high-
   confidence Notes into Persona's Top Beliefs.

## Customization

Every starter file is just a Markdown file with YAML frontmatter.
Edit freely. The brain schema (`assets/schemas/note.schema.json`)
lists required + optional fields per `type` (belief / world-fact /
observation / experience).

For per-repo behaviour rules (gate overrides, deletion allowlists,
custom-pattern detectors), add Notes with a `kaizen:` frontmatter
block — see `kaizen-allow-log-deletions.md` for the shape.

## Why these 3 starter Notes?

| Note | Why universal |
|---|---|
| `pref-no-deletions.md` | Hard-won lesson across many sessions: dead-looking files are usually patterns. Read → analyze → dedup → migrate before any `rm`. |
| `pref-tdd-for-new-code.md` | Net-new code under TDD discipline avoids the worst class of regression bugs. Cheap to apply, expensive to retrofit. |
| `kaizen-allow-log-deletions.md` | Example of a `kaizen:` rule-block: lets you `git rm *.log` without the pre-deletion gate. Customize the path glob for your project. |

These are starting points — your brain becomes valuable when YOU
edit them.
