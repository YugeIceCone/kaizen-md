---
name: daemon
description: Manage the kaizen auto-daemon — cron-driven worker that hash-compares source↔cache, validates remote sha, and runs hygiene cleanups (prune old cache versions, purge stale inbox, clean backups, validate rules, render backlog). Subcommands: run | install | uninstall | status | log.
argument-hint: [run|install|uninstall|status|log]
---

# kaizen daemon

!`python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/daemon.py ${ARGUMENTS:-status}`
