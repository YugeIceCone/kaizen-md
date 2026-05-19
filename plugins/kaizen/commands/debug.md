---
name: debug
description: "Universal error-locator + bin-smoke + parse-validity surface. Verbs - scan | parse | replay | lint | tail | smoke | check. Triggers - \"find errors\", \"smoke every bin\", \"static-scan for bugs\", \"replay this command\", \"tail stderr\", \"check yaml/python/jsonl/schema\"."
argument-hint: "[scan [--since 10m] [--source X] | parse [--stdin|--file] | replay <cmd> | lint [<path>...] | tail | smoke [--json] | check [--python|--yaml|--jsonl|--schema] [--path P] [--json]]"
allowed-tools: ["Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-debug:*)"]
---

# /kaizen:debug

!`bash -c 'exec ${CLAUDE_PLUGIN_ROOT}/bin/kaizen-debug ${ARGUMENTS:-smoke}'`

## Verbs

| Verb | Use |
|---|---|
| `scan [--since 10m] [--source {hooks\|tests\|bash\|python\|trace\|all}] [--json]` | Walk recent error sources, parse for `<file>:<line>: <error>`, surface structured records with hints |
| `parse [--stdin -] [--file <path>] [--json]` | Pipe-friendly stderr parser. `failing 2>&1 \| /kaizen:debug parse --stdin -` |
| `replay <command> [args...] [--timeout N] [--json]` | Run a command, capture stderr, parse for errors |
| `lint [<path> ...] [--json]` | Static-scan for common bug patterns (heredoc unbound vars, missing bridges) |
| `tail` | Live-monitor stderr logs; emit structured hints as errors fire |
| `smoke [--json]` | Exercise every kaizen-* bin with `--help`; surface failures with rc + stderr. Default verb. |
| `check [--python\|--yaml\|--jsonl\|--schema] [--path P] [--json]` | Parse-validity per axis. No flags = all 4. Catches bugs like the un-escaped `'` that silently broke the 2026-05-19 handoff. |

Default verb (no args) is `smoke` — the safest "is everything working" check.

## Bypass

Disable the trace emission on hook fires:
```
export KAIZEN_DEBUG_DISABLE=1
```

The CLI itself stays functional; only the trace events are silenced.
