---
name: help
description: Show kaizen surface taxonomy. 53 slash commands sorted by 9 domain clusters with pointers. Triggers on "kaizen help", "what kaizen commands", "list kaizen", "what does /kaizen:X do", "kaizen surface", "show me kaizen". One-screen body — zero bash roundtrip, agent reads the table once.
argument-hint: "(none) | <command-name>"
---

# /kaizen:help

Static taxonomy of the kaizen surface. **One screen, zero bash
execution** — the body IS the response. For deeper drill-down, the
agent invokes the named CLI directly (single roundtrip).

## Slash commands by cluster (53)

```
audit/quality  (11)  audit gatekeeper gate review coverage iron-laws
                     karpathy-check vibe-check self-audit
                     agent-self-audit ci-gate
observability   (7)  trace trace-search trace-proxy metrics observe
                     context statusline
brain/memory    (2)  brain  self-improving
workflow        (7)  backlog handoff loop flow mode migrate migrate-paths
plugin-meta    (13)  setup bootstrap update refresh-cache daemon hygiene
                     backup publish env health status surface disable-dupes
discovery       (8)  onboard knowledge claude-docs code-tour scrape
                     models browser docs
dev-aids        (5)  rule schema inbox test help
```

## Bins by cluster (66) — see CLAUDE.md "Domain organization"

## Drill-down (when needed — single roundtrip, runs CLI directly)

- `kaizen commands` — full slash-command listing with descriptions
- `kaizen help <name>` — full per-command docstring
- `kaizen list --json` — machine-readable inventory
- `kaizen <bin-name> --help` — per-bin usage
- `/kaizen:status` — repo health snapshot
- `/kaizen:menu` — interactive picker

## Pattern note

Help-by-static-body is the right shape when:
- The data is small + slow-changing (cluster taxonomy)
- The agent only needs to ORIENT (not enumerate every row)
- Token budget matters (this body is ~30 lines; `kaizen commands`
  output is ~100+ lines per invocation)

Per the "carry metadata; let the consumer pick" pattern:
the body lists the surface; the user names what they want; the
agent fetches just that one detail via CLI — zero waste.
