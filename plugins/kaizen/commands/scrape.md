---
name: scrape
description: Scrape + synthesize web content into a semantic SQLite index. PocketFlow async pipeline (FetchURLs → ScrapeFanOut → Synthesize → EmbedAndPersist) wrapping ScrapeGraphAI's SmartScraperGraph; stored in ~/.claude/.kaizen/scrape/index.db using the same indexer pattern as trace/knowledge/onboard. Defaults to local Ollama (no API key); openai/* models via env var.
---

# kaizen scrape

LLM-driven scrape that ends in a queryable SQLite index. Three kaizen patterns composed:

1. **PocketFlow async wireframe** (from `flow_demo.py`) — Node+Flow with `asyncio.gather` fan-out.
2. **ScrapeGraphAI** — `SmartScraperGraph(prompt, source, config).run()` produces structured extraction.
3. **kaizen indexer** — same SQLite + sentence-transformers (`all-MiniLM-L6-v2`, 384-dim) shape as trace, knowledge, onboard.

!`bash ${CLAUDE_PLUGIN_ROOT}/bin/kaizen-scrape $ARGUMENTS`

## Subcommands

| Form                                     | Effect                                                         |
|------------------------------------------|----------------------------------------------------------------|
| `scrape <url>`                           | Run the pipeline once; persist + print one-line result.        |
| `scrape <url> --prompt "..."`            | Override the default extraction prompt.                        |
| `scrape <url> --no-embed`                | Run scrape, skip embed + DB write (dry).                       |
| `scrape <url> --json`                    | Emit the full result as JSON.                                  |
| `batch <urls-file>`                      | One URL per line; fan-out scrape via `asyncio.gather`.         |
| `search "<query>"`                       | Cosine search; `--top-k`, `--json`.                            |
| `stats`                                  | Total / model / last-scrape-ts.                                |
| `get <id>`                               | Full row (incl. raw `content_json` decoded).                   |
| `list [--limit N]`                       | N most-recent items.                                           |
| `path`                                   | DB path.                                                       |
| `clear`                                  | Drop the index.                                                |
| `detect-llm [--refresh]`                 | Probe local LLM endpoints; print the chosen `provider/model`.  |
| `recommend [--json]`                     | List curated Ollama chat-model picks for SmartScraperGraph (v1.29.0+ — winner: `qwen2.5:7b`). Marks already-pulled models with `✓`. |

## Pipeline (the four async nodes)

```
FetchURLs → ScrapeFanOut → Synthesize → EmbedAndPersist
            (asyncio.gather                    (terminal)
             over N urls)
```

- **FetchURLs** — validates input, resolves the default prompt from `config.SCRAPE_DEFAULT_PROMPT`.
- **ScrapeFanOut** — one `SmartScraperGraph` per URL, executed in parallel via `asyncio.to_thread` + `asyncio.gather`.
- **Synthesize** — flattens each extraction to `{url, title, text, content_json}`. Drops fields named `api_key`/`secret`/`token`/`password`/`auth`/`credential` at any depth (privacy filter).
- **EmbedAndPersist** — encodes `title + text` with `sentence-transformers`, writes `(url, prompt, title, content_json, text_extract, embedding, sha, ts)` rows. `sha = sha1(url|prompt)[:16]` → re-scraping the same `(url, prompt)` pair upserts.

## LLM provider — zero-config (v1.24.1+)

If neither `KAIZEN_SCRAPE_LLM_MODEL` nor `KAIZEN_SCRAPE_LLM_BASE_URL` is set, the script probes common local-LLM endpoints in order (each with a 2-second timeout) and uses the first one that responds with a usable model list:

| Port  | Server                                    | API style                |
|-------|-------------------------------------------|--------------------------|
| 8080  | **llama.cpp `llama-server`**              | OpenAI-compatible (`/v1/...`) |
| 11434 | Ollama                                    | Native (`/api/tags`)     |
| 1234  | LM Studio                                 | OpenAI-compatible        |
| 8000  | vLLM                                      | OpenAI-compatible        |
| 5000  | text-generation-webui (oobabooga)         | OpenAI extension         |

The resolved endpoint is cached at `~/.claude/.kaizen/scrape/llm_endpoint.json` so subsequent runs skip the probe. Inspect / refresh manually:

```
/kaizen:scrape detect-llm
/kaizen:scrape detect-llm --refresh
```

### llama.cpp setup

```bash
llama-server -m /path/to/model.gguf --port 8080
```

Now `/kaizen:scrape detect-llm` resolves it; `/kaizen:scrape scrape <url>` uses it. No keys, no config.

### Explicit overrides

Env vars win over zero-config:

```
KAIZEN_SCRAPE_LLM_MODEL=ollama/llama3
KAIZEN_SCRAPE_LLM_BASE_URL=http://localhost:11434
KAIZEN_SCRAPE_LLM_AUTO=0                          # disable the probe entirely
```

### Switch to OpenAI

```
KAIZEN_SCRAPE_LLM_MODEL=openai/gpt-4o-mini
OPENAI_API_KEY=...
unset KAIZEN_SCRAPE_LLM_BASE_URL                  # use openai.com, not a local server
```

## SQLite schema

```sql
CREATE TABLE scrape_items (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  url          TEXT NOT NULL,
  prompt       TEXT NOT NULL,
  title        TEXT,
  content_json TEXT NOT NULL,        -- raw scrapegraph extraction
  text_extract TEXT NOT NULL,        -- denormalized text for snippet + embedding
  embedding    BLOB NOT NULL,        -- 384-dim float32
  sha          TEXT UNIQUE NOT NULL, -- sha1(url|prompt)[:16]
  ts           TEXT NOT NULL
);
```

DB at `~/.claude/.kaizen/scrape/index.db` (v1.22.0 unified layout). Override via `KAIZEN_SCRAPE_DIR`.

## Examples

```
/kaizen:scrape scrape https://example.com
/kaizen:scrape scrape https://docs.foo.io --prompt "List API endpoints and their HTTP verbs."
/kaizen:scrape batch urls.txt --json
/kaizen:scrape search "rate limit policy"
/kaizen:scrape get 7
```

## Pairs with

- `/kaizen:knowledge` — semantic search over brain notes / plans / backlog (different corpus, same model).
- `/kaizen:onboard` — semantic search over the project codebase (same model).
- `/kaizen:trace-search` — semantic search over kaizen trace events (same model).

The four indexers share `all-MiniLM-L6-v2` + 384-dim cosine, so query vectors are interchangeable in principle.
