---
name: daemon
description: Manage the kaizen auto-daemon — cron-driven worker that hash-compares source↔cache, validates remote sha, and runs hygiene cleanups (prune old cache versions, purge stale inbox, clean backups, validate rules, render backlog). Subcommands: run | install | uninstall | status | log.
---

# kaizen daemon

Cron-driven background worker. Each tick:

1. Hash-compare plugin source vs Claude Code's cache → auto `refresh-cache` if drift
2. Read remote HEAD via `git ls-remote` (no fetch). Notify-only by default; opt-in auto-pull via `KAIZEN_DAEMON_AUTOPULL=1`
3. Run `hygiene fix` — safe cleanups: prune old cache versions, drop drained inbox >7d, prune backups >10, render drifted backlog.md

Default interval: every 30 minutes. State + log at `~/.claude/.kaizen-daemon/{state.json,log}`.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/daemon.py ${ARGUMENTS:-status}`

## Subcommands

### Cron mode (default — periodic ticks)

| arg | effect |
|---|---|
| (none) or `status` | cron status + state + log tail |
| `run` | single tick now (cron uses this) |
| `install [--interval N]` | add cron entry (default every 30 min) |
| `uninstall` | remove cron entry |
| `log [N]` | tail last N log lines (default 20) |

### Keep-alive watcher mode (instant via hash-poll)

A long-running process that hash-polls the plugin source every N seconds (default 5) and ticks on **content drift** (touch / mtime-only updates correctly ignored — hash is content-based). Stdlib-only; no `inotify` / `watchdog` dependency.

| arg | effect |
|---|---|
| `watch [--interval SEC]` | run foreground (testing / systemd ExecStart) |
| `watch-start [--interval SEC]` | spawn detached child via `start_new_session=True` (nohup-equivalent) |
| `watch-stop` | SIGTERM (waits 3 s) then SIGKILL fallback |
| `watch-status` | print "running (pid N)" / "not running"; exit 0/1 for scripts |

PID file: `~/.claude/.kaizen-daemon/watcher.pid`. Stale PIDs auto-detected via `kill -0` probe.

### When to use which

| Use case | Mode |
|---|---|
| Lightweight, set-and-forget, low resource | **cron** (every 30 min) |
| Active development on the plugin source, want instant cache refresh | **watch** (every 5 s) |
| Both — cron as fallback in case watcher dies | install both; both are idempotent |

## Safety

By default the daemon is **passive on origin**: it READS `git ls-remote` but doesn't pull. Set `KAIZEN_DAEMON_AUTOPULL=1` (in your shell rc) to enable automatic `git pull --ff-only` on detected upstream commits. Auto-pull is opt-in because landing untrusted upstream code without review is a real risk.

Cache refresh, hygiene, and pruning ARE auto — they only operate on kaizen-owned state (cache slots, backup tarballs, drained inbox). Source code is never touched.

## Typical lifecycle

```
/kaizen:daemon install --interval 30    # add cron entry
/kaizen:daemon status                    # see runs, last sha, actions
/kaizen:daemon log 50                    # last 50 log lines
/kaizen:daemon run                       # tick now (also via cron)
/kaizen:daemon uninstall                 # remove cron entry
```

## Hygiene actions (auto-applied each tick)

| Check | Action when drifted |
|---|---|
| `cache` | Prune old version dirs (keep newest 2) |
| `backups` | Prune old tarballs (keep newest 10 per repo) |
| `inbox` | Delete drained entries > 7 days |
| `rules` | Validate frontmatter (read-only — no auto-fix; surfaces in log) |
| `backlog` | Re-render `.md` from `.json` when drifted |

Retention tunables (env vars):
- `KAIZEN_KEEP_VERSIONS=2`
- `KAIZEN_KEEP_BACKUPS=10`
- `KAIZEN_INBOX_TTL_DAYS=7`

## When NOT to run

- One-off project / no recurring kaizen use → cron entry is noise. Use `/kaizen:hygiene check` on demand instead.
- Restricted shells / containers without cron → use systemd user timer manually. The daemon worker (`daemon.py run`) is the same; wire any scheduler.

## Relationship to Claude Code's built-in `autoUpdate`

CC has a per-marketplace `autoUpdate: true` flag in `~/.claude/settings.json` → `extraKnownMarketplaces.<name>.autoUpdate`. When set, CC refreshes the marketplace cache **at session start**. The kaizen daemon is COMPLEMENTARY, not redundant:

| Capability | CC `autoUpdate` | kaizen daemon |
|---|---|---|
| Session-start refresh | ✓ | — |
| Mid-session refresh (cron tick) | ✗ | ✓ |
| Cache version pruning | ✗ | ✓ |
| Backup retention | ✗ | ✓ |
| Drained-inbox cleanup | ✗ | ✓ |
| Brain-rules validation | ✗ | ✓ |
| Backlog drift re-render | ✗ | ✓ |
| `git pull` from origin | ✓ for `source: "git"` marketplaces | opt-in (`KAIZEN_DAEMON_AUTOPULL=1`) |

Running both is safe — both rsync source→cache and are idempotent. The daemon catches the gap CC leaves: long-running sessions don't pick up pushed changes until next session restart, and CC has no retention/hygiene policy.

See `kaizen:plugin-pitfalls` #15 for the full failure-mode write-up.

## Related

- `/kaizen:hygiene` — same checks, on-demand only (no cron)
- `/kaizen:update` — manual maintenance (pull + refresh + reload)
- `/kaizen:refresh-cache` — single refresh-cache invocation
