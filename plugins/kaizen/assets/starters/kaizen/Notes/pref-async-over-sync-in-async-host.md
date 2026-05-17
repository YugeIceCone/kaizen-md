---
created: 2026-05-12
updated: 2026-05-12
type: belief
confidence: 0.92
tags: [preference, code-quality, async, asyncio, playwright, mcp, fastmcp, runtime-compatibility]
sources_count: 1
freshness: stable
evidence:
  - source: Journal/2026-05-12.md
    quote: "add to rule/memory async over sync"
    date: 2026-05-12
    context: "kaizen v1.7.0 browser_mcp.py shipped with sync_playwright; first open_browser() invocation failed: 'It looks like you are using Playwright Sync API inside the asyncio loop. Please use the Async API instead.' v1.7.1 patched by switching to playwright.async_api throughout."

name: Async over sync in async host
---

# Async over sync when the host runtime is async

**Rule**: when writing code that runs inside an async/event-loop host
(FastMCP, FastAPI, asyncio.run, aiohttp, Starlette, anything driven by
`asyncio`), use the **async** variant of every library that ships both.
Sync APIs inside an event loop range from "subtly wrong" to "outright
rejected at runtime".

**Why:** Async libraries that detect an active event loop refuse the
sync entrypoint (Playwright is the strict example — it raises
immediately). Libraries that *don't* explicitly check still block the
loop, freezing every other coroutine — equally broken, just silent.

**How to apply:**

| Library | Sync (avoid in async host) | Async (prefer) |
|---|---|---|
| Playwright | `playwright.sync_api.sync_playwright` | `playwright.async_api.async_playwright` |
| httpx | `httpx.Client` | `httpx.AsyncClient` |
| SQLAlchemy | `sessionmaker` | `async_sessionmaker` (1.4+ asyncio) |
| Redis | `redis.Redis` | `redis.asyncio.Redis` |
| psycopg | `psycopg.Connection` | `psycopg.AsyncConnection` (psycopg3) |
| File I/O | `open()` | `aiofiles.open()` OR `asyncio.to_thread(...)` |
| subprocess | `subprocess.run` | `asyncio.create_subprocess_exec` |
| requests | `requests.get` (NEVER in async) | `httpx.AsyncClient.get` / `aiohttp` |

**When sync is OK in an async host:**

- The blocking call is *brief and unavoidable* (e.g. reading a small
  config file at startup). Wrap with `asyncio.to_thread(...)` if it's
  on a hot path.
- The function explicitly says "do not call from async context" in
  the host's docs and you're following that.

**Diagnostic signal:** `RuntimeError: It looks like you are using …
Sync API inside the asyncio loop` (or silent freeze with `Task was
destroyed but it is pending!` style warnings). When you see either —
switch to the async API.

**Concrete kaizen reference:** v1.7.0 → v1.7.1 fix. `browser_mcp.py`
used `sync_playwright()` inside `FastMCP` (which runs in asyncio).
Symptom surfaced on the first real `@mcp.tool() def open_browser()`
call. v1.7.1 rewrote all 14 tools as `async def` + `await
async_playwright()`. Same surface area, correct runtime model.

Related:
- [[pref-coding-skills-strict]] — KISS says use the simplest API that
  works; the simplest one is the async one when the host is async.
- [[pref-tdd-for-new-code]] — a single `open_browser` integration
  test in v1.7.0 would have caught this before merge.
