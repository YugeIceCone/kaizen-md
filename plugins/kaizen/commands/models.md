---
name: models
description: Ollama-backed local model management — list, pull, show, delete, copy, plus embed/chat smoke tests with full capability surface (streaming, thinking, structured outputs, vision) and `pin-embed` / `pin-chat` to bridge Ollama models into kaizen's profile.env. Replaces manual `ollama` CLI invocations + manual env-var edits for the kaizen embed/chat surfaces. Requires Ollama running at `:11434` (or `KAIZEN_OLLAMA_HOST` / `OLLAMA_HOST`). The `ollama` Python client is installed on-demand via `uv run --script` (PEP 723).
---

# kaizen models

Single slash command for the full Ollama model lifecycle + capability surface — wired through the official `ollama` Python client. No more leaving Claude Code to run `ollama pull foo` in another terminal.

!`bash ${CLAUDE_PLUGIN_ROOT}/bin/kaizen-models $ARGUMENTS`

## Subcommands

### Lifecycle

| Form | Effect |
|---|---|
| `models` or `models list` | table of locally-installed models |
| `models list --json` | machine-readable |
| `models ps` | currently-loaded (in-memory) models |
| `models pull <name>` | download a model; streams progress |
| `models show <name>` | metadata, family, params, quant level |
| `models delete <name> [--force]` | remove from local cache |
| `models cp <src> <dst>` | clone a model under a new name |
| `models host` | print the active Ollama host |

### Capability smoke tests

| Form | Effect |
|---|---|
| `models embed <model> "<text>"` | run an embedding; prints dim + first 8 floats |
| `models embed … --json` | full vector as JSON |
| `models chat <model> "<prompt>"` | run a chat completion |
| `models chat … --stream` | stream tokens to stdout (thinking, if any, goes to stderr in dim grey) |
| `models chat … --think` | enable reasoning for qwen3 / deepseek-r1 / o1-like models |
| `models chat … --format json` | structured output: free-form JSON |
| `models chat … --format @schema.json` | structured output: load JSON schema from a file |
| `models chat … --format '{"type":"object",…}'` | structured output: inline JSON schema |
| `models chat … --image PATH` | vision/multimodal; pass multiple times for multi-image |
| `models chat … --temperature 0.7` | sampling temperature |
| `models chat … --keep-alive 5m` | how long to keep model in memory |

You can also pipe the prompt: `echo "what is 2+2" \| kaizen-models chat qwen2.5:3b`.

### Web search (Ollama Cloud)

| Form | Effect |
|---|---|
| `models web-search "<query>"` | Ollama Cloud web search |
| `models web-search --max-results N` | how many results (default 5) |

Requires Ollama Cloud auth — `ollama signin` or set `OLLAMA_API_KEY`. Skipped silently if not configured.

### Bridge to kaizen profile.env

| Form | Effect |
|---|---|
| `models pin-embed <model>` | writes `KAIZEN_EMBED_BACKEND=http` + `KAIZEN_EMBED_HTTP_BASE_URL=http://localhost:11434/v1` + `KAIZEN_EMBED_HTTP_MODEL=<model>` to `~/.claude/.kaizen/profile.env` |
| `models pin-chat <model>` | writes the chat-side equivalents (`KAIZEN_SCRAPE_LLM_*`) |

After pinning, `source ~/.claude/.kaizen/profile.env` (or restart the shell) and kaizen's indexers + scrape will route through Ollama.

## Quickstart

```bash
# 1. install Ollama (one-time, host-level): https://ollama.com/download
# 2. pull a small chat + embed model
/kaizen:models pull qwen2.5:3b
/kaizen:models pull nomic-embed-text

# 3. wire kaizen to them
/kaizen:models pin-embed nomic-embed-text
/kaizen:models pin-chat  qwen2.5:3b

# 4. smoke-test
/kaizen:models embed nomic-embed-text "hello world"
/kaizen:models chat  qwen2.5:3b "name three primary colors" --stream
```

## Env

- `KAIZEN_OLLAMA_HOST` — Ollama base URL kaizen-side override (e.g. `http://192.168.1.50:11434`)
- `OLLAMA_HOST` — Ollama's standard env var; honored as fallback
- `OLLAMA_API_KEY` — Ollama Cloud (web-search) credential
- `KAIZEN_PROFILE_ENV` — override the path the `pin-*` subcommands write to

## Why this exists

Before v1.26.0, the user-facing model story was: install llama-server, configure GPU/quant by hand, manage a process per model, set env vars manually after each restart. Ollama bundles model download / lifecycle / serving into one daemon; this command surfaces that lifecycle through Claude Code's slash UI and auto-bridges the active model into kaizen's HTTP-first embed/chat config. The existing `_embed.py` HTTP path works against Ollama's OpenAI-compat `/v1/embeddings` unchanged — `pin-embed` just writes the right env vars.

## How the wrapper works

`bin/kaizen-models` routes every invocation through `uv run --script` so the inline `# /// script` block in `models.py` resolves `ollama>=0.4` on first call. Subsequent calls hit uv's cache and run in ~500ms. The package is small (~5MB, no torch) so cold-start is fast.
