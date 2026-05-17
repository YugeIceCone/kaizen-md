---
created: {{today}}
updated: {{today}}
type: belief
confidence: 0.95
tags: [preference, workflow, refactor, deletions]
sources_count: 1
freshness: fresh
---

# No deletions without explicit user authorization

A foundational discipline: never remove code, files, or data the user
hasn't explicitly approved for deletion. Orphan-looking files are
USUALLY patterns — read first, deduplicate, migrate, consolidate
BEFORE any `rm` / `git rm`.

## Why

Dead-looking code frequently turns out to be:
- A re-export shim that consumers still hit
- A pattern referenced by docs or tutorials
- An interface placeholder for a future feature
- A test fixture only loaded under specific conditions

Deletion-first is regret-first. The cost of asking the user one more
question vastly outweighs the cost of restoring deleted work.

## How to apply

When you encounter an apparently-unused file:

1. **Read it in full.** Understand what it does + why it exists.
2. **Grep for references.** Find every importer / mention / link.
3. **Check git history.** Was it added recently? By whom? Why?
4. **Look for patterns.** Is it part of a series of similar files?
5. **Ask the user.** Surface what you found + propose options
   (delete / dedup / migrate / consolidate / leave).

## When deletion IS appropriate

- User explicitly says "delete X" (specific, not "clean up").
- Log files, build artifacts, *.tmp — covered by gate allowlists
  (see `kaizen-allow-log-deletions.md` for the rule shape).
- Vestigial files surfaced by `kaizen-path-migrate status` after
  the user reviews and approves.
