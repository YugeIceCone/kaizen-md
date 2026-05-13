# Kaizen plugin — cross-CLI portability + Claude Code primitive overlap analysis

- **Date:** 2026-05-13
- **Plugin version analyzed:** v1.33.0 + the consolidation work landed in master @ `aaf12ff` (this session)
- **Method:** parallel dispatch — `claude-code-guide` agent surveyed CC primitives + ecosystem; `general-purpose` agent inventoried kaizen surface + researched alternatives in other AI CLIs / dev tooling.
- **Status:** initial — not actioned. Recommendations sorted by priority, not yet scheduled. File this as a strategic input to future sprints.

## TL;DR

Kaizen is layered well on top of Claude Code's native primitives and reimplements almost nothing. The risks are integration drift (CC's APIs evolve) and parallel state (kaizen plans + backlog run alongside CC's plan-mode + `/tasks`).

The leverage point for cross-CLI work is that ~23 KLOC of the engine (`skills/workflow/scripts/`, indexers, `_blobs`, `llm_proxy`, the pre-commit gate, `backlog.py`, `observe.py`) is already pure bash + Python stdlib. The CC-specific layer is mostly packaging — `${CLAUDE_PLUGIN_ROOT}` substitution, hook event names, skill frontmatter, slash-command bodies. **The shortest path to a second target is Codex CLI** (~450 LOC of adapters); Cursor / Continue / Aider need substantially more shimming because they lack subagents, lifecycle hooks, or on-demand skill loading.

---

## 1. Subsystem inventory

| Subsystem | Entry points | LOC | Files |
|---|---|---|---|
| **Workflow & routines** | `skills/workflow/{SKILL.md, domain/routines.yaml, domain/git-discipline.yaml, application/_loader.py, scripts/workflow.sh, scripts/workflow_runner.py}` | ~3 KLOC | 11 routine schemas in `schemas/<name>/schema.yaml` (1207 LOC) |
| **Git discipline** | `pre-commit.sh` (645), `commit-msg.sh` (103), `backlog.py` (348), `install.sh` (297), `git-discipline.yaml` | ~1.4 KLOC | self-contained |
| **Semantic indexers** | `knowledge_index.py` (691), `onboard_index.py` (1392), `trace_index.py` (527), `scrape_index.py`, `claude_docs_index.py`, `search_flow.py`, `_indexer_cli.py`, `_embed.py`, `_search.py`, `_sqlite.py` | ~4 KLOC | shared substrate; each `<name>_index.py` is a thin variant |
| **MCP servers** | 10 FastMCP servers (`workflow_mcp.py`, `state_mcp.py`, `lint_mcp.py`, `knowledge_mcp.py` 165, `onboard_mcp.py`, `trace_mcp.py`, `scrape_mcp.py`, `claude_docs_mcp.py`, `browser_mcp.py`, `mcp_server.py` 181) | ~2.5 KLOC | each wraps a CLI-equivalent script |
| **Hooks** | 7 `.sh` files in `hooks/` + `hooks.json` manifest | 591 LOC | events: `SessionStart`, `UserPromptSubmit`, `PreToolUse:Bash`, `PostToolUse:Bash`, `Stop`, `PreCompact` |
| **Observability** | `observe.py` (746), `trace.py`, `llm_proxy.py` (345), `_blobs.py` (497) | ~2 KLOC | 6-layer log model + content-addressed store + stdlib HTTP proxy |
| **Skills (SKILL.md)** | 74 skill dirs after consolidation | ~13 KLOC markdown | CC progressive-disclosure routing format |
| **Slash commands** | 40 `commands/*.md` | 915 LOC | CC frontmatter |
| **Subagents** | 6 `agents/*.md` | 587 LOC | CC YAML frontmatter |
| **Brain integration** | references to `~/.claude/brain/` | n/a | content is plain markdown; path is CC-shaped |

---

## 2. Claude Code primitive overlap

| Primitive | Native role | Kaizen's layer | Overlap risk | Recommendation |
|---|---|---|---|---|
| **Skills** (SKILL.md auto-discovery, progressive disclosure, ~25 KB context budget) | Model-invoked workflow instructions, on-demand loading | 74 skills covering 8 coding disciplines, Onion-DDD, workflow routines, plus bundled `superpowers` skills | Low (no reimpl — uses native discovery). Risk: bundled superpowers may double-load if user installs upstream | **Stay layered.** Consider declaring `superpowers@claude-plugins-official` as a plugin dependency rather than bundling. |
| **Agents / subagents** | Specialized workers with own context + tool restrictions; worktree isolation | 6 subagents (reviewer, backlog-curator, debt-auditor, karpathy-reviewer, memory-analyst, skill-extractor) | Low. Risk: depends on stable semantic-dispatch behavior | **Stay layered.** Document the agent dependency graph for fresh deployments. |
| **Hooks** (9 events: SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop, SubagentStop, SessionEnd, PreCompact, Notification) | Side-effect injection via shell + JSON stdin/stdout | 7 hooks wired into user's `settings.json` at install (pre-commit gate, inbox capture/drain, backlog reminder, snapshot, surface backlog) | **Medium.** Install writes to `settings.json` directly — risk of overriding user hooks; OS-dependent bash (`readlink -f`, `find -printf`) | **Migrate to plugin hooks.json** to prevent accidental override and reduce maintenance. Add cross-platform CI tests. |
| **MCP servers** (FastMCP, `.mcp.json` wiring, `mcp__<server>__<tool>` namespace) | Tool surface for Claude | 10 servers (workflow, state, lint, backlog, browser, claude-docs, knowledge-search, onboard-search, scrape, trace-search) | Low–medium. Risk: namespace conflict if CC ships native browser MCP | **Stay layered.** Document server lifecycle + quotas. Consider graduating high-value servers (trace/onboard/knowledge) to standalone marketplace plugin. |
| **Slash commands** | User-invoked workflows, frontmatter args, dynamic context | 40 commands under `kaizen:` namespace | Low. Risk: cognitive load from large `/` menu; stateful commands need file locking | **Stay layered.** Document menu hierarchy. Add file-locking guards for stateful ops. |
| **Plan mode + ExitPlanMode** | Phased plan workflow, lightweight | Custom `plans/<name>.md` with phases + verify + resume protocol; `/kaizen:execute-plan`, `:create-plan`, `:create-tasks` | **Medium-high.** Custom plan format runs parallel to native `/plan`; could be obsoleted if CC ships native plan storage | **Eventually migrate to native.** Build `kaizen:plan-to-native` / `native-to-kaizen` bridge for format conversion. Keep separate for now to avoid confusion. |
| **TaskCreate / TaskUpdate** | Built-in lightweight task tracker | Kaizen runs its own backlog at `.kaizen/workflow/backlog.json` with richer metadata (probe, verify, started_at, committed_at) | **Medium.** Parallel state — users get tasks in `/tasks` AND backlog items in `/kaizen:backlog` | **Bridge.** Add `/kaizen:backlog-to-tasks` sync. Long-term: pick one source of truth. |
| **Settings** (settings.json, permissions, env, statusLine, marketplaces) | Native, per-scope (managed > local > project > user) | Kaizen wires `env.REMEMBER_BRAIN_PATH`, `permissions.allow:[Bash(*)]`, `enabledPlugins` at install | Low. Risk: schema drift; permissive Bash policy | **Stay layered.** Add `/kaizen:settings-check` to validate hook wiring + permissions policy. |
| **Plugins** (`.claude-plugin/plugin.json`, marketplace discovery, version bump) | Native plugin format | Kaizen itself is a plugin | Low. Risk: version pin in `enabledPlugins` requires explicit update | **Stay layered.** Wire `/kaizen:daemon` to periodically run `/plugin update kaizen`. |
| **CLAUDE.md + memory** (project / user CLAUDE.md, `.claude/rules/`, auto-memory, MEMORY.md, Remember brain) | Native instructions + path-scoped rules + machine-local memory | Reads CLAUDE.md (e.g. shodan workspace's 600-line file). Manages project memory at `~/.claude/projects/<slug>/memory/`. Uses Remember brain at `~/.claude/brain/` for cross-project rules | **Medium.** Brain-sourced rules live outside CC's native memory system | **Migrate brain-sourced rules to `.claude/rules/`** so they're discoverable via `/memory`. Reduces Remember plugin dep. |
| **Bash tool + permissions** | Per-tool matchers, scoped allow/ask/deny | All-or-nothing `Bash(*)` + reliance on gate hook for enforcement | **Medium.** Single point of failure if hook script breaks | **Add deny rules** for truly forbidden commands (`deny: [Bash(rm -rf /)]`). Log gate decisions to trace-search for auditability. |

---

## 3. Cross-CLI portability classification

| Subsystem | Class | Why |
|---|---|---|
| Git discipline (`pre-commit.sh`, `commit-msg.sh`, `backlog.py`, `install.sh`) | **Portable** | Pure bash + Python stdlib + git. Already invoked via `core.hooksPath` — orthogonal to which AI drove the change. |
| Semantic indexer cores (`*_index.py`) | **Portable** | Self-contained `python <x>_index.py index | search | stats | get` CLIs. SQLite + sentence-transformers. |
| Routine schemas (`schemas/<routine>/schema.yaml`) | **Portable** (data) | YAML phases/artifacts/verify commands. Currently only `workflow.sh` interprets. |
| Observability (`observe.py`, `trace.py`, `_blobs.py`) | **Portable** | Trace is plain JSONL; `_blobs` is content-addressed sha256. Layer 2 reader is CC-specific; engine is not. |
| `llm_proxy.py` | **Portable** | Stdlib HTTP proxy targeting Anthropic API; activated via `ANTHROPIC_BASE_URL` — works for any client (Codex, Aider, …) targeting the same endpoint. |
| Workflow runner (`workflow.sh`, `workflow_runner.py`, `_loader.py`) | **Adaptable** | State machine + yaml routines are tool-agnostic; the "what skill backs stage X" mapping is CC-shaped but easy to abstract via an oracle. |
| Hooks (`.sh` scripts) | **Adaptable** | Behaviors (destructive-command gate, inbox capture, snapshot) are universal; the JSON event-envelope schema is CC's specific contract. Codex CLI now has a similar `hooks.json` + inline `[hooks]` shape — a thin translator maps them. |
| MCP servers | **Adaptable** | MCP is the cross-tool standard (Cursor, Continue, Goose, Codex, Cody all speak it). Only the `${CLAUDE_PLUGIN_ROOT}` substitution + plugin bundling are CC-locked. |
| Subagents (`agents/*.md`) | **Adaptable for Codex; H for others** | YAML-frontmatter + Markdown. Codex `~/.codex/agents/*.toml` is the direct analog. Cursor / Continue / Aider have no native subagents. |
| Slash commands (`commands/*.md`) | **Adaptable** | CC frontmatter + `!`-prefixed bash. Codex `~/.codex/commands/` is nearly identical. Cursor / Continue use different shapes. |
| SKILL.md content | **CC-locked (routing); Adaptable (content)** | Bodies are plain markdown — any LLM can ingest. The `description:`-as-routing-prompt + on-demand-load semantics are CC-specific. Codex now has `~/.codex/skills/`; Cursor `.cursor/rules/*.mdc` (always-on or glob-scoped); Continue `.continue/rules/*.md` (mode-aware). None replicate progressive disclosure exactly. |
| `hooks.json` manifest schema | **CC-locked** | Event names, matcher syntax, `${CLAUDE_PLUGIN_ROOT}` substitution. |
| `${CLAUDE_PLUGIN_ROOT}` + marketplace mechanism | **CC-locked** | No cross-tool equivalent. |
| `Skill` tool semantics (load body mid-conversation) | **CC-locked** | CC's invention. Cursor rules are glob-based + always-on; Continue rules are mode-scoped; Codex skills are config-loaded. None match. |
| `AskUserQuestion` / `ExitPlanMode` / `TaskCreate` references in skills | **CC-locked** | Need rewrites per target. |
| Brain integration (`~/.claude/brain/`) | **Adaptable** | Already partially decoupled via `REMEMBER_BRAIN_PATH`. Promote to `KAIZEN_BRAIN_PATH` everywhere. |

---

## 4. Alternatives matrix (strongest 2-3 per subsystem)

### Git discipline (pre-commit gate + backlog + commit-msg)
- **kaizen:** 645-line bash gate, 8-12 checks, backed by `.kaizen.toml`.
- **pre-commit framework** ([pre-commit.com](https://pre-commit.com/)): python; standard for language-agnostic hooks; `.pre-commit-config.yaml`; hundreds of pre-built hooks but no belief-scan / backlog-drift / plan-tick equivalent.
- **Lefthook:** Go binary, parallel hook execution (~10× husky on large repos); YAML config; non-Node-team default.
- **Husky + commitlint + lint-staged:** Node-ecosystem default (~5M weekly downloads); commitlint validates Conventional Commits natively.
- **Adaptation effort: L** — `core.hooksPath` install is already universal.

### Semantic indexers (knowledge / onboard / trace / scrape / claude-docs)
- **kaizen:** SQLite + `all-MiniLM-L6-v2` (384-dim), `<repo>/.kaizen/<x>.db`, CLI `index | search | stats | get`.
- **Cursor `@codebase`:** closed-source built-in; not user-controllable.
- **Continue `@codebase` + `@docs`:** configurable in `config.yaml`; tighter IDE coupling.
- **Aider repo-map:** tree-sitter based (not embeddings) — coarser.
- **Sourcegraph / Zoekt:** server-side, heavy deploy — overkill.
- **Adaptation effort: L** — point any tool's custom-context provider at `python <x>_index.py search "..."`.

### MCP servers (10 of them)
- **kaizen:** FastMCP, stdio-transport.
- **Cursor:** `.cursor/mcp.json` (40-tool cap across all servers).
- **Continue:** `mcpServers` block in `config.yaml` (stdio + remote HTTP).
- **Goose:** MCP-native from day one (70+ documented extensions; full MCP registry).
- **Adaptation effort: L** — replace `${CLAUDE_PLUGIN_ROOT}` with absolute path or `$KAIZEN_PLUGIN_ROOT`; ~50-LOC `bin/kaizen-mcp-config --target {cursor|continue|goose|codex}` shim emits each host's JSON/YAML.

### Hooks (7 shell scripts + hooks.json)
- **kaizen:** event-JSON in, decision-JSON out, ~50-100 LOC each.
- **Codex CLI:** `hooks.json` + inline `[hooks]` blocks support `SessionStart`, `PreToolUse`, `PostToolUse`, `Stop` (per the May-2026 Codex changelog citing plugin-bundled hook visibility, `apply_patch` observation, long-running Bash session interception, `SessionGoalUpdate`).
- **Cursor:** no per-event hook system — only MCP-tool-invocation; gap.
- **Continue:** limited; agent-mode customization via rules.
- **Adaptation effort: M** — split each hook into `_behavior.py` + `_cc_envelope.sh`; ~20-LOC `_codex_envelope.sh` per hook.

### Workflow routines + schemas
- **kaizen:** 11 declarative schemas; `workflow.sh` advances state in `.kaizen/workflow/state.json`.
- **Codex CLI Goal Mode (April 2026)** + MultiAgentV2 with thread caps — closest analog. `SessionGoalUpdate` hook + `~/.codex/agents/`.
- **just / mise tasks / make:** task runners — sequential phases but no "current stage" + "advance with verification" loop; weak on agentic branching.
- **GitHub Actions / Tekton / Temporal:** server-side, overkill for a per-repo state machine.
- **Adaptation effort: M-H** — yaml + state.json port easily; the stage→skill oracle needs tool-specific shim.

### Observability (trace + observe + llm_proxy + _blobs)
- **kaizen:** JSONL trace + 6-layer observe + stdlib HTTP proxy + sha-keyed blob store.
- **Langfuse / Helicone / LangSmith:** SaaS / self-hosted LLM observability; heavier and require sending traces off-machine unless self-hosted.
- **Phoenix (Arize) / OpenLLMetry:** open-source OpenTelemetry-shaped — closest match for "JSONL → structured trace" upgrade.
- **Promptlayer:** SaaS prompt logging; lighter than Langfuse but cloud-only.
- **Adaptation effort: L** — `llm_proxy.py` already cross-tool via `ANTHROPIC_BASE_URL`. `observe.py` Layer 2 needs per-tool adapter (Codex transcripts at `~/.codex/log/`).

### Skills (74 SKILL.md)
- **Cursor:** `.cursor/rules/*.mdc` — `alwaysApply` / `globs` / `description`; glob-based routing + manual `@rule`.
- **Continue:** `.continue/rules/*.md` — mode-scoped (Chat / Agent / Edit); active by default.
- **Codex CLI:** `~/.codex/skills/` and `.codex/skills/` (added 2026); closest 1:1 match.
- **Adaptation effort: L for Codex** (mechanical TOML/YAML translation), **M for Cursor / Continue** (bucket into always-on vs glob-scoped vs manual; lose on-demand loading), **H for Aider** (no skill system — bake into system prompt).

### Slash commands (40)
- **Cursor:** `/rules`, `/mcp enable`, custom CLI slash commands (Cursor CLI Jan-2026).
- **Continue:** custom slash commands + prompt templates in `config.yaml`.
- **Codex:** `~/.codex/commands/` markdown — nearly identical shape.
- **Adaptation effort: L** — substitute `${CLAUDE_PLUGIN_ROOT}` and convert frontmatter.

### Subagents (6)
- **Codex CLI:** `~/.codex/agents/*.toml` (`nickname_candidates`, `model`, `model_reasoning_effort`, `sandbox_mode`, `mcp_servers`, `skills.config`, MultiAgentV2 thread caps).
- **Cursor / Continue:** no native subagent concept; closest is custom-prompt slash commands.
- **Adaptation effort: L for Codex**, **H for others**.

---

## 5. Recommended hybrid architecture

```
┌─ kaizen-core (portable)  ──────────────────────────────┐
│   scripts/  •  schemas/  •  domain/  •  application/   │
│   _blobs/   •  trace store  •  llm_proxy  •  indexers  │
│   pre-commit.sh, backlog.py, install.sh, observe.py    │
└────────────────────────────────────────────────────────┘
                            ▲
                            │ per-target adapter (thin)
            ┌───────────────┼───────────────┬──────────────┐
       Claude Code     Codex CLI       Cursor/Continue    Aider
       (current)       (next target)   (limited target)   (cli-only)
   plugin.json +       agent.toml +    .cursor/rules +    just shell
   hooks.json +        hooks.json +    mcp.json (no       wrappers
   .mcp.json +         commands/ +     hooks)             over CLIs
   skills/ +           skills/
   commands/           (Codex skills)
```

---

## 6. Recommendation table (consolidated, deduped, prioritized)

| # | Recommendation | Subsystem | Effort | Priority | Notes |
|---|---|---|---|---|---|
| R1 | Migrate hooks from `settings.json` injection to plugin `hooks.json` | Hooks | L | **High** | Prevents accidental user override; aligns with CC's plugin-hook path. Non-destructive merge via `hookify`. |
| R2 | Add `KAIZEN_PLUGIN_ROOT` env fallback for `${CLAUDE_PLUGIN_ROOT}` everywhere | MCP, hooks, commands | L | **High** | Single-token unlock for cross-CLI use. Per-target wrappers can set this without CC. |
| R3 | Build `bin/kaizen-export --target codex` (+ later: `cursor`, `continue`) | Skills, commands, agents, MCP | M | **High** | Codex is the highest-leverage second target; ~450 LOC of adapters total. |
| R4 | Move brain-sourced rules to `.claude/rules/` | Brain integration, CLAUDE.md | L–M | **Medium** | Discoverable via `/memory`; reduces Remember plugin dep. Keep brain as primary store; rules dir as cache. |
| R5 | Sync kaizen backlog with native `/tasks` (bidirectional bridge) | Backlog, TaskCreate | M | **Medium** | Eliminates parallel work-management state. Long-term pick one source of truth. |
| R6 | Bridge kaizen plans ↔ native `/plan` mode | Plans, Plan mode | M | **Medium** | Format converter both directions. Eventually retire one if convergence holds. |
| R7 | Document `<x>_index.py` plain CLI as the public API; add `--json` flags consistently | Indexers | L | **Medium** | Already mostly there. Removes need to invoke MCP for cross-tool integration. |
| R8 | Add `bin/kaizen-mcp-config --target <host>` emitter | MCP servers | L | **Medium** | Drop-in MCP wiring for Cursor / Continue / Goose / Codex. ~50 LOC. |
| R9 | Split each hook into `_behavior.py` + `_<host>_envelope.sh` | Hooks | M | **Medium** | Codex envelope is ~20 LOC each. Behavior stays shared. |
| R10 | Add deny rules for truly forbidden commands (`Bash(rm -rf /)` etc.) | Permissions | L | **Medium** | Defense-in-depth alongside gate hook. |
| R11 | Repackage git-discipline as standalone `kaizen-gate` (PyPI/cargo-binstall) | Git discipline | M | **Low** | Currently bundled in plugin; could ship independently for non-CC users. |
| R12 | Add Codex-transcript reader to `observe.py` (alongside CC) | Observability | L | **Low** | Layer 2 cross-tool support; bodies stay shared. |
| R13 | Declare `superpowers@claude-plugins-official` as plugin dependency (vs bundling) | Skills | L | **Low** | Reduces version-skew if upstream updates. |
| R14 | Add `/kaizen:settings-check` validator | Settings | L | **Low** | Detects drift in hook wiring + permissions policy. |
| R15 | Wire `/kaizen:daemon` to auto-run `/plugin update kaizen` | Plugins | L | **Low** | Users currently must invoke explicitly. |

### What NOT to port

- `Skill` tool semantics (mid-conversation body load), `AskUserQuestion`, `ExitPlanMode`, `TaskCreate` — drop or replace per target. <5% of skill bodies reference these.
- CC marketplace mechanism — irreplaceable; document manual install path for non-CC.
- The "progressive disclosure" tier — Cursor / Continue can't replicate. Accept the cost.

---

## 7. Risks watchlist (CC integration drift)

| Primitive | Risk | Mitigant |
|---|---|---|
| Skills discovery + lazy-loading | Low | CC's skill system is stable; kaizen uses native SKILL.md |
| Subagent dispatch | Medium | Semantic dispatch depends on description stability; document drift scenarios |
| Hook JSON schema + exit codes | **Medium** | OS-dependent bash + accidental override risk. Mitigate via R1 + cross-platform CI. |
| MCP tool namespace (`mcp__*`) | Medium | Scoped namespaces would require remapping. R2 + R8 reduce coupling. |
| Plan-mode integration | **High** | Custom plan format could be obsoleted. Mitigate via R6 bridge. |
| CLAUDE.md discovery order | Low | Precedence is well-defined. |

---

## 8. Ecosystem alternatives (Claude Code plugins)

| Plugin | Overlaps kaizen feature | Recommend |
|---|---|---|
| `superpowers@claude-plugins-official` | brainstorming, executing-plans, TDD, systematic-debugging, verification-before-completion, writing-plans, using-git-worktrees, subagent-driven-development | **Depend** (currently bundled — R13) |
| `skill-creator@claude-plugins-official` | writing-skills, skill evals, optimization | **Depend** (bundled as reference) |
| `coderabbit@claude-plugins-official` | code-review, autofix | **Coexist** (kaizen wires `coderabbit:coderabbit-review` agent) |
| `plugin-dev@claude-plugins-official` | creating agents, skills, hooks, MCPs | **Depend** (bundled) |
| `mcp-server-dev@claude-plugins-official` | MCP server creation | **Coexist** (complementary) |
| `frontend-design@claude-plugins-official` | UI/visual design | **Coexist** (orthogonal) |
| `commit-commands@claude-plugins-official` | git commit / push / PR | **Coexist** (kaizen gate + commit-commands complement each other) |
| `hookify@claude-plugins-official` | hook rule creation | **Coexist** (kaizen uses hookify for rule management) |
| `claude-code-docs` (ericbuess mirror) | docs search | **Depend** (kaizen indexes via `/kaizen:claude-docs`) |

---

## 9. Sources cited by agents

- [Subagents – Codex | OpenAI Developers](https://developers.openai.com/codex/subagents)
- [Codex Changelog](https://developers.openai.com/codex/changelog)
- [Codex Advanced Configuration](https://developers.openai.com/codex/config-advanced)
- [Migrating a Workflow from Claude Code to Codex CLI](https://codex.danielvaughan.com/2026/03/26/migrating-claude-code-to-codex-cli/)
- [Continue.dev Rules](https://docs.continue.dev/customize/rules)
- [Continue MCP setup](https://docs.continue.dev/customize/deep-dives/mcp)
- [Continue slash commands](https://docs.continue.dev/customize/slash-commands)
- [Aider scripting](https://aider.chat/docs/scripting.html)
- [Aider feature request: custom commands](https://github.com/Aider-AI/aider/issues/894)
- [Cursor docs (Agent, Rules, MCP, Skills, CLI)](https://cursor.com/en-US/docs)
- [Cursor MCP Servers Setup Guide 2026](https://www.truefoundry.com/blog/mcp-servers-in-cursor-setup-configuration-and-security-guide)
- [Goose: open-source agent that shaped MCP](https://www.arcade.dev/blog/goose-the-open-source-agent-that-shaped-mcp/)
- [Goose AAIF / Linux Foundation transition](https://block.xyz/inside/block-open-source-introduces-codename-goose)
- [Husky vs Lefthook vs pre-commit comparison 2026](https://www.pkgpulse.com/guides/husky-vs-lefthook-vs-lint-staged-git-hooks-nodejs-2026)
- [Git Hooks: The Complete Guide for 2026](https://devtoolbox.dedyn.io/blog/git-hooks-complete-guide)

---

## 10. Next steps (if this gets actioned)

1. **R1 + R2** combined as a single PR — flip hooks to plugin-level + introduce `KAIZEN_PLUGIN_ROOT`. Unblocks everything downstream.
2. **R3 prototype** — `bin/kaizen-export --target codex` for skills + commands + agents. Smoke-test against a fresh Codex install in isolation.
3. **R6 + R5** — plan + backlog bridges. Wait for native plan-mode + tasks API to stabilize first.
4. The rest are independent and can be picked up opportunistically by `/kaizen:audit` cycles.

This file is the input, not the work. File backlog items via `/kaizen:backlog add` as each recommendation gets ranked into a sprint.
