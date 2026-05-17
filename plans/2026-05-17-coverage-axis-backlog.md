# Coverage-axis backlog — deferred ideas from brainstorm pass

Plan-file storing the 50-idea brainstorm output from the 2026-05-17
session. Each entry is a candidate audit / coverage / quality axis
for the kaizen plugin. Currently shipped: 4 axes (token-bloat,
code-to-test-coverage, schema-coverage, name-quality-coverage).
Everything below is **deferred** until pulled into an active sprint.

## Status

- [ ] Tier 1 — high-value low-effort wins (vulture, trigger-phrase, wiring-completeness, test-isolation)
- [ ] Tier 2 — high-value medium-effort (mutation testing, function/class-name quality, error-capture)
- [ ] Tier 3 — research before building (comment quality, MCP latency, dxm-event registry)
- [ ] Tier 4 — defer until evidence of need

## Tier 1 — high-value, low-effort

| # | Idea | One-line implementation |
|---|---|---|
| 3 | dead-code coverage (`vulture-coverage`) | wrap `vulture --min-confidence 80 --json` as sub-gate |
| 15 | trigger-phrase coverage | regex over SKILL.md frontmatter `description:` — count quoted phrases |
| 34-38 | wiring-completeness coverage | cross-check plugin.json perms / hooks.json / bin/ / commands/*.md / mcpServers |
| 22 | test-isolation coverage | AST-scan test setUp for KAIZEN_*_PATH env-sandbox pattern |

## Tier 2 — high-value, medium-effort

| # | Idea | Implementation |
|---|---|---|
| 24 | mutation-testing coverage | wrap `mutmut run` per-module; emit kill-ratio |
| 10/11 | function/class-name quality | extend name_quality from module to function/class scope |
| 32 | error-capture coverage | AST-scan: every subprocess.run checked for returncode |

## Tier 3 — research before building

| # | Idea | Research needed |
|---|---|---|
| 1 | comment quality | needs LLM-judging or "rewrite-without-loss" rule |
| 26 | MCP latency budget | needs trace-derived p50/p95 baselines |
| 33 | dxm-event-type registry | inventory first — how scattered are evt_types today? |

## Tier 4 — defer (YAGNI risk)

Single-pass detector axes to skip until evidence:
- #5 stale internal references
- #6 markdown link rot
- #25 hook-latency (every hook already has `timeout` in hooks.json)
- #43-46 security extensions (audit.sh already handles most)
- #50 license-header

## Full 50-idea brainstorm (raw)

Content / artifact quality (extends token-bloat): #1 comment-quality, #2 TODO/FIXME age, #3 dead-code, #4 unused config keys, #5 stale internal refs, #6 markdown link rot, #7 heading-depth consistency, #8 trailing whitespace / mixed indent, #9 duplicate-section detection.

Naming / labels (extends name-quality): #10 function-name quality, #11 class-name quality, #12 test-name quality, #13 variable-name discipline, #14 SKILL frontmatter name matches dir, #15 trigger-phrase coverage.

Schema / shape (extends schema-coverage): #16 JSONSchema-usage, #17 schema-file naming, #18 validator-wiring, #19 domain-YAML lint.

Test quality (extends code-to-test): #20 test-density per public-fn, #21 skipped-test ratio, #22 test isolation, #23 mock-vs-real coverage, #24 mutation-testing.

Performance / cost: #25 hook latency, #26 MCP tool latency budget, #27 heavy-import detection, #28 per-feature cold-start, #29 cold-start cost map.

Observability: #30 hook trace coverage, #31 MCP trace coverage, #32 error capture, #33 dxm-event-type registry.

Wiring / completeness: #34 plugin.json perm coverage, #35 hooks.json wiring, #36 bin-wrapper coverage, #37 slash-command perm allowlist, #38 MCP-server registration.

Documentation: #39 SKILL.md required-sections, #40 references/ link coverage, #41 slash-command docstring, #42 CHANGELOG entry per release tag.

Security: #43 secret-pattern coverage, #44 path-traversal scan, #45 shell-injection scan, #46 tarfile filter='data' coverage.

Convention / style: #47 iron-law per-feature, #48 Conventional Commits drift detector, #49 architecture-log row alignment, #50 license-header coverage.

## Research-validated picks

- **vulture** (`/jendrikseipp/vulture`) — mature dead-code detector, pyproject.toml-configurable, ignore_decorators + min_confidence + whitelist support. Direct fit for #3.
- **mutmut** (`/websites/mutmut_readthedocs_io_en`) — Python mutation tester with incremental + parallel + interactive TUI + wildcards. Direct fit for #24.

## Pattern note

Every new axis follows the same template:
- `skills/workflow/scripts/<axis>.py`
- `bin/kaizen-<axis>`
- `_gate_<axis>` function added to `gatekeeper.py::SUB_GATES`
- row in CLAUDE.md Coverage-family table
- `tests/test_<axis>.py`

After 3 more axes ship, consider extracting a "coverage axis registry"
YAML so new axes only need a domain/yaml + a scoring function.
