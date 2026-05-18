# Audit — daemon + watcher + heartbeat systems

> **Purpose:** end-to-end trace of the runtime systems shipped over the last
> 2 sessions (cron `tick()`, persistent `watch-start`, new SessionStart/PostToolUse
> `systems-check`). Map cadences, find coverage gaps, propose improvements.

**Date:** 2026-05-18 (sid 9f4c8972, post-restart)
**Triggered by:** user — "trace kaizen daemon watcher heartbeat systems" +
"audit heartbeat system surface".

---

## The 4 cadences

| Cadence | Trigger | What runs | Sink |
|---|---|---|---|
| **Cron periodic** (default 30 min) | crontab `*/30 * * * *` | `tick()`: src/cache hash, refresh-cache, remote sha, hygiene, index refresh | `~/.claude/.kaizen/data/daemon/state.json` + `daemon/log` |
| **Cron @reboot** | crontab `@reboot watch-start` | `watch-start`: spawn watchdog daemon, hash-poll loop (5s default) | `daemon/watcher.pid` |
| **SessionStart hook** (1 fire) | CC `SessionStart` event | `systems-check`: probe 4 systems | `keepalive/heartbeat.jsonl` |
| **PostToolUse hook** (every 25 calls) | CC `PostToolUse` w/ counter | Same `systems-check` | Same `heartbeat.jsonl` |

The 3 are **independent + non-overlapping** by design:

- `tick()` = maintenance + sync (heavy: git, hygiene, indexing).
- `watch-start` = file-change detection → re-index trigger.
- `systems-check` = liveness audit ("are the sinks alive?").

---

## Coverage today

`_TRACKED_SYSTEMS` (daemon.py:731) probes **4** systems:

| name | kind | sink probed | extant |
|---|---|---|---|
| `hooks` | config | `hooks/hooks.json` (existence + mtime) | ✓ |
| `trace` | sink | `indexes/trace/events.jsonl` | ✓ (109K events live) |
| `dxm` | sink | `dxm/events-<sid>.jsonl` (newest) | ✓ |
| `observer` | sink | `observer/events.jsonl` | ⏳ pending session restart load |

---

## Coverage gaps (5+ systems unmonitored)

| Sink / process | Why monitor | Status |
|---|---|---|
| `daemon/watcher.pid` | The persistent watch daemon; if dead, file-change re-indexing is silently broken | NOT probed |
| `learning/events.jsonl` | kaizen-learn structured P/S log | NOT probed |
| `gold/events.jsonl` | kaizen-gold incidental-discovery sink | NOT probed |
| `keepalive/counter.txt` | The keep-alive counter itself; meta-check | NOT probed |
| `data/handoff.db` | Handoff SQLite store | NOT probed |
| `brain/brain.db` | Second Brain SQLite | NOT probed |
| `indexes/knowledge/index.db` | Semantic knowledge index | NOT probed |
| `indexes/scrape/index.db` | Web scrape semantic index | NOT probed |
| `indexes/claude-docs/index.db` | Claude docs semantic index | NOT probed |
| `.kaizen/onboard.db` | Per-repo codebase semantic index | NOT probed |

---

## Behavior gaps

1. **No staleness check.** A sink that stops growing (e.g. observer hook
   stops firing) keeps reporting the same `count` indefinitely. There's no
   threshold like "if `last_mtime` > N hours ago → flag stale".
2. **No rotation.** `heartbeat.jsonl` grows unbounded. Every PostToolUse-25
   adds a row (~1KB). 10K tool calls → 10MB. Hits token-bloat ceiling.
3. **No subscriber.** Nothing reads `heartbeat.jsonl` — not statusline,
   not observer, not dxm. The data is collected but never surfaced.
4. **No `--watch` mode.** All cadences are external (cron / hook).
   `systems-check --watch INTERVAL` would let humans/scripts poll without
   re-launching the process.
5. **Code dedup with `daemon.py status`.** The existing `status` subcommand
   reads `state.json` + tails `log`. `systems-check` does a similar
   probe-then-print but doesn't reuse it.
6. **No alert thresholds.** No way to say "warn me when `observer.count` is
   the same for N consecutive heartbeats".

---

## Architectural observations

- The 3 sinks (`daemon/`, `keepalive/`, `dxm/`) use 3 different sink shapes
  (JSON state file / append-only jsonl / per-session jsonl). Unification
  would be a refactor, not a hot-path concern — note for later.
- `_TRACKED_SYSTEMS` is a module-level tuple. Adding a system =
  appending an entry. Each `_check_one` branch needs a kind-specific
  probe (config / sink / pid). The probe code is duplicated for each
  jsonl-sink — could factor into a `_probe_jsonl_sink(path)` helper
  if/when adding `learning` + `gold` + `observer-meta`.
- The `_check_one` function has a `name == "hooks"` early-return special
  case + a `name == "dxm"` glob branch — both legible for now but if
  we add 3+ more special cases, refactor to dispatch table.

---

## Recommendations (priority order)

### Ship now (1 commit, TDD)

1. **Expand `_TRACKED_SYSTEMS` to 9** — add: `daemon-watcher` (pid file probe),
   `learning` (jsonl), `gold` (jsonl), `keepalive-meta` (counter.txt), and
   one of: `handoff-db` (sqlite size). Skips the index DBs (each has its
   own freshness story).
2. **Add staleness flag** — when `last_mtime` is older than
   `KAIZEN_KEEPALIVE_STALE_SEC` (default 7200 = 2 hours), set
   `stale: true` in the system dict. Non-fatal — informational.

### Ship next (1 commit)

3. **Heartbeat rotation** — when `heartbeat.jsonl` > 1MB, rotate to
   `heartbeat.jsonl.1` (single-roll). Bounded growth.

### Ship later (1 commit)

4. **`systems-check --watch INTERVAL`** — continuous poll mode. Mirrors
   the existing `daemon watch` shape.

### Defer (future arcs)

5. **Statusline integration** — surface latest probe summary in statusline
   (separate skill).
6. **Dedup with `daemon status`** — share probe code (refactor commit).
7. **Sink alert thresholds** — change-detection per-sink across heartbeats.

---

## File map

| Path | Role |
|---|---|
| `plugins/kaizen/skills/workflow/scripts/daemon.py` | tick + watch + systems-check |
| `plugins/kaizen/hooks/claude/session-start-systems-check.sh` | SessionStart hook |
| `plugins/kaizen/hooks/claude/posttool-keepalive.sh` | PostToolUse periodic hook |
| `plugins/kaizen/tests/test_daemon_systems_check.py` | systems-check tests (5 classes) |
| `~/.claude/.kaizen/keepalive/heartbeat.jsonl` | append-only heartbeat sink |
| `~/.claude/.kaizen/keepalive/counter.txt` | tool-call counter for periodic fires |
| `~/.claude/.kaizen/data/daemon/state.json` | cron tick state |
| `~/.claude/.kaizen/data/daemon/watcher.pid` | watch-start daemon pid |
