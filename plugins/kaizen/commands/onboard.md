---
name: onboard
description: Index a codebase for semantic search. SQLite + sentence-transformers (same model as /kaizen:trace-search and /kaizen:knowledge). Source files only (extension allowlist), comments stripped per-language, whitespace normalized. Project-scoped — db at `<repo>/.kaizen/onboard.db`. Pair with `/init` (Claude Code's built-in) for full onboarding: /init writes CLAUDE.md from a read-pass, /kaizen:onboard builds the semantic index.
---

# kaizen onboard

Build + query a semantic index of the current project's source code.

!`python3 ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/onboard_index.py ${ARGUMENTS:-stats}`

## Subcommands

- `index [--root PATH] [--no-git]` — incremental index. Sha-deduped per file; skips unchanged. By default uses `git ls-files` so `.gitignore` is honored automatically. Use `--no-git` outside a git repo (falls back to filesystem walk with the built-in ignore list).
- `reindex [--root PATH]` — wipe + rebuild.
- `search "<query>" [--top-k 10] [--lang LANG] [--json]` — semantic search; cosine ranking. `--lang` filters to one of: `rust`, `python`, `typescript`, `go`, `java`, `kotlin`, etc.
- `stats` — total files, total sloc, total bytes, counts by language.
- `get <id>` — full file record (snippet + path + sha + updated_at).
- `path` — print db path (default `<repo>/.kaizen/onboard.db`).
- `clear` — drop the index.

## Source-file scope

| Language    | Extensions                       |
|-------------|----------------------------------|
| Rust        | `.rs`                            |
| Python      | `.py` `.pyi`                     |
| JS / TS     | `.js .jsx .mjs .cjs .ts .tsx`    |
| Go          | `.go`                            |
| Java        | `.java`                          |
| Kotlin      | `.kt .kts`                       |
| Scala       | `.scala`                         |
| C / C++     | `.c .h .cpp .hpp .cc .hh .cxx`   |
| C#          | `.cs`                            |
| Swift       | `.swift`                         |
| PHP         | `.php`                           |
| Ruby        | `.rb`                            |
| Shell       | `.sh .bash .zsh`                 |
| Lua         | `.lua`                           |
| Elixir      | `.ex .exs`                       |
| Haskell     | `.hs`                            |
| OCaml       | `.ml .mli`                       |
| SQL         | `.sql`                           |
| YAML / TOML | `.yaml .yml .toml`               |

Always-skipped (regardless of extension): `node_modules/`, `target/`, `dist/`, `build/`, `.git/`, `__pycache__/`, `.venv/`, `venv/`, `vendor/`, `.cache/`, `tmp/`, `coverage/`, `.pytest_cache/`, `.mypy_cache/`, `.next/`, `.nuxt/`, `.output/`. Lockfiles (`package-lock.json`, `Cargo.lock`, `poetry.lock`, `go.sum`, etc.). Minified bundles (`*.min.js`, `*.bundle.js`). Anything matching `secret`, `credential`, `token` in the path (privacy filter — non-overridable).

Per-file size cap: `KAIZEN_ONBOARD_MAX_BYTES` (default 1 MB). Larger files are skipped.

## What gets embedded

For each indexed file: comments stripped per-language (C-family `//`/`/* */`, Python `#` + triple-quoted, hash-comment for shell/yaml/toml, etc.), whitespace normalized (trailing trimmed, blank-line runs collapsed). The cleaned content is what `sentence-transformers` embeds — semsearch matches on actual logic, not docstring noise.

Stored per row: path, language, raw byte count, post-clean SLOC, first ~2KB cleaned snippet, embedding (384-dim float32), content sha, mtime.

## MCP tools

The same index is exposed as an MCP server (`kaizen-onboard-search`):

- `mcp__plugin_kaizen_kaizen-onboard-search__onboard_search(query, top_k, language)`
- `mcp__plugin_kaizen_kaizen-onboard-search__onboard_index_status()`
- `mcp__plugin_kaizen_kaizen-onboard-search__onboard_index_run(no_git)`
- `mcp__plugin_kaizen_kaizen-onboard-search__onboard_get(file_id)`
- `mcp__plugin_kaizen_kaizen-onboard-search__onboard_recent(limit, language)`

Spawns on-demand; resolves project root via `git rev-parse --show-toplevel` or cwd at startup. Override with `KAIZEN_ONBOARD_ROOT` env.

## Onboarding flow — pair with `/init`

Recommended sequence when entering a new project:

```
/init
```

→ Writes `CLAUDE.md` with codebase orientation (Claude Code's built-in; a read-pass + structured prose).

```
/kaizen:onboard index
```

→ Builds `.kaizen/onboard.db` with embedded source. First run downloads the model (~80MB via uv).

```
/kaizen:onboard search "<question>"
```

→ Top-K relevant files returned with cosine scores. Pair with the `self-rag` skill for retrieval discipline.

The two commands compose: `/init` produces durable prose for the agent to read once at session start; `/kaizen:onboard` produces a queryable index for on-demand grounded lookups. CLAUDE.md = pinned context; onboard.db = retrieval surface.

## First-time setup

`knowledge_index.py`/`trace_index.py`/`onboard_index.py` all share the same uv-managed venv (PEP 723 inline metadata). First indexing call auto-installs `sentence-transformers`, `numpy`, CPU torch. Subsequent calls reuse the cached venv + model.

## Env

- `KAIZEN_ONBOARD_DB` — override db path (default `<repo>/.kaizen/onboard.db`)
- `KAIZEN_ONBOARD_MODEL` — override model (default `all-MiniLM-L6-v2`)
- `KAIZEN_ONBOARD_MAX_BYTES` — skip files larger than this (default 1000000)
- `KAIZEN_ONBOARD_ROOT` — override project root for the MCP server
