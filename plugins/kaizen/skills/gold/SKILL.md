---
name: gold
description: Incidental-discovery + learnings tracker. Captures mid-work "ha!" moments — patterns, gotchas, hidden contracts — before they decay. Sits between dxm (raw events) and brain (consolidated beliefs). Triggers on "capture gold", "save this pattern", "incidental discovery", "gold pattern", "gotcha tracker", "learnings log", "kaizen-gold". Promote durable entries to CLAUDE.md or `~/.claude/.kaizen/brain/Notes/` via `promote --to <path> [--brain]`.
---

# kaizen gold

Catch the "ha!" moments mid-work. A pattern, gotcha, or hidden
contract you only discover by hitting it. Capture immediately so the
shape doesn't decay; later `promote` the durable ones into rules
(CLAUDE.md) or beliefs (brain Notes).

## Where it sits in the persistence stack

| Tier | What | Decay | Storage |
|---|---|---|---|
| **dxm** | raw lifecycle events (every hook fire, every tool call) | seconds-minutes | append-only JSONL per session |
| **gold** | named patterns + learnings (curated mid-work) | hours-days | `$KAIZEN_DIR/gold/<project-slug>/patterns.jsonl` |
| **brain Notes** | consolidated beliefs with frontmatter + confidence + tags | months | `~/.claude/.kaizen/brain/Notes/*.md` |

Gold is the **middle tier** — coarser than dxm (you name the
pattern), finer than brain (you haven't decided it generalizes yet).

## When to capture

- A subprocess / tool quirk that bit you (e.g. "cwd persists across
  Bash calls").
- A hidden contract you only discovered by building against it
  ("skill-suggest only matches QUOTED phrases").
- A per-dir gotcha (".kaizen/.gitignore whitelist overrides
  repo-root").
- A model-aware surprise ("JSONL strips `[1m]` from model id").

Rule of thumb: **if you'd warn a future agent about it, capture it**.

## When to promote (and where)

- **CLAUDE.md** — the pattern is a project convention. Append a
  bullet under the relevant section: `kaizen gold promote N --to CLAUDE.md`.
- **Brain Note (durable belief)** — the pattern generalizes across
  projects. `kaizen gold promote N --to ~/.claude/.kaizen/brain/Notes/<slug>.md --brain` builds the file with proper Note
  frontmatter (`type: belief`, `confidence: 0.5`, tags include `gold`).
- **A specific plan file** — the pattern is decision-local. Same
  promote, target the plan.

The `--brain` flag is the bridge: when the target doesn't exist, the
file is created as a real brain Note instead of being seeded with a
bare bullet line.

## CLI

```text
kaizen gold capture "<pattern>" [--tag X] [--source path:line] [--learned "<context>"]
kaizen gold list [--tag X] [--unpromoted] [--limit N] [--json]
kaizen gold show <id> [--json]
kaizen gold promote <id> --to <target> [--brain] [--note "<context>"]
kaizen gold path
```

Full per-flag docs: `kaizen help gold` or `kaizen gold --help`.

## Storage shape

One JSON record per line in `$KAIZEN_DIR/gold/<project-slug>/patterns.jsonl`:

```json
{"id": 1, "ts": "2026-05-17T11:48:47Z", "tag": "gitignore",
 "pattern": "Per-dir .kaizen/.gitignore whitelist overrides repo-root",
 "source": ".kaizen/.gitignore", "learned": "First commit didn't suppress audit reports",
 "promoted": false, "promoted_to": ""}
```

Atomic append (tempfile + `os.replace`). Per-project slug via
`cwd_to_slug` — different repos get separate stores under the same
`$KAIZEN_DIR/gold/` root.

## Env knobs

- `KAIZEN_DIR` — override the root (default `~/.claude/.kaizen/`)
- `KAIZEN_GOLD_FILE` — override the JSONL path directly (tests use this)

## Anti-patterns

- **Don't capture every dxm event.** Gold is curated. If the agent
  fires `capture` automatically on every tool call you've duplicated
  dxm with worse retention.
- **Don't promote without re-reading the entry first.** `show <id>`
  is cheap; do it before promote so the destination ends up with the
  exact phrasing you want.
- **Don't promote stale entries.** If the gotcha got fixed at the
  source (e.g. the hook now handles the edge case), delete the entry
  via manual jsonl edit rather than promoting a dead note.
