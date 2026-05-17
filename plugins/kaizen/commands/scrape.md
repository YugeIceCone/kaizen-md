---
name: scrape
description: Scrape + synthesize web content into a semantic SQLite index. PocketFlow async pipeline (FetchURLs → ScrapeFanOut → Synthesize → EmbedAndPersist) wrapping ScrapeGraphAI's SmartScraperGraph; stored in ~/.claude/.kaizen/scrape/index.db using the same indexer pattern as trace/knowledge/onboard. Defaults to local Ollama (no API key); openai/* models via env var.
argument-hint: [<url>|batch <urls.txt>|search "<query>"|stats|get <id>|list|clear]
---

# kaizen scrape

Scrape web content + embed it into a SQLite semantic index. Local Ollama by default.

!`bash -c 'exec ${CLAUDE_PLUGIN_ROOT}/bin/kaizen-scrape ${ARGUMENTS:-stats}'`

Claude can also query the scraped index without a slash command via the `kaizen-scrape` MCP server:

- `scrape_search(query, top_k=8)` — cosine top-k
- `scrape_stats()` — items / model / last_indexed_ts
- `scrape_get(item_id)` — full content of one indexed item
- `scrape_list_recent(limit=20)` — latest N by `scraped_at`
