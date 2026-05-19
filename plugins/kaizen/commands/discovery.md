---
name: discovery
description: "Umbrella over kaizen 4 semantic indexes - codebase (onboard) / knowledge / Claude-docs / web-scrapes. No-args wizard. Triggers - "semantic search", "index this", "reindex", "build index"."
argument-hint: "(empty = 2-Q wizard) | <surface> <action> [args]"
allowed-tools: ["AskUserQuestion", "Bash(uv run --script ${CLAUDE_PLUGIN_ROOT}/scripts/indexers/onboard_index.py:*)", "Bash(uv run --script ${CLAUDE_PLUGIN_ROOT}/scripts/indexers/knowledge_index.py:*)", "Bash(uv run --script ${CLAUDE_PLUGIN_ROOT}/scripts/indexers/claude_docs_index.py:*)", "Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-scrape:*)"]
---

# /kaizen:discovery — unified semantic-search entry point

Single picker over kaizen's 4 distinct semantic indexes — each tuned
for a different content domain, each with its own SQLite store. Use
this when you want one of them and don't want to memorize four slashes.

| Surface | Underlying slash | Stores | Indexes |
|---|---|---|---|
| Codebase | `kaizen-onboard` | `<repo>/.kaizen/onboard.db` | Source files (extension allowlist, comments stripped) |
| Knowledge base | `kaizen-knowledge` | `~/.claude/.kaizen/knowledge.db` | Brain notes, plans, backlog, schemas, persona beliefs |
| Claude docs | `kaizen-claude-docs` | `~/.claude/.kaizen/claude-docs.db` | Local Claude API/Code/SDK docs mirror |
| Web scrapes | `kaizen-scrape` | `~/.claude/.kaizen/scrape/index.db` | Pages scraped via PocketFlow + ScrapeGraphAI |

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
    description: "Source files in this repo. Extension-allowlisted, comments stripped per-language. Dispatches kaizen-onboard."
  - label: "Knowledge base (knowledge)"
    description: "Brain notes, project plans, backlog items, workflow schemas, persona beliefs. Dispatches kaizen-knowledge."
  - label: "Claude docs (claude-docs)"
    description: "Local mirror of Claude API/Code/SDK docs. Dispatches kaizen-claude-docs."
  - label: "Web scrapes (scrape)"
    description: "Pages previously scraped via PocketFlow + ScrapeGraphAI. Dispatches kaizen-scrape."
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

### Question 3 — embedding model (always asked)

After Q1+Q2 resolve, the agent calls `discovery_list_embed_models()`
to fetch every locally-available embedding-capable Ollama model, then
builds Q3 dynamically from that list. Q3 fires regardless of Q2 — the
user can always pick or change the embedding model.

Per-action semantics for the Q3 pick:

| Q2 action | Non-default Q3 pick semantics |
|---|---|
| **Search** | No-op for THIS search (search uses each surface's build-time model — cosine isn't comparable across models). Pin the pick as the future default via `kaizen-models pin-embed <name>` if you want it persisted. |
| **Index / refresh** | Pass the model through to the underlying indexer (per-surface env or `--model` flag) so re-embed uses the new model. |
| **Stats** | Inform the user that stats are read-only — to actually switch, follow up with `/kaizen:discovery <surface> index` (or pick "Index / refresh" next time). Optionally pin the choice via `kaizen-models pin-embed <name>`. |

```
question:    "Which embedding model for the re-index?"
header:      "Embed model"
multiSelect: false
options:
  - label: "Keep each surface's current model (default)"
    description: "Each surface re-indexes against the model it was last built with. Safest — preserves dim + cosine semantics."
  # One option per Ollama model returned by discovery_list_embed_models().
  # If the tool returns []  (Ollama down or no embed models pulled),
  # show only the "default" option and note "Ollama unreachable — pull
  # a model with /kaizen:models pull <name> if you want a switch".
  - label: "<model.name> (dim=<model.dim>)"
    description: "Switch the picked surface(s) to this Ollama embedding model. Re-index is mandatory after a model change because dim differs and cosine isn't comparable across models."
```

Cap Q3 at 4 options total (AskUserQuestion contract). When >3 embed
models exist locally, show "default" + top 3 (sorted by dim then
name) and route the rest via `Other` follow-up.

### After the 2-3 questions

- **Search:** ask a free-text query, then dispatch
  `<slash> search "<query>"` once per surface picked in Q1 (run them
  in parallel — they're independent reads). Aggregate results back to
  the user grouped by surface. Search uses each surface's existing
  model — no Q3 needed.
- **Index / refresh:** for each Q1 pick, dispatch `<slash> index` (or
  `reindex` when available). When Q3 picked a non-default model,
  surface the model name in the dispatch so the underlying indexer
  honors it (per-surface env var or `--model` flag — see each
  underlying script's CLI for the exact knob).
- **Stats:** dispatch `<slash> stats` per pick and summarize.

## Arg assembly

Per-surface dispatch slash + verb mapping:

| Q1 pick | Slash | Search verb | Index verb | Stats verb |
|---|---|---|---|---|
| Codebase | `kaizen-onboard` | `search "<q>"` | `index` | `stats` |
| Knowledge base | `kaizen-knowledge` | `search "<q>"` | `index` | `stats` |
| Claude docs | `kaizen-claude-docs` | `search "<q>"` | `index` (run `bootstrap` first if never indexed) | `stats` |
| Web scrapes | `kaizen-scrape` | `search "<q>"` | `<url>` to add a new page (this one is URL-driven, not bulk-index) | `stats` |

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
| `code` / `onboard` | `kaizen-onboard` |
| `kb` / `knowledge` | `kaizen-knowledge` |
| `docs` / `claude-docs` | `kaizen-claude-docs` |
| `web` / `scrape` | `kaizen-scrape` |

Example: `/kaizen:discovery code search "async semaphore"` →
`kaizen-onboard search "async semaphore"`.

## Folded surface (formerly separate slashes)

Five search/index bins are reachable directly as power-user entry points:

| Concern | Bin (direct) | Use case |
|---|---|---|
| Codebase semantic index | `kaizen-onboard` | SQLite + sentence-transformers; project DB at `<repo>/.kaizen/onboard.db` — was `/kaizen:onboard` |
| Brain notes + plans + backlog semantic search | `kaizen-knowledge` | index / search / stats — was `/kaizen:knowledge` |
| Claude API/Code/SDK doc semantic search | `kaizen-claude-docs` | bootstrap / update / index / search / stats — was `/kaizen:claude-docs` |
| Web content semantic scrape | `kaizen-scrape` | PocketFlow async pipeline + Ollama default — was `/kaizen:scrape` |
| Per-package doc generator | `kaizen-docs` | Rust / JS-TS / Go / Python stdlib-only generator — was `/kaizen:docs` |

## MCP surface (agent-callable)

When the agent wants to query without going through the
AskUserQuestion wizard, the kaizen MCP server exposes:

| Tool | Purpose |
|---|---|
| `discovery_list_surfaces()` | Catalog of the 4 surfaces with slash + desc |
| `discovery_search(query, surfaces=None, top_k_per=4)` | Federated cosine; one call, grouped results, per-surface failure isolation |
| `discovery_stats(surfaces=None)` | Multi-surface index stats in one shot |
| `discovery_list_embed_models()` | Locally-available embedding-capable Ollama models (with capability + dim) — empty when Ollama is down |

Use `discovery_list_embed_models()` before deciding which surface to
re-index against a different backend, or when comparing dim/cost
tradeoffs across local embedding options.

## Related

- **Cluster:** discovery/search (see `/kaizen:help` for the full taxonomy).
- **Pairing:** `self-rag` skill — retrieval discipline for the
  search results.
