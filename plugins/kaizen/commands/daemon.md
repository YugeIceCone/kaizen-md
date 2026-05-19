---
name: daemon
description: "Manage kaizen auto-daemon - cron-driven worker, hash-compares source↔cache, validates remote sha, runs hygiene + memory tasks."
argument-hint: [run|install|uninstall|status|log]
---

# kaizen daemon

!`uv run --script ${CLAUDE_PLUGIN_ROOT}/scripts/daemon/daemon.py ${ARGUMENTS:-status}`

## Daemon-driven jobs

The cron-driven worker ticks several memory-related jobs without
manual invocation:

| Job | What it does | On-demand bin |
|---|---|---|
| **Memory curation** | Scan `~/.claude/projects/<slug>/memory/MEMORY.md` for promotion candidates; surface durable patterns | `kaizen-self-improving review` / `kaizen-self-improving promote <slug>` |
| Auto-memory regen | Rebuild MEMORY.md index from sibling files | `kaizen-better-memory regen-index` |
| Hygiene cleanups | Prune cache, backups, inbox TTL, vacuum trace DB, prune logs | `kaizen-hygiene` |
| Gold-mining | Promote mid-work gold patterns toward brain | `kaizen-gold` (capture) + `kaizen-gold-mine` |

The slash forms for the daemon-driven jobs were retired in the
cat-2 consolidation — the daemon owns the loop, the bins remain for
on-demand invocation. `Skill(kaizen:self-improving)` is still loadable
by agents for the promotion-lifecycle prose.
