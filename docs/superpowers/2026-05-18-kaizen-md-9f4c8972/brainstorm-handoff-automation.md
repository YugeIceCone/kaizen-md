# Brainstorm — Handoff automation (token / context / mental load)

> **Trigger:** user 2026-05-18 sid 32bad1f7 — "brainstorm for handoff:
> more automation with scripts for token savings and optimizations,
> context budget, mental load."
>
> **Scope:** scripts / subcommands / hooks that shrink the cost (tokens
> read, decisions made, context burned) of working with handoffs.
> Pairs with the 6-of-which-3-shipped upgrade arc (parent_handoff /
> append / tree already landed; this brainstorm covers what's next).

---

## All 21 — ranked by impact × effort

| # | Idea | Theme | Impact | Effort | Score | Sprint |
|---|---|---|---|---|---|---|
| 1 | **`handoff cost --file X`** — token estimator (chars/4) + per-section breakdown + threshold warning | tokens | 5 | 1 | 25 | ✅ TDD now |
| 2 | **Smart since-cutoff** — when parent_handoff exists, default `since` to parent's date (not "1 week ago") | tokens | 4 | 1 | 16 | next |
| 3 | **`handoff resume --section X`** — surgical read; agent loads ONLY the named section, not whole file | context | 5 | 2 | 12 | next |
| 4 | **Auto-bridge in `auto-finalize`** — fold `bridge --apply` for high-confidence durables; one less manual step | mental | 4 | 2 | 8 | next |
| 5 | **`handoff diff X Y`** — section-by-section delta between 2 handoffs (chain-aware via parent_handoff) | tokens | 4 | 2 | 8 | defer |
| 6 | **`handoff resume --create-tasks`** — auto-mint TaskCreate calls for each `next[]` item on resume | mental | 4 | 2 | 8 | defer |
| 7 | **Skill-frame capture** (was Task #40 item #6) — record which skills loaded per phase; resume reloads only those | tokens | 4 | 3 | 7 | defer |
| 8 | **Structured `next[]`** (was Task #40 item #2) — promote string items to `{item, why, blocker}` objects | mental | 3 | 2 | 7 | defer |
| 9 | **Session re-mine surface** (was Task #40 item #1) — refresh handoff mid-session via re-mining JSONL | mental | 3 | 2 | 7 | defer |
| 10 | **Duplicate detector** — `next[]` items that match a `done_this_session.task` get auto-pruned on append | mental | 3 | 2 | 7 | defer |
| 11 | **Auto-promote `done` → `next` siblings** — completed entry suggests related next-actions via grep/sem | mental | 4 | 3 | 7 | defer |
| 12 | **`handoff validate`** — schema-validate full yaml against `handoff.schema.json`; catch drift early | mental | 3 | 2 | 6 | defer |
| 13 | **`handoff compact`** — collapse repetitive `done_this_session` entries via prefix merge (e.g. all `fix:` → group) | tokens | 3 | 3 | 6 | defer |
| 14 | **Auto-classify entries** — assign `kind: feat/fix/refactor/...` tag from commit-message regex | mental | 3 | 2 | 6 | defer |
| 15 | **Threshold-aware auto-handoff** — `auto-handoff.sh` factors `handoff cost` into the fire-decision (#1 enables this) | context | 4 | 3 | 6 | defer |
| 16 | **`handoff stream <events.jsonl>`** — append events live to a sink as work happens; replayable | tokens | 3 | 4 | 5 | defer |
| 17 | **Reference-by-anchor** — when prose section > N chars, replace with `prose: <slug>` linking to paired .md | tokens | 3 | 4 | 5 | defer |
| 18 | **`handoff replay`** — emit each section as a numbered prompt suitable for re-feeding a fresh agent | mental | 2 | 3 | 4 | defer |
| 19 | **`handoff snapshot`** — periodic tarball of yaml + state.json + cwd for rollback | safety | 2 | 3 | 4 | defer |
| 20 | **`handoff stats --since N`** — rollup over the last N handoffs: avg size, outcome distribution, drift count | mental | 2 | 3 | 4 | defer |
| 21 | **Auto-compact `done` on replay** — same-prefix entries appended twice get merged on next `auto-finalize` | tokens | 2 | 3 | 4 | defer |

---

## Top 1 to TDD this session

### #1 — `handoff cost --file X`

**Why:** Right now there's no visibility into how big a handoff has
grown. The drain-all session's handoff (this one) has 33 entries
under `done_this_session` and the file is ~5KB — but agents have no
signal saying "this is approaching the budget where reading the whole
thing wastes tokens — consider scaffolding fresh + chaining via
`parent_handoff`."

`handoff cost` makes that signal first-class:
- Pure read; no mutation
- Pairs with the just-shipped `parent_handoff` — the recommended
  remediation is "scaffold fresh + link via parent_handoff" so the
  chain stays intact without bloat
- Enables future items #15 (threshold-aware auto-handoff that factors
  yaml size) and #5 (`handoff diff` cost comparison)
- KISS shape — single subcommand, char-count / 4 token approximation
  (matches the convention used elsewhere in kaizen for fast estimates)

**TDD plan:**
1. RED: `test_compute_section_costs_returns_per_section_bytes`
   `test_total_matches_file_size`
   `test_threshold_default_2000`
   `test_threshold_env_overridable` (`KAIZEN_HANDOFF_COST_TOKEN_BUDGET`)
   `test_over_threshold_flag`
   `test_unknown_section_lumped_as_other`
   `test_cli_returns_json_envelope`
   `test_cli_human_output_lists_sections`
2. GREEN: implement `_compute_costs(text, body)` pure function +
   `_cmd_cost` CLI; register subcommand parser
3. REFACTOR: extract `_approx_tokens(s)` helper if used 2+ times

**Output shape (JSON):**
```json
{
  "file": "<path>",
  "size_bytes": 5043,
  "approx_tokens": 1261,
  "threshold_tokens": 2000,
  "over_threshold": false,
  "per_section": {
    "done_this_session": {"chars": 3200, "approx_tokens": 800, "pct": 63.5},
    "session_meta":      {"chars":  420, "approx_tokens": 105, "pct":  8.3},
    "...": {"...": "..."}
  },
  "recommendation": "ok — under budget"
}
```

**Human output:**
```
handoff cost: <file>
total:    5,043 bytes  ~1,261 tokens   (threshold 2,000)  ✓ ok

per section:
  done_this_session  3,200 chars  ~800 tok  (63.5% of total)
  session_meta         420 chars  ~105 tok  ( 8.3%)
  ...
```

---

## Deferred / future passes

Items 2–21 sit in 3 buckets:

- **Quick wins (1-3 days each):** #2, #3, #4, #5, #6, #14
- **Schema/data-model bumps:** #7, #8, #9, #10, #11, #12, #13
- **New surface area:** #15, #16, #17, #18, #19, #20, #21

The most natural next sprint pulls #2 (smart since-cutoff — enables
better defaults across the board) + #3 (selective resume — biggest
token-savings per dollar of effort) + #4 (auto-bridge — closes the
mental-load gap from finalize to brain capture).
