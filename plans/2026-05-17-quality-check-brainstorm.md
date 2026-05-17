# Quality-check brainstorm — 20 improvements

**Date:** 2026-05-17
**Trigger:** Quality audit surfaced 33 frontmatter name-mismatches (now fixed in `307e741`), 50+ weak-routing skills (<3 trigger phrases), and 1 slash-name collision (gate↔gatekeeper, resolved by `96a9f10` precommit rename).
**Goal:** Capture 20 distinct quality-check improvements, rank them, TDD-implement top 3 this session.

---

## All 20 — ranked by impact × effort

| # | Improvement | Axis | Impact | Effort | Score | Sprint |
|---|---|---|---|---|---|---|
| 1 | **Frontmatter `name:` ↔ dir lint** — hard-gate via gatekeeper | name-quality | 5 | 2 | 10 | ✅ TDD now |
| 2 | **Weak-routing detector** (require ≥3 quoted phrases in description) — soft-gate | frontmatter | 5 | 2 | 10 | ✅ TDD now |
| 3 | **Slash-prefix collision lint** (≥4 chars shared = warn) | name-quality | 4 | 2 | 8 | ✅ TDD now |
| 4 | **Skill body required-section lint** (Iron Law / Decision rules / Triggers / Examples) | content-quality | 5 | 3 | 8 | next |
| 5 | **Description-length cap** (≤200 chars to fit in skill-router) | frontmatter | 4 | 2 | 8 | next |
| 6 | **Triggers field promotion** — `triggers:` as a structured array, deprecate quoted-phrases-in-description | frontmatter | 5 | 3 | 8 | next |
| 7 | **Cross-link integrity** — every `[[Notes/X]]` resolves; every `commands/X.md` reference exists | links | 4 | 3 | 7 | next |
| 8 | **Skill version field** — every SKILL.md declares `metadata.version`; bump on each edit | versioning | 3 | 3 | 6 | defer |
| 9 | **Allowed-tools coverage** — every backing script the body invokes appears in allowed-tools | iron-law | 5 | 4 | 5 | defer |
| 10 | **Description routing-keyword test** — fire 5 sample phrases per skill, assert match | semantic | 4 | 4 | 5 | defer |
| 11 | **Naming-convention rubric** — verb-first imperative vs noun (e.g. "review" vs "reviewing") | convention | 3 | 3 | 5 | defer |
| 12 | **Skill graveyard auto-archive** — skills not loaded in 90 days surface for review | lifecycle | 4 | 5 | 4 | defer |
| 13 | **Duplicate-content detector** — skills with >80% overlap surface as merge candidates | dedup | 5 | 6 | 4 | defer |
| 14 | **Description style guide** — lint for "Use when X" pattern + ban hype words | style | 3 | 4 | 4 | defer |
| 15 | **Subcommand catalog parity** — bin subcommands + slash subcommands + MCP tools match | parity | 4 | 5 | 4 | defer |
| 16 | **Skill-loader smoke test** — every SKILL.md loads without parse error in CI | basic | 3 | 3 | 4 | defer |
| 17 | **Per-skill test coverage** — assert ≥1 test per skill in `tests/test_<skill>*.py` | coverage | 4 | 6 | 3 | defer |
| 18 | **Trigger-phrase overlap** — two skills sharing ≥2 trigger phrases surface as routing-ambiguous | routing | 3 | 5 | 3 | defer |
| 19 | **Skill body length cap** — bodies >800 lines surface for split (kaizen has 3+ already) | bloat | 3 | 3 | 4 | defer |
| 20 | **Tab-completion collision** — slashes sharing ≥3-char prefix surface (covered by #3, separate fixture) | UX | 3 | 2 | 5 | merged into #3 |

---

## Top 3 to TDD this session

### #1 — Frontmatter `name:` ↔ dir lint (hard-gate)

**Why:** Just fixed 33 mismatches manually. Without a gate, they'll re-drift. The `kaizen-frontmatter gaps` tool detects them but doesn't BLOCK commits.

**TDD:**
1. RED: write test asserting gatekeeper red-verdicts when a SKILL.md has `name:` ≠ dir basename
2. GREEN: add `frontmatter-name-match` SUB_GATE to gatekeeper that calls `kaizen-frontmatter check --json` and fails on any name-mismatch
3. REFACTOR: extract the name-check from the existing `gaps` subcommand into a focused `check` subcommand

### #2 — Weak-routing detector (soft-gate)

**Why:** Skill-suggest hook relies on quoted-phrase matching in descriptions. 50+ skills have <3 phrases — they're invisible to phrase routing.

**TDD:**
1. RED: assert a SKILL.md with 0 quoted phrases in `description:` triggers a soft warning
2. GREEN: extend `frontmatter check` to emit warn-level for weak-routing (already detected; just plumb through the verdict)
3. REFACTOR: parameterize the threshold (default 3, configurable via env)

### #3 — Slash-prefix collision lint

**Why:** User flagged `mode/models` and `gate/gatekeeper` collisions this session. A periodic lint catches future ones.

**TDD:**
1. RED: assert that when 2+ slashes share a ≥4-char prefix, the lint emits a warning row with each colliding name
2. GREEN: write `kaizen-slash-collision` CLI scanning `commands/*.md` filenames
3. REFACTOR: register as a gatekeeper SUB_GATE

---

## Deferred / future passes

Items 4–20 ranked by score. The "next" tier (4 / 5 / 6 / 7) is the natural follow-up sprint. Items 8–19 each warrant a focused session. Item 20 collapses into #3.
