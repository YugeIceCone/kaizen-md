---
created: {{today}}
updated: {{today}}
tags: [session-notes, parking-lot, ideas]
---

# Session Notes

A running, append-only **parking lot for ideas surfaced during work**
that don't yet warrant a full Note, a Task, or a backlog item.

## The convention

- **Append at the bottom.** Newest entries last. Don't reorganize
  history.
- **Date-stamp each entry.** Use `## YYYY-MM-DD — <topic>`. One
  section per session per topic.
- **Capture verbatim.** When something interesting surfaces during
  a conversation — a "we could also..." or a "remember to look at..."
  — write the exact wording. Polish later.
- **Periodically promote.** Once a week (or whenever you re-read
  this file), move proven ideas into:
  - `Notes/<slug>.md` — beliefs/observations that survived re-derivation
  - `Tasks/tasks.md` — concrete work-to-do
  - `<repo>/.kaizen/workflow/backlog.json` — project-scoped backlog items
  - `Projects/<project>/<slug>.md` — project-specific decisions
- **Cross out (don't delete) what didn't pan out.** Use `~~struck~~`
  so future-you can see what was tried + rejected.

## Why this exists

Without a parking lot, ideas surfaced mid-session either:
1. Get acted on immediately (derails the current work), or
2. Get forgotten by next session's end.

SessionNotes is the middle path: capture in 5 seconds, evaluate
later in a focused review.

## Distinct from siblings

| File | When to use |
|---|---|
| `SessionNotes.md` (this file) | Parking lot for ideas + maybe-laters |
| `Journal/<date>.md` | Daily entries — what happened, what changed |
| `Inbox/` | Drafts from the brain-audit auto-capture flow (review + route) |
| `Tasks/tasks.md` | Active commitments with verify steps |
| `Notes/<slug>.md` | Curated beliefs/observations (the durable ones) |

---

## {{today}} — starter installed

- Replace this section with your first real session entry.
- Format suggestion: bullets for individual ideas, sub-headings
  (`### sub-topic`) when an idea has multiple sub-points.
