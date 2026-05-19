---
name: kaizen-md
description: Single orientation entry-point for the kaizen-md plugin. When an agent or user is unsure WHERE in kaizen to start, load this skill — it routes by intent to the right specialized skill (brain / workflow / quality / plugin-dev / automation / discovery). Subsumes the discovery role of `/kaizen:help`; references `intent` (automation) and `plugin-development` (dev workflows) as specialized siblings. Triggers on "where do I start with kaizen", "what should I use", "which kaizen skill", "kaizen umbrella", "kaizen orientation", "kaizen entry", "kaizen-md help", "I want to do X with kaizen".
---

# kaizen-md — Orientation Hub for the Plugin

## ⚠ Iron Law — read in full

Skip nothing. The cluster taxonomy + dispatch rubric only hold
together when read end-to-end. Skimming to a flowchart produces
wrong-cluster dispatches and rediscovery loops.

## What this skill does

Single entry-point for finding the right kaizen specialty when the
agent/user doesn't already know which skill to load. Routes by intent
to one of six clusters; each cluster has its own canonical skill +
slash command + bin wrapper surface.

| Cluster | When to dispatch | Canonical skill |
|---|---|---|
| **brain / memory** | "remember this" / "capture", "search the brain", "promote a belief", "audit memory" | `Skill(brain)` + `/kaizen:brain` |
| **workflow / TDD** | "implement feature", "fix bug", "refactor", "run workflow", "build with TDD" | `Skill(workflow)` + `/kaizen:workflow` |
| **quality / coverage** | "audit code", "check coverage", "find dead code", "lint markdown" | `/kaizen:audit` + the per-axis bins (`kaizen-coverage`, `kaizen-complexity`, etc.) |
| **plugin-dev (kaizen-md itself)** | "add a kaizen feature", "build new MCP server", "validate staged diff" | `Skill(plugin-development)` + `/kaizen:plugin-development` |
| **automation / hooks** | "automate when X", "set up trigger", "phrase pattern", "event automation" | `Skill(intent)` + `kaizen-intent` |
| **discovery / inventory** | "what kaizen commands exist", "list skills", "show me kaizen surface" | `kaizen` CLI (categorized listing) + `/kaizen:help` |

## Dispatch contract

When this skill is loaded, surface the cluster table above. If the
user's intent matches one cluster cleanly, recommend loading the
canonical skill or invoking the slash command — don't try to handle
the work directly from kaizen-md.

When intent spans multiple clusters (e.g. "audit my code AND record
the findings to brain"), name both — the agent can chain the
specialized skills.

## What this skill does NOT do

- **Does not automate** — that's `intent`'s job (declarative
  phrase + event_pattern triggers, hook-driven).
- **Does not validate features** — that's `plugin-development`'s
  job (intake checklist + validate.py + iron-laws).
- **Does not generate the surface inventory** — that's `kaizen-help-gen`
  (auto-generates `/kaizen:help` from `commands/*.md`).
- **Does not capture/store memory** — that's `brain`'s job.

kaizen-md is the front-door router. The specialized skills do the
actual work.

## Cluster taxonomy (deeper view)

### brain / memory cluster
- `Skill(brain)` — capture / search / promote / audit / evolve / blocks-show-edit
- `/kaizen:brain <verb>` — consolidated CLI parent
- `bin/kaizen-brain` — bin wrapper
- Backing: `scripts/brain/brain.py` + `build_index.py` +
  `brain_audit.py` + `brain_promote.py` + `brain_evolve.py` + `brain_mcp.py`
- Related: `Skill(remember)`, `Skill(process)`, `Skill(evolve)`,
  `Skill(status)` — back-compat wrappers; route through `brain/`

### workflow / TDD cluster
- `Skill(workflow)` — commit cadence + pre-commit gate + multi-stage
  routines (audit / build-feature / fix-bug / refactor / migrate /
  harden / debug / mcp-build / spec-driven / onion-tdd-strict)
- `/workflow <args>` — runs a curated structured workflow
- `Skill(tdd)` — RED → GREEN → REFACTOR discipline
- `Skill(executing-plans)` / `Skill(writing-plans)` — plan-driven work

### quality / coverage cluster
- `/kaizen:audit` — periodic comprehensive audit
- Per-axis bins: `kaizen-coverage`, `kaizen-complexity`,
  `kaizen-dead-code`, `kaizen-heavy-imports`, `kaizen-md-dupes`,
  `kaizen-md-whitespace`, `kaizen-md-link-rot`, `kaizen-md-heading-depth`,
  `kaizen-name-quality`, `kaizen-class-name-quality`,
  `kaizen-var-name-quality`, `kaizen-tname-quality`,
  `kaizen-test-density`, `kaizen-test-isolation`, `kaizen-test-name-quality`,
  `kaizen-bin-coverage`, `kaizen-command-allowed-tools-coverage`,
  `kaizen-hook-coverage`, `kaizen-hook-trace-coverage`,
  `kaizen-mcp-coverage`, `kaizen-mcp-trace-coverage`,
  `kaizen-perm-coverage`, `kaizen-schema-load-coverage`,
  `kaizen-sandbox-check`, `kaizen-silent-fail`,
  `kaizen-subprocess-rc`, `kaizen-unused-env`, `kaizen-todo-inventory`,
  `kaizen-density`, `kaizen-turn-density`, `kaizen-prompt-event-diff`,
  `kaizen-prompt-rhythm`
- Aggregator: `kaizen-gatekeeper check --all` (one verdict over the axes)

### plugin-dev cluster
- `Skill(plugin-development)` — feature shape + intake checklist
- `/kaizen:plugin-development <verb>` — intake / workflow / validate /
  rules / dispatch / audit / surface / cluster
- `Skill(iron-laws)` — commit-blocking rules
- `Skill(writing-plans)` / `Skill(test-driven-development)` —
  preconditions for any plugin-original change

### automation / hooks cluster
- `Skill(intent)` — declarative intent → action automation
- `Skill(claude-hooks)` — lifecycle hook authoring
- `hooks/hooks.json` — registered hooks
- `_intent_userprompt.py`, `_observer_capture.py`, etc. — hook handlers

### discovery / inventory cluster
- `kaizen` CLI — categorized listing (126 subcommands)
- `kaizen commands` — slash-command listing (57)
- `kaizen list --json` — machine-readable inventory
- `/kaizen:help` — interactive cluster wizard
- `/kaizen:status` — current install state

## Pairing with siblings

| Sibling | Relationship |
|---|---|
| `intent` | kaizen-md routes USER intent; `intent` handles AGENT/EVENT intent (hook-driven automation). |
| `help` | kaizen-md is human-facing orientation; `help` is auto-generated surface tables. Both can be invoked; `help` for "what exists", kaizen-md for "what to use". |
| `plugin-development` | kaizen-md routes general users; `plugin-development` is the specialized hub for plugin DEVELOPERS. kaizen-md dispatches there for plugin-dev work. |

## Triggers (when to load this skill)

- The user opens with an ambiguous high-level kaizen ask
- An agent is unsure which kaizen skill applies
- "Where do I start?" / "What's the kaizen way to do X?" / "Which
  kaizen tool for Y?"
- The current task spans multiple kaizen clusters and needs coordination

## DON'T load this skill when

- You already know the specific skill needed (load it directly)
- The work is in a non-kaizen domain (UI, infra, etc.)
- You're in mid-execution of a specialized skill — finish that first
