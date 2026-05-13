# Attributions

The `kaizen` plugin is a composition. The pre-commit gate, backlog CLI, hook scripts, and slash commands in `scripts/`, `hooks/`, `commands/`, and `skills/kaizen/` are original to this plugin (MIT, © 2026 YugeIceCone).

Everything else is **bundled from upstream projects**, redistributed here under their original licenses with full attribution. Credit and gratitude to the original authors.

## Bundled skills + scripts

### `skills/{detect-stack, kiss, yagni, solid, dry, separation-of-concerns, law-of-demeter, boy-scout-rule, convention-over-configuration}` — 9 skills

- **Author:** Jordan Coin Jackson — https://github.com/JordanCoin
- **Source:** [github.com/JordanCoin/codingskills](https://github.com/JordanCoin/codingskills) — the `coding-skills` plugin
- **License:** MIT (© 2026 Jordan Coin Jackson)
- **Notes:** Foundational coding-principle skills, language-agnostic. Bundled to satisfy the gate's skill-weaving table (`coding-skills:dry`, `coding-skills:yagni`, etc.) without requiring users to install the upstream plugin separately.

### `skills/{using-superpowers, brainstorming, writing-plans, executing-plans, subagent-driven-development, dispatching-parallel-agents, test-driven-development, systematic-debugging, verification-before-completion, requesting-code-review, receiving-code-review, finishing-a-development-branch, using-git-worktrees, writing-skills}` — 14 skills

- **Author:** Jesse Vincent — jesse@fsck.com — https://github.com/obra
- **Source:** [github.com/obra/superpowers](https://github.com/obra/superpowers) — the `superpowers` plugin
- **Version bundled:** 5.1.0
- **License:** MIT (© 2025 Jesse Vincent)
- **Notes:** Process / discipline skills (TDD, debugging, planning, code review, git worktrees, skill authoring). Bundled to make `superpowers:*` references in the gate's skill-weaving resolvable without separate install.

### `skills/{remember, process, evolve, status, init}` + `scripts/*.js` + `references/*` + `assets/templates/*` + `config.defaults.json` + `REMEMBER.md.template`

- **Author:** Gabi Fratica — gabriel@codez.ro
- **Source:** [github.com/remember-md/remember](https://github.com/remember-md/remember) — the `remember` plugin (Second Brain for Claude Code)
- **License:** MIT (© 2026 Gabi Fratica)
- **Notes:** Extended Second Brain — knowledge capture, session processing, belief evolution, brain stats, initialization. The plugin's `scripts/*.js` (build-index, extract, schema, promote, append-evidence, evolution-log, session_start, user_prompt, config, build-context), `references/{structure.md, workflows.md}`, `assets/templates/{daily, note, person, project, remember, resource}.md`, and `config.defaults.json` are bundled alongside so the skills' `${CLAUDE_PLUGIN_ROOT}/scripts/...` references resolve without the upstream plugin installed.

### `skills/workflow/` (incl. `scripts/workflow.sh`, `domain/`, `application/`)

- **Source:** The user's local `~/.claude/skills/workflow/` (the `/workflow` engine). No upstream attribution was discoverable in the source files (no LICENSE / no author header).
- **License:** Assumed MIT under the user's authorship until the original is identified.
- **Notes:** Multi-stage routine engine + 12-check pre-commit gate + backlog CLI + semantic indexers. Drives `.kaizen/workflow/state.json` + `.kaizen/workflow/snapshot.md`. Absorbed the prior `workflow-routing` skill in the 2026-05-12 consolidation pass (routing data lives in `domain/routines.yaml::stage_skill_map`). If you are the original author and want different attribution, please open an issue against this plugin.

### `skills/onion-ddd-workflow/` + `skills/tdd/`

- **Source:** The user's local `~/.claude/skills/`. No upstream attribution in the source files.
- **License:** Assumed MIT under the user's authorship.
- **Notes:** Onion/DDD theory+audit+plan/execute discipline, and operational TDD runbook. Same caveat — if derived from elsewhere, the author can update this attribution.

## Why bundle?

The kaizen plugin's design goal is **session and project agnostic** operation. The gate's skill-weaving table routes to ~30 skills when their domain is touched; users would otherwise need to install 3 separate plugins (coding-skills, superpowers, remember) for the routing to resolve.

Bundling makes installation a single `/plugin install` command. The trade-off is potential namespace duplication (skills appear under both `coding-skills:dry` AND `kaizen:dry` if both plugins are installed) — see `/kaizen:disable-dupes` for the canonical resolution.

## Reporting attribution issues

If you are an original author and would like:

- Different wording in the credit line
- A different license assertion
- Additional information (e.g. funding sources, contributor lists)
- Or for your content to NOT be bundled here

…please open an issue at [github.com/YugeIceCone/kaizen-md](https://github.com/YugeIceCone/kaizen-md/issues) and we will respond promptly.
