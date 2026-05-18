# Ralph automation — 30 improvements

**Trigger:** Earlier this session a stale `.kaizen/loop.state.md` from iteration 3 of a long-dead task wedged the Stop hook for ~10 turns. Root cause was 2-fold (transcript-path turn-id fallback collision + no auto-cleanup of stale state). The turn-id bug is now fixed (`3b14961`). This doc captures the broader "fully automated" target so Ralph doesn't need manual hand-holding.

**Goal:** Ralph runs end-to-end without human-in-the-loop prompting — self-cleans, self-recovers, self-completes.

---

## All 30 — ranked by impact × effort

| # | Improvement | Theme | Impact | Effort | Score | Sprint |
|---|---|---|---|---|---|---|
| 1 | **TTL on loop state** — auto-delete state files older than N hours | lifecycle | 5 | 2 | 10 | ✅ TDD now |
| 2 | **Auto-archive on session boundary** — different session_id → archive + start fresh | lifecycle | 5 | 2 | 10 | ✅ TDD now |
| 3 | **Stuck-run escalation** — `stuck_run >= N` (field exists) → auto-cancel + handoff suggestion | recovery | 5 | 2 | 10 | ✅ TDD now |
| 4 | **Workflow-config defaults** — `/kaizen:loop` reads `.kaizen/workflow.json::loop.*` for `--its`/`--stop` defaults | integration | 4 | 2 | 8 | ✅ done |
| 5 | **Per-iteration dxm trace** — emit event per Stop fire (action/decision/ledger-delta) | observability | 4 | 2 | 8 | ✅ done |
| 6 | **Implicit ledger from TODOs** — parse `- [ ]` items in user prompt as ledger seed | ergonomics | 4 | 3 | 7 | ✅ done |
| 7 | **Auto-verify-shape detection** — `desc: "ship X"` → suggest `git log --grep=X` | ergonomics | 4 | 3 | 7 | next |
| 8 | **Verify-cmd retries** — N-retry with backoff for flaky commands | recovery | 3 | 3 | 6 | defer |
| 9 | **Auto-archive completed loops** — `.kaizen/loops/<UTC>.archive.md` instead of delete | auditability | 3 | 2 | 6 | defer |
| 10 | **Per-item failure surfacing** — fail-N-times items surface for manual review | observability | 3 | 3 | 6 | defer |
| 11 | **Iteration budget elasticity** — making progress → auto-extend `max_iterations` | recovery | 4 | 4 | 5 | defer |
| 12 | **Watchdog PostToolUse hook** — periodic stale-loop check, dxm warn | observability | 3 | 3 | 5 | defer |
| 13 | **Live status MCP tool** — query loop progress without file read | observability | 3 | 3 | 5 | defer |
| 14 | **JSON Schema for state file** — validate frontmatter + body at every write | schema | 3 | 3 | 5 | defer |
| 15 | **Verify timing histogram** — per-cmd avg time, flag slow ones | observability | 3 | 3 | 5 | defer |
| 16 | **Brain-capture on every completed item** — write to kaizen-gold | integration | 3 | 3 | 5 | defer |
| 17 | **Pre-emptive handoff on stuck** — auto-trigger `/kaizen:handoff create` | integration | 4 | 5 | 4 | defer |
| 18 | **Self-cancel on context pressure** — when auto-handoff fires for context, cancel loop too | recovery | 4 | 5 | 4 | defer |
| 19 | **Failure dashboard** — `kaizen-loop failures` summarizes recurring verify fails | observability | 3 | 4 | 4 | defer |
| 20 | **State diff between iterations** — `kaizen-loop diff <iter-a> <iter-b>` | debugging | 3 | 4 | 4 | defer |
| 21 | **Loop replay** — rewind state to iteration N | debugging | 3 | 5 | 3 | defer |
| 22 | **Multiple concurrent loops** — per-branch state files | scope | 4 | 7 | 3 | defer |
| 23 | **Loop queueing** — queue next loop after current completes | scope | 3 | 6 | 3 | defer |
| 24 | **Cross-session loops** — survive session boundaries (vs #2 — opposite choice) | scope | 2 | 5 | 2 | defer (conflicts w/ #2) |
| 25 | **Migration on schema bump** — older state files auto-upgrade | schema | 2 | 4 | 2 | defer |
| 26 | **Pretty-print status** — `kaizen-loop status --rich` colored output | ergonomics | 2 | 3 | 3 | defer |
| 27 | **Auto-start from workflow Q2=Loop** — super-menu pick auto-invokes loop slash | integration | 3 | 4 | 4 | defer |
| 28 | **Auto-prompt regeneration** — when stuck, LLM reframes next prompt | recovery | 4 | 8 | 2 | defer (needs LLM) |
| 29 | **Per-item timeout per verify** — long-running verify gets killed at N seconds | recovery | 3 | 3 | 5 | defer |
| 30 | **Auto-promise on ledger empty** — explicit completion signal even without `--promise` | completion | 3 | 2 | 6 | (already works — verify) |

---

## Top 3 to TDD this session

### #1 — TTL on loop state

**Why:** Exact bug that bit this session. Stop hook reads stale state, idempotence-traps subsequent Stops.

**TDD:**
1. RED: test that loop_ledger refuses to act on state-files with `started_at` older than `KAIZEN_LOOP_TTL_HOURS` (default 24).
2. GREEN: extend stop-ralph.sh to compute age from `started_at`, archive + skip when exceeded.
3. REFACTOR: env-knob configurable.

### #2 — Auto-archive on session boundary

**Why:** When a new session starts and finds a state file from a different `session_id`, that state is orphan — should archive, not block.

**TDD:**
1. RED: test that stop-ralph.sh archives state when `STATE_SESSION` is set AND ≠ current `HOOK_SESSION`.
2. GREEN: replace silent `exit 0` (current behavior at line 89) with archive-then-exit.
3. REFACTOR: archive dir path SSOT.

### #3 — Stuck-run escalation

**Why:** State file already carries `stuck_run: N` (loop_ledger writes it when body sha doesn't change between iterations). Currently it's surfaced but never acted on — should auto-cancel + leave breadcrumb when `stuck_run >= STUCK_THRESHOLD`.

**TDD:**
1. RED: test that loop_ledger emits `complete-stuck` action when `stuck_run >= 5` (configurable via env).
2. GREEN: add the early-exit branch.
3. REFACTOR: threshold via `KAIZEN_LOOP_STUCK_THRESHOLD` env.

---

## Deferred (next sprint targets, ranked by score)

Items 4–7 (score 7–8) are the natural next pass — workflow-config defaults (#4), dxm trace per iteration (#5), implicit ledger from TODOs (#6), verify-shape detection (#7). Items 8–21 each warrant their own focused TDD session.

Items 22–24 (multi-loop / queueing / cross-session) need a coordinated design — defer until automation top-tier is stable.
