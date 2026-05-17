---
name: help
description: Show kaizen surface — 53 slash commands by 9 domain clusters with one-line descriptions. Triggers on "kaizen help", "what kaizen commands", "list kaizen", "what does /kaizen:X do", "kaizen surface", "show me kaizen". Static body — zero bash roundtrip; precise + concise per-command summary.
argument-hint: "(none) | <command-name>"
---

# /kaizen:help

Static taxonomy of all 53 `/kaizen:*` commands. **One screen, zero bash
execution.** For full per-command docs use `kaizen help <name>`.

## audit/quality (11)

| Command | Does |
|---|---|
| `audit` | comprehensive severity-classified audit (security/arch/debt/coverage/docs) |
| `gatekeeper` | aggregated green/yellow/red verdict across 9 sub-gates |
| `gate` | dry-run pre-commit gate against staged changes |
| `review` | per-change lightweight inline review |
| `coverage` | 1:1 script ↔ test-file presence per workflow script |
| `iron-laws` | list/check/show non-negotiable plugin invariants |
| `karpathy-check` | Karpathy 4-principle review on staged or last commit |
| `vibe-check` | periodic gut-feel sanity pass on the diff |
| `self-audit` | schema-driven plugin self-audit pipeline |
| `agent-self-audit` | fan out self-audit checkpoints across subagents |
| `ci-gate` | CI-friendly gate runner |

## observability (7)

| Command | Does |
|---|---|
| `trace` | kaizen event log: stats / tail / query / clear |
| `trace-search` | semantic search over indexed traces |
| `trace-proxy` | proxy MCP / network calls for trace capture |
| `metrics` | session rollup + never-used + skip-detection + graveyard |
| `observe` | snapshot kaizen state for diff/regression |
| `context` | context-window tokens / pct / zone (green/yellow/red) |
| `statusline` | install/preview statusline (context + backlog + gate) |

## brain/memory (2)

| Command | Does |
|---|---|
| `brain` | Second Brain CLI (audit/evolve/index/promote/migrate/status/seed) |
| `self-improving` | curate auto-memory; promote learnings to brain Notes |

## workflow (7)

| Command | Does |
|---|---|
| `backlog` | JSON-sourced micro-work tracker (add/start/tick/park) |
| `handoff` | create/resume session handoff documents |
| `loop` | self-correcting iteration (ralph-loop) |
| `flow` | execute a kaizen async flow primitive |
| `mode` | record session mode + discipline bundles + auto-handoff |
| `migrate` | data-migration parent dispatcher |
| `migrate-paths` | specific path-restructure migrator |

## plugin-meta (13)

| Command | Does |
|---|---|
| `setup` | install/uninstall per-repo gate + cache mgmt |
| `bootstrap` | pre-warm uv-managed Python venvs for the plugin |
| `update` | git-pull marketplace + refresh cache + reload |
| `refresh-cache` | force Claude Code cache to match plugin source |
| `daemon` | manage the cron-driven auto-daemon |
| `hygiene` | one-shot cleanup pass (cache/backups/inbox) |
| `backup` | snapshot .kaizen/ + state to tarball (list/restore/prune) |
| `publish` | publish plugin/marketplace to GitHub |
| `env` | print/install kaizen shell env (aliases + KAIZEN_*) |
| `health` | broken symlinks / missing scripts / schema drift |
| `status` | repo health snapshot (config/gate/backlog/...) |
| `surface` | MCP+hooks registry validator (orphans / unmounted) |
| `disable-dupes` | detect + disable duplicate skill/command registrations |

## discovery/search (8)

| Command | Does |
|---|---|
| `onboard` | semantic SQLite index over a codebase |
| `knowledge` | semantic search over indexed knowledge bases |
| `claude-docs` | semantic search over local Claude API/Code docs mirror |
| `code-tour` | scaffold a CodeTour walkthrough (file+line anchored) |
| `scrape` | scrape + synthesize web content into semantic index |
| `models` | Ollama model mgmt + embed/chat smoke tests |
| `browser` | manage Playwright-backed MCP browser server |
| `docs` | generate per-package docs (Rust/JS/Go/Python) |

## dev-aids (5)

| Command | Does |
|---|---|
| `rule` | inspect/validate/template brain-sourced kaizen rules |
| `schema` | inspect schema-driven CLI surfaces |
| `inbox` | manage in-session message inbox (list/peek/drain/clear) |
| `test` | run plugin test suite |
| `help` | this screen |

## Drill-down (single CLI roundtrip)

- `kaizen help <name>` — full per-command docstring
- `kaizen list --json` — machine-readable inventory
- `kaizen <bin> --help` — per-bin usage
- `/kaizen:status` / `/kaizen:menu` — health snapshot / interactive picker
