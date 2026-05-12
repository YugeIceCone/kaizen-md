---
name: knowledge
description: Semantic search over kaizen's knowledge surface — Remember brain notes, project plans, backlog items, workflow schemas, persona beliefs. SQLite + sentence-transformers (same model as /kaizen:trace-search). Privacy-safe by default (signature embedding only; body opt-in). Pair with `self-rag` skill for retrieval discipline.
---

# kaizen knowledge

SQLite-backed semantic search over kaizen's non-trace knowledge sources. Sibling of `/kaizen:trace-search` (which indexes trace events) — this one indexes the **stable corpus** the agent draws on for project context.

!`python3 ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/knowledge_index.py ${ARGUMENTS:-stats}`

## Subcommands

- `index [--embed-body]` — incremental index of all sources. Default embeds only the signature (source + title + tags); `--embed-body` also embeds the first ~400 chars of the body.
- `reindex [--embed-body]` — drop the db and rebuild from scratch.
- `search "<query>" [--top-k 10] [--source <type>] [--json]` — semantic cosine-similarity search. `--source` filters to one of: `brain-note`, `plan`, `backlog`, `schema`, `persona`.
- `stats` — count by source, model, last-indexed timestamp.
- `get <id>` — fetch one item by db id (full record sans embedding bytes).
- `path` — print the db path (`~/.claude/.kaizen-knowledge/index.db` by default).
- `clear` — delete the index. Next `index` rebuilds.

## Sources indexed

| Source       | Where                                              | What becomes a unit |
|--------------|----------------------------------------------------|---------------------|
| `brain-note` | `~/.claude/brain/Notes/*.md`                       | One per `.md`; title = `name:` frontmatter or stem; tags from frontmatter |
| `plan`       | `<repo>/plans/**/*.md` (incl. archive)              | One per `.md`; title = first `# H1` |
| `backlog`    | `<repo>/.workflow/backlog.json`                    | One per item; title = `BK-N title` |
| `schema`     | built-in + `~/.claude/kaizen-schemas/` + project   | One per `schema.yaml`; title = `schema:<name>` |
| `persona`    | `~/.claude/brain/Persona.md` (Top Beliefs section) | One per `[[Notes/...]]` reference in the list |

## Privacy

By default, **only the signature is embedded**: source + title + tags. The body / snippet is stored in SQLite for display but is not embedded. The agent sees the snippet on `search` / `get` but the semantic vector itself doesn't carry body content.

Use `--embed-body` if you want retrieval to match on body content (better recall, larger trade against accidental sensitive-content matching). Files matching `*secret*`, `*credential*`, `*token*` in their path are **always skipped** regardless of flag.

## Pairing with Self-RAG

The matching agent-side discipline lives in the `self-rag` skill. The pattern:

1. Before answering a question that depends on project-specific context, decide: would retrieval help?
2. If yes: `/kaizen:knowledge search "<focused query>"`
3. For each top result: relevance check (does it actually apply?), support check (does it ground my response?).
4. After answering, self-assess: did I miss obvious context?

See `skills/self-rag/SKILL.md` for the full retrieval-discipline body.

## MCP tools (v1.17.0+)

The same index is also exposed as an MCP server (`kaizen-knowledge-search`) registered in the plugin's `.mcp.json`. Sibling of `kaizen-trace-search`. Tools available to Claude in any session:

- `mcp__plugin_kaizen_kaizen-knowledge-search__knowledge_search(query, top_k, source)`
- `mcp__plugin_kaizen_kaizen-knowledge-search__knowledge_index_status()`
- `mcp__plugin_kaizen_kaizen-knowledge-search__knowledge_index_run(embed_body)`
- `mcp__plugin_kaizen_kaizen-knowledge-search__knowledge_get(item_id)`
- `mcp__plugin_kaizen_kaizen-knowledge-search__knowledge_recent(limit, source)`

The MCP server spawns on-demand when the first tool fires. Same uv-managed venv as the CLI; SQLite DB is shared.

## First-time setup

```bash
# Install the dependencies via uv (one-time):
uvx --from sentence-transformers python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Index once:
/kaizen:knowledge index

# Search:
/kaizen:knowledge search "onion ddd boundary lint"
```

The PEP 723 inline metadata in `knowledge_index.py` auto-installs `sentence-transformers`, `numpy`, and CPU torch into a uv-managed venv on first invocation, so `uv run --script` works without any external setup.
