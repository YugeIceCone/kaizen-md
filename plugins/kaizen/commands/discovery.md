---
name: discovery
description: "Unified entry point for kaizen's 4 semantic indexes — codebase (onboard) / knowledge base (knowledge) / Claude docs (claude-docs) / web scrapes (scrape). No-args → 2-question wizard (which surfaces × which action) then dispatches the matching underlying slash. Triggers on \"semantic search\", \"index this\", \"search knowledge\", \"discovery menu\", \"what to index\", \"reindex\", \"build index\"."
argument-hint: "(empty = 2-Q wizard) | <surface> <action> [args]"
allowed-tools: ["AskUserQuestion", "Bash(uv run --script ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/onboard_index.py:*)", "Bash(uv run --script ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/knowledge_index.py:*)", "Bash(uv run --script ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/claude_docs_index.py:*)", "Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-scrape:*)"]
---

# /kaizen:discovery — unified semantic-search entry point

Single picker over kaizen's 4 distinct semantic indexes — each tuned
for a different content domain, each with its own SQLite store. Use
this when you want one of them and don't want to memorize four slashes.

| Surface | Underlying slash | Stores | Indexes |
|---|---|---|---|
| Codebase | `/kaizen:onboard` | `<repo>/.kaizen/onboard.db` | Source files (extension allowlist, comments stripped) |
| Knowledge base | `/kaizen:knowledge` | `~/.claude/.kaizen/knowledge.db` | Brain notes, plans, backlog, schemas, persona beliefs |
| Claude docs | `/kaizen:claude-docs` | `~/.claude/.kaizen/claude-docs.db` | Local Claude API/Code/SDK docs mirror |
| Web scrapes | `/kaizen:scrape` | `~/.claude/.kaizen/scrape/index.db` | Pages scraped via PocketFlow + ScrapeGraphAI |

## Interactive wizard (when `$ARGUMENTS` is empty)

Step the user through a 2-question AskUserQuestion call to capture
which surfaces × which action, then dispatch the matching slash(es).

### Question 1 — surfaces (multiSelect)

```
question:    "Which semantic indexes?"
header:      "Surfaces"
multiSelect: true
options:
  - label: "Codebase (onboard)"
    description: "Source files in this repo. Extension-allowlisted, comments stripped per-language. Dispatches /kaizen:onboard."
  - label: "Knowledge base (knowledge)"
    description: "Brain notes, project plans, backlog items, workflow schemas, persona beliefs. Dispatches /kaizen:knowledge."
  - label: "Claude docs (claude-docs)"
    description: "Local mirror of Claude API/Code/SDK docs. Dispatches /kaizen:claude-docs."
  - label: "Web scrapes (scrape)"
    description: "Pages previously scraped via PocketFlow + ScrapeGraphAI. Dispatches /kaizen:scrape."
```

### Question 2 — action

```
question:    "What to do with the picked surface(s)?"
header:      "Action"
multiSelect: false
options:
  - label: "Search (semantic query)"
    description: "Ask Q3 for the query text and dispatch <slash> search \"<query>\" per picked surface."
  - label: "Index / refresh"
    description: "Build or refresh each picked index (dispatches <slash> index or reindex)."
  - label: "Stats"
    description: "Print per-index stats (rows / size / last update). Dispatches <slash> stats per pick."
```

### After the 2 questions

- **Search:** ask a free-text Q3 for the query, then dispatch
  `<slash> search "<query>"` once per surface picked in Q1 (run them
  in parallel — they're independent reads). Aggregate results back to
  the user grouped by surface.
- **Index / refresh:** dispatch `<slash> index` (or `reindex` when
  available) per pick. These can be long-running; the agent should
  surface progress.
- **Stats:** dispatch `<slash> stats` per pick and summarize.

## Arg assembly

Per-surface dispatch slash + verb mapping:

| Q1 pick | Slash | Search verb | Index verb | Stats verb |
|---|---|---|---|---|
| Codebase | `/kaizen:onboard` | `search "<q>"` | `index` | `stats` |
| Knowledge base | `/kaizen:knowledge` | `search "<q>"` | `index` | `stats` |
| Claude docs | `/kaizen:claude-docs` | `search "<q>"` | `index` (run `bootstrap` first if never indexed) | `stats` |
| Web scrapes | `/kaizen:scrape` | `search "<q>"` | `<url>` to add a new page (this one is URL-driven, not bulk-index) | `stats` |

**Edge cases the wizard handles:**

- Empty Q1 picks → abort with a "pick at least one surface" message.
- Q2 = Search + Q3 query is empty → abort.
- Q2 = Index + Web scrapes picked → ask the user for the URL(s)
  separately; bulk `index` is not a `scrape` verb.

## Direct dispatch (with `$ARGUMENTS`)

When invoked with arguments, treat as `<surface> <action> [args]`
and pass through to the matching underlying slash. Surface aliases:

| Alias | Resolves to |
|---|---|
| `code` / `onboard` | `/kaizen:onboard` |
| `kb` / `knowledge` | `/kaizen:knowledge` |
| `docs` / `claude-docs` | `/kaizen:claude-docs` |
| `web` / `scrape` | `/kaizen:scrape` |

Example: `/kaizen:discovery code search "async semaphore"` →
`/kaizen:onboard search "async semaphore"`.

## Folded surface

`/kaizen:discovery` is **additive** — the 4 underlying slashes
(`/kaizen:onboard`, `/kaizen:knowledge`, `/kaizen:claude-docs`,
`/kaizen:scrape`) stay as direct entry points for power users.

## Related

- **Cluster:** discovery/search (see `/kaizen:help` for the full taxonomy).
- **Pairing:** `self-rag` skill — retrieval discipline for the
  search results.
