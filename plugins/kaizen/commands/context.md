---
name: context
description: Report Claude Code's current context-window state — tokens used, percentage of limit, zone (green/yellow/red), and a recommendation. Uses CLAUDE_CONTEXT_TOKENS env or stdin JSON (statusline schema). Use to decide when to /compact, before a large refactor, or when the gate Check #12 fired a warning.
---

# kaizen context

Resolve the current context window state and recommend action.

!`python3 ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/context.py ${ARGUMENTS:-show}`

## Subcommands

| arg | output |
|---|---|
| (none) or `show` | one-line summary: `context: N/M tokens (P%, zone)` |
| `json` | full record: `{tokens, limit, pct, zone}` |
| `zone` | one of: `green` / `yellow` / `red` / `unknown` |
| `pct` | integer percentage (blank if unknown) |
| `should-warn` | exits 0 if yellow/red, 1 if green/unknown — use in shell guards |

## Zones

| zone | range | meaning |
|---|---|---|
| 🟢 green | 0–59% | safe; carry on |
| 🟡 yellow | 60–79% | start thinking about /compact at a natural break |
| 🔴 red | 80–100% | actively warn; risk of state loss at compact |
| ⚪ unknown | — | no token signal available |

## Where the token count comes from

In priority order:

1. `CLAUDE_CONTEXT_TOKENS` env (if exported by the harness)
2. `CLAUDE_USAGE_TOTAL_TOKENS` env (alternate name)
3. stdin JSON — `total_tokens` or `usage.total_tokens` field
4. (fallback) None — report `unknown`

## Limit override

`KAIZEN_CONTEXT_LIMIT` env, default 200_000. Set this if you're on a tier with a different cap.

## Gate integration

`pre-commit.sh` Check #12 reads this via `context.py zone` after all other checks. Yellow → silent unless `KAIZEN_VERBOSE=1`; red → warns "consider /compact after this commit". Advisory only — never blocks the gate.
