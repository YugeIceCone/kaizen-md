---
name: daemon
description: "Manage kaizen auto-daemon - cron-driven worker, hash-compares source↔cache, validates remote sha, runs hygiene + memory tasks."
argument-hint: [run|install|uninstall|status|log]
---

# kaizen daemon

!`uv run --script ${CLAUDE_PLUGIN_ROOT}/scripts/daemon/daemon.py ${ARGUMENTS:-status}`
