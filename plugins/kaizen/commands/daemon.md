---
name: daemon
description: Manage the kaizen auto-daemon — cron-driven worker that hash-compares source↔cache, validates remote sha, and runs hygiene cleanups (prune old cache versions, purge stale inbox, clean backups, validate rules, render backlog). Subcommands: run | install | uninstall | status | log.
argument-hint: [run|install|uninstall|status|log]
---

# kaizen daemon

!`uv run --script ${CLAUDE_PLUGIN_ROOT}/scripts/daemon/daemon.py ${ARGUMENTS:-status}`
