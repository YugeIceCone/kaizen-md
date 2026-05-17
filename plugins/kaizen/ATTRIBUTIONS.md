# Attributions

The `kaizen` plugin is © 2026 YugeIceCone, MIT-licensed.

Several skills in `plugins/kaizen/skills/` were **originally based on or inspired by** prior work by other authors. As of **2026-05-17** those skills are no longer tracked as live upstream bundles — extensive kaizen-local alterations (schema-driven domain refactors, the `verify-before-execution` discipline, the onion-ddd-workflow integration, per-skill enhancements, etc.) made the upstream-patch-first round-trip impractical. The skills are now plugin-original derivatives that the kaizen maintainers own and evolve here.

Original-author credit is preserved below. Gratitude to each of them — the foundational work is theirs.

## Originally based on `coding-skills` by Jordan Coin Jackson

Skills that began as adaptations of the `coding-skills` plugin:

- `detect-stack`
- `kiss`
- `yagni`
- `solid`
- `dry`
- `separation-of-concerns`
- `law-of-demeter`
- `boy-scout-rule`
- `convention-over-configuration`

- **Original author:** Jordan Coin Jackson — https://github.com/JordanCoin
- **Original source:** [github.com/JordanCoin/codingskills](https://github.com/JordanCoin/codingskills)
- **Original license:** MIT (© 2026 Jordan Coin Jackson)
- **Notes:** Foundational coding-principle skills, language-agnostic. The `boy-scout-rule` body has been substantially rewritten (Rules 5-7 added for apply-during-discovery + verify-before-execution gate delegation). The other 8 retain their original principle wording with kaizen-specific routing additions.

## Originally based on `superpowers` by Jesse Vincent

Skills that began as adaptations of the `superpowers` plugin (v5.1.0):

- `using-superpowers`
- `brainstorming`
- `writing-plans`
- `executing-plans`
- `subagent-driven-development`
- `dispatching-parallel-agents`
- `test-driven-development`
- `systematic-debugging`
- `verification-before-completion`
- `requesting-code-review`
- `receiving-code-review`
- `finishing-a-development-branch`
- `using-git-worktrees`
- `writing-skills`

- **Original author:** Jesse Vincent — jesse@fsck.com — https://github.com/obra
- **Original source:** [github.com/obra/superpowers](https://github.com/obra/superpowers)
- **Original license:** MIT (© 2025 Jesse Vincent)
- **Notes:** Process / discipline skills (TDD, debugging, planning, code review, git worktrees, skill authoring). `tdd/` has a kaizen-extended operational runbook (tiering, EDD, phase pipeline) and cross-references `verify-before-execution`. Others carry kaizen-routing wiring atop the upstream discipline.

## Originally based on `claude-code-skills` by alirezarezvani

Three skills absorbed in kaizen v1.32.0 and refactored to schema-driven shape in v1.33.0:

- `code-tour`
- `karpathy`
- `self-improving`

- **Original author:** alirezarezvani — https://github.com/alirezarezvani
- **Original source:** [github.com/alirezarezvani/claude-code-skills](https://github.com/alirezarezvani/claude-code-skills)
- **License:** per upstream repo
- **Notes:** `karpathy` is the largest divergence — kaizen added the `principles.yaml` declarative form + `principle.schema.json` + 4 stdlib-only diff-level Python scanners + the `kaizen-karpathy-reviewer` sub-agent. `self-improving` was rewired to consume kaizen's existing brain + project memory without duplicating `kaizen:remember` / `kaizen:status` ownership.

## Originally based on `remember` by Gabi Fratica

Five skills + supporting Node scripts originally from the `remember` Second Brain plugin:

- `remember`
- `process`
- `evolve`
- `status`
- `init`

Plus: `scripts/*.js` (build-index, extract, schema, promote, append-evidence, evolution-log, session_start, user_prompt, config, build-context), `references/{structure.md, workflows.md}`, `assets/templates/{daily, note, person, project, remember, resource}.md`, and `config.defaults.json`.

- **Original author:** Gabi Fratica — gabriel@codez.ro
- **Original source:** [github.com/remember-md/remember](https://github.com/remember-md/remember)
- **Original license:** MIT (© 2026 Gabi Fratica)
- **Notes:** Extended Second Brain — knowledge capture, session processing, belief evolution, brain stats, initialization.

  **Consolidation status (2026-05-17+):** the live implementation is
  now [`skills/brain/`](skills/brain/SKILL.md) — a Python rewrite with
  schema-driven domain yamls (`skills/brain/domain/schemas/note.schema.json`),
  Node+Flow async engine (PocketFlow `AsyncNode`), MCP-exposed tools,
  and SessionStart/UserPromptSubmit/SessionEnd hooks. The 5 originally-
  upstream skills (`remember/`, `process/`, `evolve/`, `status/`, `init/`)
  remain as thin back-compat wrappers; their bodies still describe the
  user-facing capture/process/evolve verbs but route through the
  `brain/` engine. `brain/SKILL.md` is the canonical reference.

  The original Node.js scripts (`build-index`, `extract`, `schema`,
  `promote`, `append-evidence`, `evolution-log`, `build-context`,
  `session_start`, `user_prompt`) are no longer present — the Python
  rewrite replaced them. Gabi's design (PARA dirs, note schema with
  `type/confidence/freshness/sources_count`, top-beliefs promotion
  cycle) is fully preserved.

## Plugin-original (always)

- `skills/workflow/` — the multi-stage routine engine + 12-check pre-commit gate + backlog CLI + semantic indexers. Drives `.kaizen/workflow/state.json`.
- `skills/onion-ddd-workflow/` — the theory + audit + plan + execute layering discipline.
- `skills/verify-before-execution/` — the RED-GREEN gate generalising TDD to non-test artifacts.
- `skills/iron-laws/`, `skills/brain/`, `skills/plugin-development/`, `skills/plugin-self-audit/`, `skills/handoff/`, `skills/audit/` (schemas), and most others not listed above.
- `scripts/`, `commands/`, `hooks/`, `bin/` — plugin entry points.
- `LICENSE`, `README.md`, `ATTRIBUTIONS.md`, `CHANGELOG.md`, `CONTRIBUTING.md`.

## Reporting attribution issues

If you are an original author and would like:

- Different wording in the credit line
- A different license assertion
- Additional information (e.g. funding sources, contributor lists)
- Removal of your credit if you no longer consider the kaizen derivative a fair adaptation

…please open an issue at [github.com/YugeIceCone/kaizen-md](https://github.com/YugeIceCone/kaizen-md/issues) and we will respond promptly.
