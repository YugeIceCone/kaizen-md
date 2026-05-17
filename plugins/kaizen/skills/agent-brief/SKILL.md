---
name: agent-brief
description: Use this skill the first time you enter a kaizen-installed repo or session as a fresh agent / subagent. Dense, AI-facing capability map of the kaizen plugin — every commit-gate check, hook, trace stream, MCP tool, agent, and state file with exact invocation patterns. Read this BEFORE invoking any /kaizen:* command, browser tool, or backlog mutation. Triggers on "tell me about kaizen", "what does kaizen do", "kaizen capabilities", "orient me in this repo", "kaizen overview", "show me kaizen tools", "agent brief", "fresh session in kaizen repo", "subagent kaizen handoff", "what's installed here", "kaizen surface area", "kaizen state".
---

# Kaizen — agent brief

You are an LLM/agent. This skill is your machine-readable map of the kaizen plugin. Skip prose for humans; everything below is operationally precise.

## What kaizen is

One sentence: **kaizen = pre-commit gate + structured backlog + multi-layer observability + on-demand subagents, all behind `/kaizen:*` slash commands, `kaizen-*` shell binaries, and `mcp__plugin_kaizen_*` tool surfaces.**

It's a discipline plugin (Conventional Commits, sizing-by-trace, no-deletions-without-auth, paired tests, brain-rule severity overrides). Every commit in an installed repo passes a 12-check gate. Every tool call by Claude flows through hooks that emit structured trace events.

## When this skill applies — check first

You're in a kaizen-installed repo if any of these are true:

```bash
test -f .kaizen.toml                                              # repo-level marker
test -L .kaizen/hooks/pre-commit                                  # gate active
git config --get core.hooksPath | grep -q '\.kaizen/hooks'        # local hooksPath set
```

You're in a kaizen-installed session if `kaizen:*` commands appear in your skill catalog (look for `/kaizen:backlog`, `/kaizen:gate`, `/kaizen:trace`).

If neither: this skill doesn't apply — kaizen isn't here.

## Capability layers (8)

### 1. Pre-commit gate (12 checks)

Path: `<plugin>/skills/workflow/scripts/pre-commit.sh` symlinked to `<repo>/.kaizen/hooks/pre-commit`.

| # | Check | Block / Warn / Skip |
|---|---|---|
| 1 | compile-barrier (cargo check / tsc --noEmit / configured) — cached by `(cmd, sha1(staged-diff))` | block |
| 2 | Conventional Commits prefix on commit message | block |
| 3 | Structural diff → architecture log row appended | warn |
| 4 | Plan-phase named in commit msg → `- [x]` ticked | warn |
| 5 | Pre-deletion gate (`git rm`) consulted against brain `deletion-allow` rules | block |
| 6 | CLAUDE.md scanned for forbidden volatile data (commit SHAs, point-in-time inventories) | warn |
| 7 | New non-test source → paired test present | warn (skippable via `KAIZEN_SKIP_TDD_CHECK=1`) |
| 8 | Project `verify_cmd` from `.kaizen.toml` | block if non-zero |
| 9 | Secret pattern scan (AWS, GitHub, OpenAI, Anthropic, JWT, private keys) | block (bypass `KAIZEN_ALLOW_SECRET=1`) |
| 10 | Backlog .md/.json drift check | warn |
| 11 | brain-sourced `custom-pattern` rules (regex over staged diff) | per-rule warn/block |
| 12 | Context-window advisory (red zone warn — only fires if `CLAUDE_CONTEXT_TOKENS` env set) | warn |

Plus a **suggestion engine** that emits skill-pointers based on diff content:
- 100+ LOC single file → `coding-skills:kiss + separation-of-concerns`
- Repeated string literal >40 chars → `coding-skills:dry`
- 8+ pub fn / file → `coding-skills:solid`
- 4-level method chain → `coding-skills:law-of-demeter`
- `cfg(feature)` or no-impl trait → `coding-skills:yagni`
- TODO/FIXME near edits → `coding-skills:boy-scout-rule`
- New file ext diverges from siblings → `coding-skills:convention-over-configuration`
- Net-new source file → `tdd`
- Cargo/package.json dep change → `onion-ddd-workflow`

**Invoke**: gate runs automatically on `git commit`. Dry-run: `/kaizen:gate`.

### 2. Backlog (JSON-source-of-truth)

Path: `<repo>/.kaizen/workflow/backlog.json` (source) + `.kaizen/workflow/backlog.md` (generated). Sections: `next_up`, `in_flight`, `done`, `parked`, `decisions`.

**CLI** (`backlog.py`):
```bash
backlog.py list [next_up|in_flight|done|parked|all]
backlog.py add --title "..." --probe "<cmd>" --verify "<cmd>" [--ref ... --tags a,b]
backlog.py start BK-N                    # next_up → in_flight
backlog.py tick BK-N --committed <sha>   # in_flight → done
backlog.py park BK-N --reason "..."
backlog.py decision --text "..." --why "..."
backlog.py render                        # regenerate .md
backlog.py verify                        # check .md/.json sync
```

Slash: `/kaizen:backlog` (same surface).

**Sizing rule** — NEVER by clock-time:
- ≤3 files, 0 manifest edits, 0 trait moves → micro backlog item
- 4–15 files OR 1 manifest edit OR 1 trait move → split into sibling micros
- ≥16 files OR ≥2 manifest edits OR cross-context OR carve-out trigger → promote to `plans/<date>-<slug>.md`

Hand-editing `.md` is corruption (pre-commit gate detects drift via `backlog.py verify`).

### 3. Agents (3 read-only subagents)

In `<plugin>/agents/`. Each declares worktree-isolation contract in body; caller passes `isolation: "worktree"` when dispatching.

| Agent | Purpose | Output |
|---|---|---|
| `kaizen-reviewer` | Audit staged diff vs 12 gate checks + brain severity overrides | `{verdict: green\|yellow\|red, checks, diff_sha1, rationale}` JSON |
| `kaizen-backlog-curator` | Mine session JSONL for backlog candidates with probe + verify; dedup against existing items + brain Notes | candidate list with `ref` quotes |
| `kaizen-debt-auditor` | Scan codebase vs onion-DDD + 8 coding-skills + depth invariants | findings ranked by `severity × ease` |

Dispatch with the `Agent` tool (`subagent_type` = exact name, `isolation: "worktree"`).

### 4. Trace (unified event log)

Path: `~/.claude/.kaizen-trace/events.jsonl` (current) + `events-*.jsonl.gz` (rotated).

Schema: `{ts, src, evt, sid, tool, ms, data}` where `src ∈ {hook, agent, llm, tool, user, cc, plugin}`.

**Query**:
```bash
kaizen-trace                                  # last 20 events
kaizen-trace query --since 1h --src hook
kaizen-trace stats --since 24h                # counts by src/evt/tool + p50/p95/max latency
kaizen-trace query --sid <uuid> --json        # session replay
```

**What's instrumented automatically**:
- All 7 kaizen hooks (SessionStart, UserPromptSubmit, PreToolUse-bash, PostToolUse-bash, PostToolUse-drain, Stop, PreCompact)
- LLM calls (if `kaizen-trace-proxy` running + `ANTHROPIC_BASE_URL` set)
- All MCP tool boundaries (via PreToolUse/PostToolUse — `mcp__plugin_kaizen_*` events)

Privacy: hooks log only `session_id` from the event payload — never `tool_input` / `tool_response`. v1.6.1+ default.

Disable: `KAIZEN_TRACE_DISABLE=1`.

### 5. LLM logging proxy

`scripts/llm_proxy.py` — stdlib HTTP proxy that forwards `localhost:8765 → api.anthropic.com`, logs each request/response to trace as `src=llm` (model, message count, input/output tokens, latency). Auth headers scrubbed.

```bash
kaizen-trace-proxy start
export ANTHROPIC_BASE_URL=http://127.0.0.1:8765   # CC sessions in THIS shell trace LLM
# (restart CC after export — env is inherited at spawn)
```

Streaming SSE handled (chunk passthrough + final `message_delta` parsed for `output_tokens`).

### 6. Daemon + watcher (background hygiene)

| Mode | Trigger | Interval |
|---|---|---|
| Cron daemon (`kaizen-daemon install`) | crontab entry | every 30 min (configurable) |
| Watcher (`kaizen-watch start`) | hash-poll loop | every 5 s (configurable) |

Each tick:
1. SHA1-hash plugin source vs version-named cache → refresh-cache on drift
2. Read `git ls-remote origin master` (no fetch; notify-only unless `KAIZEN_DAEMON_AUTOPULL=1`)
3. Run hygiene fixes: prune old cache versions, drop drained inbox >7d, prune backups >10, validate brain rules, re-render drifted `backlog.md`

State: `~/.claude/.kaizen-daemon/{state.json,log,watcher.pid,llm-proxy.pid}`.

### 7. Browser MCP (v1.7.1+)

Server: `scripts/browser_mcp.py` registered in `.mcp.json` as `kaizen-browser`. Uses `playwright.async_api` (NOT sync_api — FastMCP runs in asyncio loop).

Tools (all `mcp__plugin_kaizen_kaizen-browser__*`):
- `open_browser(headless=False, viewport_width=1280, viewport_height=800)`
- `close_browser()`
- `navigate(url, wait_until=load)` / `current_url()`
- `click(selector, timeout_ms=10000)` — accepts CSS, `text=…`, `role=…`, any Playwright locator
- `type_text(selector, text, timeout_ms)` / `press_key(key)`
- `wait_for(selector, state=visible, timeout_ms)`
- `get_text(selector=body)` / `get_html(selector=html)` / `screenshot(path, full_page=False)`
- `list_links()` / `list_inputs()` / `evaluate(js_expression)`

State: single browser, single page, persists across tool calls within one MCP server lifetime. Server spawned on-demand by CC at first tool invocation.

Setup gate: `kaizen-browser check` confirms uv + deps + Chromium binary.

### 8. Bin wrappers (in `~/.local/bin/`, on $PATH after `/kaizen:setup`)

```
kaizen <subcmd> [args]    # multiplexer: kaizen flow . / kaizen docs scan / etc.
kaizen-backlog            kaizen-cache              kaizen-context
kaizen-daemon             kaizen-docs               kaizen-flow
kaizen-hygiene            kaizen-inbox              kaizen-rules
kaizen-trace              kaizen-trace-proxy        kaizen-update
kaizen-watch              kaizen-browser
```

Each is a self-locating bash shim that resolves to the real script via `python3 os.path.realpath`. Symlinks survive plugin updates.

## Failure modes — recognize + recover

| Symptom | Cause | Recovery |
|---|---|---|
| `Unknown command: /kaizen:*` | Plugin reload missed the new slash command | `/reload-plugins` (and rerun if it doesn't take — caching) |
| `kaizen-update` reports cache stale | `/plugin update` doesn't refresh local marketplaces | `/kaizen:update` (auto-reloads if changes applied; reads version from plugin.json + rsyncs the cache slot) |
| Gate fails on `compile-barrier` | Cargo/TS/Go check failed | Read `/tmp/kaizen-compile.log` |
| Gate blocks on `pre-deletion` | Trying to `git rm` without `KAIZEN_ALLOW_DELETE=1` or matching `deletion-allow` brain rule | Either authorize via env OR add a `deletion-allow` rule via `kaizen-rules template deletion-allow` |
| Inbox shows pending messages | User typed while Claude was busy | Acknowledge each entry before continuing the current task |
| Browser MCP errors with "Sync API inside asyncio loop" | You're on v1.7.0 (pre-fix) | `/kaizen:update` to v1.7.1+ |

## Common agent tasks → exact invocation

| Task | Invocation |
|---|---|
| Dry-run the gate against current diff | `/kaizen:gate` |
| Add a backlog item | `kaizen-backlog add --title "..." --probe "<grep ...>" --verify "<cmd>"` |
| Promote BK-N from next_up to in_flight | `kaizen-backlog start BK-N` |
| Mark BK-N done after commit | `kaizen-backlog tick BK-N --committed <sha>` |
| Audit codebase for tech debt | dispatch `kaizen-debt-auditor` agent with `isolation: "worktree"` |
| Replay last hour of hook events | `kaizen-trace query --src hook --since 1h` |
| Open a real browser | invoke `mcp__plugin_kaizen_kaizen-browser__open_browser` (headless=True default-safe) |
| Generate per-package docs | `kaizen-docs scan` |
| Refresh plugin cache after a kaizen push | `/kaizen:update` (auto-reloads on changes) |
| Add a brain rule | `kaizen-rules template deletion-allow > ~/.claude/.kaizen/brain/Notes/kaizen-allow-X.md` then edit |

## State data streams (where to look)

| Layer | Path | What |
|---|---|---|
| CC transcript | `~/.claude/projects/<slug>/<sid>.jsonl` | Authoritative, every tool call + response |
| Trace | `~/.claude/.kaizen-trace/events.jsonl` | Structured cross-source events |
| Inbox | `~/.claude/kaizen-inbox/*.json` | User messages captured during busy moments |
| Daemon log | `~/.claude/.kaizen-daemon/log` | Hash drift, hygiene activity |
| Proxy log | `~/.claude/.kaizen-daemon/llm-proxy.log` | Raw `llm_proxy.py` stdout |
| Cache | `<repo>/.kaizen/cache/*.json` | Compile-barrier + agent verdicts (per-repo) |
| Compile log | `/tmp/kaizen-compile.log` | Last gate compile-barrier output |
| Backlog | `<repo>/.kaizen/workflow/backlog.{json,md}` | Active work |
| Workflow state | `<repo>/.kaizen/workflow/state.json` | Active `/workflow` routine |
| Architecture log | `<repo>/.kaizen/workflow/progress.md` | Append-only structural change log |
| Snapshot | `<repo>/.kaizen/workflow/snapshot.md` | Last session handoff |
| Backups | `~/.claude/backups/kaizen/<repo-slug>/*.tar.gz` | Pre-risky-op snapshots |
| Brain rules | `~/.claude/.kaizen/brain/Notes/kaizen-*.md` | deletion-allow / check-severity / custom-pattern |

## Pointers to deeper skills

When a task crosses your default knowledge, load these (via `Skill` tool):

| Trigger | Skill |
|---|---|
| About to commit / cadence question / sizing dispute | `kaizen:workflow` (the git-workflow Iron Laws) |
| Structural change touching layer boundaries | `kaizen:onion-ddd-workflow` |
| Net-new code (no existing tests yet) | `kaizen:tdd` |
| Code-quality dimension is named (DRY/KISS/SOLID/...) | `kaizen:<principle>` |
| Authoring a brain rule | `kaizen:behaviour-config` |
| Publishing the plugin to GitHub | `kaizen:publishing` |
| Building a new plugin / SKILL.md | `kaizen:writing-skills` |
| Multi-phase work | `kaizen:writing-plans` (plans/) + `kaizen:execute-plan` |
| Plugin gotchas seen in production | `kaizen:plugin-pitfalls` |

## Critical Iron Laws (applies to ALL agent actions in a kaizen repo)

1. **No `git rm` without explicit user authorization** OR a matching `deletion-allow` brain rule (gate Check #5 blocks otherwise).
2. **No bypassing the gate** — never `git commit --no-verify` unless the user explicitly asks. Always read failure details + surface to the user.
3. **No hand-editing `backlog.md`** — it's generated from `backlog.json`. Always use `backlog.py`.
4. **No writing volatile data into CLAUDE.md** (commit SHAs, point-in-time LOC counts, file inventories) — gate Check #6 warns.
5. **Sizing rule** — measure blast radius via grep/cargo-tree/ast-grep before scoping; NEVER estimate by clock-time.
6. **Skills read in full** — when you load a skill body, read end-to-end before applying any table/example.

## Versioning / change log

`<plugin>/.claude-plugin/plugin.json` + `<plugin>/CHANGELOG.md`. Check the latter for the most recent fixes when something feels off; the gate's check list, hook tracing schema, and tool surface evolve.

This skill is the index, not the truth — when in doubt, read the actual `<plugin>/skills/workflow/SKILL.md` (the canonical git-workflow rulebook) or the specific tool's `--help` output.
