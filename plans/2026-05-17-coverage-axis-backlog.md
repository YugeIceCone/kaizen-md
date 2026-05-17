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


## Appendix — live PreToolUse dxm sample (this session, last 30min, capped 30)
- 1779016567  PreToolUse  tool=Edit  id=toolu_01
- 1779016571  PreToolUse  tool=Edit  id=toolu_01
- 1779016575  PreToolUse  tool=Edit  id=toolu_01
- 1779016579  PreToolUse  tool=Read  id=toolu_01
- 1779016585  PreToolUse  tool=Edit  id=toolu_01
- 1779016588  PreToolUse  tool=Bash  id=toolu_01
- 1779016655  PreToolUse  tool=Bash  id=toolu_01
- 1779016727  PreToolUse  tool=mcp__arxiv__search_papers  id=toolu_01
- 1779016728  PreToolUse  tool=mcp__arxiv__search_papers  id=toolu_01
- 1779016728  PreToolUse  tool=mcp__claude_ai_Context7__resolve-library-id  id=toolu_01
- 1779016845  PreToolUse  tool=mcp__claude_ai_Context7__query-docs  id=toolu_01
- 1779016845  PreToolUse  tool=mcp__claude_ai_Context7__resolve-library-id  id=toolu_01
- 1779016852  PreToolUse  tool=mcp__claude_ai_Context7__query-docs  id=toolu_01
- 1779016996  PreToolUse  tool=Write  id=toolu_01
- 1779017003  PreToolUse  tool=Bash  id=toolu_01
- 1779017137  PreToolUse  tool=Bash  id=toolu_01
- 1779017141  PreToolUse  tool=Read  id=toolu_01
- 1779017145  PreToolUse  tool=Read  id=toolu_01
- 1779017158  PreToolUse  tool=Edit  id=toolu_01
- 1779017163  PreToolUse  tool=Read  id=toolu_01
- 1779017169  PreToolUse  tool=Edit  id=toolu_01
- 1779017172  PreToolUse  tool=Bash  id=toolu_01
- 1779017175  PreToolUse  tool=Bash  id=toolu_01
- 1779017179  PreToolUse  tool=Bash  id=toolu_01
- 1779017181  PreToolUse  tool=Bash  id=toolu_01
- 1779017187  PreToolUse  tool=Read  id=toolu_01
- 1779017195  PreToolUse  tool=Edit  id=toolu_01
- 1779017199  PreToolUse  tool=Bash  id=toolu_01
- 1779017269  PreToolUse  tool=Bash  id=toolu_01
- 1779017395  PreToolUse  tool=Bash  id=toolu_01

---

# Round 2 — 50 ideas: trace + dxm stream exploitation (deferred)

Vertical (per-feature depth) + horizontal (cross-feature breadth) over the
existing trace/dxm event streams. None shipped yet.

## A. Vertical — per-feature event timelines (10)

1. per-feature event timeline view  •  2. per-feature call-graph
3. per-feature latency histogram  •  4. per-feature error rate
5. per-feature first-fire / last-fire dates  •  6. per-feature hour×day heat-map
7. per-feature lifecycle audit (git log + trace first/last)
8. per-feature peak concurrency  •  9. per-feature retry rate
10. per-feature p95 latency regression detection

## B. Horizontal — cross-feature patterns (10)

11. tool-chain frequency analysis (Edit→Read→Bash motifs)
12. hook-fire cascade detection (A fires → B within ε)
13. cross-feature correlation matrix (P(Y|X) within N events)
14. cross-feature data-flow (file-path intersect)
15. tool-use bursts (Poisson-deviation clusters)
16. skill activation graph (co-load edges → implicit "pairs with")
17. cross-session anomaly detection (this vs lifetime mean)
18. cohort comparison (session-mode=loop|workflow|neither)
19. cross-MCP routing waste (overlap → absorb candidates)
20. feature usage decay curves (one-shot tool detection)

## C. Live monitoring (dxm — current session) (10)

21. live activity feed  •  22. live token-budget meter
23. live hook-latency dashboard  •  24. live error stream
25. live tool-call rate w/ surge detection
26. real-time skill-load tracking (since last UserPromptSubmit)
27. live MCP queue depth  •  28. per-prompt event diff
29. live concurrency map  •  30. live "hot" feature surface (top-5 in 60s)

## D. Lifetime analytics (trace — historical) (10)

31. top-N most-fired hooks  •  32. top-N most-called tools
33. never-used features (extend metrics never-used to bins/cmds)
34. feature half-life (date fire-rate dropped to 50% peak)
35. feature adoption curves  •  36. multi-session 3-motif mining
37. most-touched files lifetime  •  38. cross-project comparison
39. lifetime cost estimation (token projection)
40. hook reliability over time (failure-rate drift)

## E. Stream join / fusion (10)

41. trace ⨝ dxm union view (lifetime + live merged tape)
42. trace ⨝ token-bloat (which fires cause cumulative cost)
43. dxm ⨝ coverage gaps (untested files = more events?)
44. trace ⨝ handoff log (patterns preceding handoff)
45. dxm ⨝ intent rules (per-rule hit rate + downstream actions)
46. trace ⨝ git history (commit → activity change)
47. dxm ⨝ session-mode (loop vs workflow tool-mix delta)
48. trace ⨝ memory writes (which features → memory entries)
49. dxm ⨝ name-quality (bad-named files touched more?)
50. trace ⨝ token-bloat fire weighting (per-session vs lifetime)

**Top picks from Round 2:**
- B12 cascade detection + E42 trace ⨝ token-bloat (causal weight)
- A7 lifecycle audit (retire candidates)
- C28 per-prompt event diff ("what did this prompt cost")

---

# Round 3 — 50 ideas: agent-meta / session-shape / interaction patterns (deferred)

Round 1 = artifact quality (static). Round 2 = behavioural streams (dynamic).
Round 3 = how the agent + user interact with the plugin.

## F. Session-shape analytics (10)

1. turn-density (events per UserPromptSubmit)
2. prompt-rhythm (time between user prompts → stuck detection)
3. tool-mix per turn (Edit-heavy / Bash-heavy / Read-heavy)
4. cost-per-turn token distribution
5. conversation phase detection (exploration / impl / verification / handoff)
6. turn-to-commit ratio (working efficiency)
7. self-correction count (Edit retries on same file within N turns)
8. Read-then-Edit ratio (confidence proxy)
9. skill-load density per turn
10. end-of-turn shape (last-N events before each Stop)

## G. User-feedback signals (10)

11. redirect detection ("actually" / "wait" / "no" / "instead")
12. praise signal ("perfect" / "great" / "nice")
13. interruption events (user message during in-flight tool call)
14. question count (prompts ending "?")
15. imperative vs reflective prompts ("do X" vs "explain X")
16. prompt length distribution (short directives vs long specs)
17. repeat-keyword detection (unclear delivery signal)
18. acceptance latency (turns: proposal → user "yes go")
19. roll-back signals (undo / revert / drop)
20. user-extension signals ("also do X" mid-stream)

## H. Subagent dynamics (10)

21. subagent dispatch rate  •  22. subagent depth (nested layers)
23. subagent cost vs quality  •  24. subagent isolation audit
25. subagent overlap (same task twice)  •  26. subagent completion-rate
27. subagent type-usage (research / Explore / general-purpose)
28. parent-subagent context transfer (re-reads after return)
29. SubagentStop pattern (what fires immediately after)
30. subagent vs in-process (when is one better?)

## I. Cross-session / longitudinal (10)

31. returning-user signals  •  32. session-mode evolution
33. skill drift (load count over time)
34. bin-adoption curve  •  35. feature-deprecation candidates (no fire in N sessions)
36. pattern memorisation (fix repeat from prior session?)
37. memory recall rate  •  38. persona top-belief utilization
39. handoff effectiveness (resume vs cold-start time-to-productive)
40. brain growth rate (Notes/Persona deltas per week)

## J. Self-improvement / failure-mode loops (10)

41. silent-fail detection (hook returned {} when it should fire)
42. empty-tool-result tracking  •  43. tool-error catalog (top N patterns)
44. iron-law violation introduction-rate (per N commits)
45. test-flake detection (intermittent pass/fail)
46. commit-revert rate  •  47. plan-deviation rate
48. Stop-hook block rate (auto-handoff fires vs ignored)
49. permission-prompt frequency (Bash perm not in allow-list catalog)
50. cache-hit rate (Skill / context cache effectiveness)

**Top picks from Round 3:**
- F2 prompt-rhythm + F1 turn-density (in-flight context-bloat signal)
- J41 silent-fail detection (catches forgot-to-fire bugs)

---

# Round 4 — "The streams ARE the answer" — deeper exploitation (deferred)

Reframe: every "coverage" question is actually a stream query. Build the
substrate, then 30+ axes become trivial.

## K. Stream substrate primitives (10)

1. **append-to as a universal pattern** — extend to every stream-emitter:
   `kaizen-trace append-to`, `kaizen-metrics append-to`,
   `kaizen-bloat append-to`, `kaizen-coverage append-to`
2. **Generic stream sink** — `kaizen-stream <source> append-to <target> [filter]`
   abstracted over (trace / dxm / metrics / bloat)
3. **Stream join CLI** — `kaizen-stream join trace dxm --on session_id`
4. **Stream pipe** — `kaizen-trace tail --json | kaizen-bloat correlate`
5. **Stream window** — uniform `--back / --window-from/to / --since-unix`
   across every stream-emitter (already in dxm; mirror to trace + metrics)
6. **Stream format adapters** — md / jsonl / csv / human, picked at consumer
7. **Stream filter DSL** — `--where "evt_type=PreToolUse AND tool=Bash"`
   instead of a flag per-field (when N filters grow)
8. **Stream tee** — fan-out to multiple sinks (file + dxm-event + trace)
9. **Stream tail-and-follow** — `--follow` flag (like `tail -F`) for live consumers
10. **Stream backpressure** — `--max-rate N/s` for live tail-and-follow

## L. Coverage-as-stream-query (10)

11. **Axis-as-yaml** — `domain/coverage-axes/<axis>.yaml` declaring the stream query + threshold; generic runner executes
12. **Coverage delta** — N-th-most-recent-scan minus latest (auto-archive diff)
13. **Trend** — sparkline per coverage axis from history JSONL
14. **Auto-promote** — when a coverage axis stays clean for K scans, demote its check frequency
15. **Auto-fire** — when a coverage axis spikes, surface as additionalContext
16. **Coverage event stream** — every scan emits `<axis>.scanned` event;
    correlate axes via the event stream (`trace ⨝ trace`)
17. **Coverage rubric** — yaml-driven scoring (like split-rubric) for ANY axis,
    so adding a new axis is a yaml edit
18. **Coverage budget** — per-axis max waste tokens; budget exhaustion → red
19. **Coverage debt curve** — debt accumulating per axis vs paid-down rate
20. **Cross-axis correlation** — when token-bloat goes up, does name-quality follow?

## M. Streams as the canonical SSOT (10)

21. **Findings ARE events** — don't store findings in JSON files; emit them
    to the trace stream and `kaizen-trace query --evt token-bloat.finding`
    rebuilds the snapshot on demand
22. **Plans ARE event projections** — plan files derive from event motifs
    matched against templates; auto-update as events accumulate
23. **CHANGELOG IS a trace projection** — `kaizen-trace export --as-changelog`
    instead of hand-maintained
24. **Backlog IS a query** — backlog items derive from open `*.candidate` events
    in the stream; no separate JSON file
25. **Tests ARE replayed events** — capture a session's events; replay them
    against a fresh codebase as a regression suite
26. **Handoff IS a stream snapshot** — auto-generate handoff YAML from last
    N events + commit log + diff
27. **Persona IS a slow-rolled aggregation** — top beliefs derived from
    confidence-weighted memory-write events
28. **Audit reports ARE filtered views** — `kaizen-audit` = filtered stream
    of `*.finding` events grouped by severity
29. **The architecture log IS a commit-event projection** — drop progress.md;
    derive it from `git log + plan-tick events`
30. **Skill suggestions ARE intent-event matches** — drop static rules;
    derive triggers from observed phrase ↔ skill-load correlations

## N. Pattern mining over streams (10)

31. **Frequent-itemset over tool-sequences** — Apriori / FP-Growth on
    `[tool_name, tool_name, tool_name]` 3-grams; find common chains
32. **Anomaly detection** — z-score baseline per tool; flag this-turn outliers
33. **Markov-chain transitions** — P(next tool | current tool); detect
    unexpected transitions
34. **Session clustering** — group sessions by tool-mix vector; find archetypes
35. **Hot-edit clusters** — files edited within N seconds of each other =
    implicit "co-change" pairs
36. **Sequence-to-feature** — given an event sequence, infer the active feature
37. **Outlier-feature detection** — features whose event signature differs
    sharply from siblings
38. **Causal-inference graph** — events A and B; does A cause B or coincidence?
39. **Bottleneck detection** — which event-types account for the longest p95
    delay between adjacent events
40. **Goldilocks zone** — for a given session-mode, optimal turn-density /
    skill-load / tool-mix that correlates with high commit-rate

## O. Stream-driven self-improvement (10)

41. **Auto-deprecate** — never-fired features for K weeks → archive PR
42. **Auto-promote** — heavily-fired ad-hoc patterns → suggest extraction to skill
43. **Auto-rebalance** — when X axis spikes, allocate next iteration to fix
44. **Auto-budget** — predict session token spend from rolling event rate
45. **Auto-handoff cause-of-death** — record which event-pattern triggered fire
46. **Auto-coverage-axis** — when a new bug class repeats, generate a coverage axis
47. **Auto-skill-suggest** — observed `phrase → Skill load` pairs train the router
48. **Auto-intent-rule** — phrase clusters with high downstream-action rate
    become new intent rules
49. **Auto-rubric** — high-frequency decisions converted to rubric.yaml entries
50. **Auto-test** — record a known-good event sequence as a replay test

**Cross-thread synthesis:**

- The plugin already EMITS rich streams; what's missing is the
  **substrate primitives** (K1-K10) that make consumers cheap.
- Once K is built, **every coverage axis becomes a yaml** (L11) and the
  plugin stops growing custom Python per axis.
- **M (streams as SSOT)** is the radical reframe: stop persisting derived
  state; derive it on demand from the events. Smaller surface, fewer dupes,
  one source of truth.
- **N (pattern mining)** is the research-grade payoff: with the substrate in
  place, learning from observation becomes tractable.
- **O (self-improvement)** is the long arc: the plugin observes its own use
  and proposes improvements.

**Recommended next 3 builds (after Round 1's 4 axes):**

1. **K1+K3** — extend `append-to` to trace + metrics; add `stream join` CLI.
   3 small files, immediate leverage for every consumer downstream.
2. **L11** — coverage-axis YAML registry + generic runner. After 3 more
   axes land, this is the consolidation the pattern-note in Round 1 called for.
3. **C28** — per-prompt event diff (Round 2 winner). Cheapest live-monitoring
   primitive that surfaces in-flight context-bloat before auto-handoff fires.

---

# Round 5 — 150 new ideas across 10 buckets (151-300 cumulative)

Research-informed (context7: DuckDB + Radon; arxiv rate-limited — gap noted).

## P. SQL-over-streams (DuckDB) — 15
151 `kaizen-sql 'SELECT ...'` thin wrapper • 152 pre-built views • 153 JSONL-as-table (no ETL) • 154 cross-stream JOIN • 155 window-function cumulative cost • 156 CTEs for multi-stage • 157 materialised views • 158 SQL-driven coverage axes • 159 `time_bucket` rollups • 160 `approx_quantile` p95 dashboards • 161 EXPLAIN for slow queries • 162 SQL REPL • 163 SQL→markdown renderer • 164 per-session VIEW • 165 Parquet archive (DuckDB COPY)

## Q. Code metrics (Radon) — 15
166 `kaizen-complexity` per-fn CC • 167 MI per file • 168 Halstead volume/effort • 169 CC SUB_GATE • 170 CC trend over time • 171 CC vs test-coverage corr • 172 CC vs bloat corr • 173 per-feature CC budget • 174 fn-length histogram • 175 LCOM class cohesion • 176 import-fanout • 177 PR CC gate • 178 big-bang refactor candidates • 179 dead-complexity (radon + vulture + trace) • 180 hotspot (CC × churn)

## R. Visualization & rendering — 15
181 statusline live cost + bloat • 182 ASCII sparklines • 183 Sankey tool-chain • 184 heatmap PNG (hour×day×tool) • 185 timeline graph per session • 186 Mermaid from rubric YAML • 187 colour terminal tables • 188 HTML report bundle • 189 live dashboard server • 190 visual snapshot diff • 191 file-touch heatmap • 192 skill-load co-occurrence graphviz • 193 cost-gauge glyph • 194 per-prompt cost mini-table • 195 end-of-session card

## S. CI/CD integration — 15
196 GH Actions kaizen gatekeeper • 197 pre-commit framework • 198 PR coverage-delta comment • 199 auto-label by feature changes • 200 `kaizen-bench` latency baselines • 201 failure-replay artifact • 202 PR token-bloat comment • 203 snapshot-diff bot • 204 branch protection (red gate blocks) • 205 dependabot for vendored skills • 206 auto-publish on tag • 207 release-notes generator • 208 hook health-check CI • 209 MCP smoke-test CI • 210 cross-OS matrix

## T. Multi-user / collaboration — 15
211 per-user session-mode prefs • 212 shared team brain overlays • 213 pair-coding session linking • 214 code-review handoff • 215 conflict detection (kaizen.toml) • 216 team-wide axis pinning • 217 per-user inbox routing • 218 per-user audit log • 219 perm-grant approval workflow • 220 cross-user backlog • 221 shared metric dashboards • 222 per-user iron-law overrides • 223 mentor/junior roles • 224 brain-export knowledge handoff • 225 team retrospective generator

## U. Privacy / redaction / safety — 15
226 auto-redact secrets in trace • 227 per-event PII tagger • 228 redaction profile per surface • 229 network-egress trace • 230 SBOM-style MCP reach audit • 231 hash-only event storage • 232 local-only mode • 233 time-limited brain notes • 234 per-skill data classification • 235 encrypted trace storage • 236 audit hash-chain seal • 237 sandbox profile per skill • 238 egress allowlist • 239 `/kaizen:logout` memory cleanse • 240 per-project data residency

## V. Cost telemetry — 15
241 per-tool token cost coefficients • 242 per-session USD estimate • 243 burn-rate alert • 244 cost forecast • 245 most-expensive top-N • 246 per-feature cost attribution • 247 cost-vs-value heatmap • 248 monthly rollup • 249 cost-regression detector • 250 "/compact" suggestion when over • 251 per-task token envelope • 252 subagent cost amortisation • 253 cache-hit savings calc • 254 free-tier alert • 255 cost-aware tool selection

## W. Plugin-marketplace meta — 15
256 cross-plugin coordination • 257 compat matrix • 258 version-skew detection • 259 plugin permission audit • 260 plugin-load order analyser • 261 conflict detection (same MCP) • 262 marketplace local search • 263 update notifications • 264 per-plugin telemetry opt-in • 265 manifest schema validator • 266 uninstall cleanup verifier • 267 plugin-share manifest export • 268 trust score (signed manifests) • 269 plugin-pack bundles • 270 recommendation engine

## X. Disaster recovery / state versioning — 15
271 schema migration framework • 272 atomic state-bundle snapshot • 273 per-file rollback to ts • 274 corruption detection (checksums) • 275 state quorum • 276 portable archive export • 277 disaster-replay from event stream • 278 state-diff between timestamps • 279 versioning headers in JSON • 280 migration test fixtures • 281 brain auto-backup before evolve • 282 crashed-tool recovery • 283 hot-reload without restart • 284 read-only state-debug mode • 285 state-rebuild from events alone

## Y. Agentic self-modification — 15
286 recurring-fix → skill extraction • 287 frequent chains → macro • 288 phrasing → intent rule • 289 oversized file → split-plan (partial) • 290 repeated subagent prompts → agent def • 291 hook for repeated post-prompt actions • 292 auto-promote experiments to defaults • 293 self-tuning bloat thresholds • 294 self-extending iron-laws • 295 auto-deprecate unused after N weeks • 296 memory decay (low-confidence) • 297 self-tuning auto-handoff threshold • 298 CLAUDE.md update proposals • 299 auto-test from bug-fix sessions • 300 self-improving research-tool selection

## Cross-thread synthesis (rounds 1-5)

- **DuckDB unlocks Round 4 M (streams-as-SSOT)**: `read_json('events-*.jsonl')` = SQL queries over existing JSONL, zero new infra. Most-leveraged finding of the day.
- **Radon is a drop-in** for Q (complexity axes), mirroring vulture's role for dead-code (round 1 Tier 1).
- **arxiv gap noted** per the new brainstorming-skill required-tools rule (rate-limited; would have validated motif-mining + complexity-research literature).
- **300 total ideas across 5 rounds.** Coverage axes (R1), stream exploitation (R2), interaction patterns (R3), streams-as-SSOT (R4), and SQL-substrate + complexity + viz + CI + multi-user + privacy + cost + marketplace + DR + self-modification (R5).

## Updated recommended next 5 builds

1. **R5#153 + R5#154** — DuckDB wrapper: `kaizen-sql` over event JSONL. Single small file, unlocks dozens of axes-as-queries.
2. **R5#166** — `kaizen-complexity` via radon wrap. 5th audit gate.
3. **R1#3** — `vulture-coverage` (Tier 1 from round 1 still standing).
4. **R4#K1** — extend `append-to` to trace + metrics (after dxm proves the pattern this session).
5. **R2#C28** — per-prompt event diff (cheapest in-flight bloat signal).
