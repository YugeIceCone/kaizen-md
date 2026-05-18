# Coverage-ideas master checklist (300 ideas)

- **Source:** `~/workspace/semantic-search/docs/2026-05-17-coverage-ideas.jsonl` (300 lines, id == line number)
- **Generated:** 2026-05-18 (after the 30-axis coverage loop)
- **Shipped:** 33/300 (11.0%) — 30 this run + 3 prior
- **Pending:** 267

Format: `- [x] **#ID** (line N) [tier T / status S / bucket B] idea — kaizen-axis (if shipped)`

---

## bucket: `content` (8/9 shipped)

- [ ] **#1** (line 1-1) [tier 3 / status deferred] comment-quality coverage (rewrite-without-loss)
- [x] **#2** (line 2-2) [tier 4 / status deferred] TODO/FIXME age inventory via git-blame — **kaizen-todo-inventory**
- [x] **#3** (line 3-3) [tier 1 / status deferred] dead-code detection (vulture) — **kaizen-dead-code**
- [x] **#4** (line 4-4) [tier 3 / status deferred] unused config keys (env defined but never read) — **kaizen-unused-env**
- [x] **#5** (line 5-5) [tier 4 / status deferred] stale internal references — **kaizen-md-link-rot**
- [x] **#6** (line 6-6) [tier 4 / status deferred] markdown link rot — **kaizen-md-link-rot**
- [x] **#7** (line 7-7) [tier 3 / status deferred] heading-depth consistency — **kaizen-md-heading-depth**
- [x] **#8** (line 8-8) [tier 4 / status deferred] trailing whitespace / mixed indentation — **kaizen-md-whitespace**
- [x] **#9** (line 9-9) [tier 3 / status deferred] duplicate-section detection — **kaizen-md-dupes**

## bucket: `naming` (5/6 shipped)

- [ ] **#10** (line 10-10) [tier 2 / status deferred] function-name quality (body verb match)
- [x] **#11** (line 11-11) [tier 2 / status deferred] class-name quality — **kaizen-class-name-quality**
- [x] **#12** (line 12-12) [tier 3 / status deferred] test-name quality test_<X>_<scenario> — **kaizen-tname-quality**
- [x] **#13** (line 13-13) [tier 4 / status deferred] variable-name discipline — **kaizen-var-name-quality**
- [x] **#14** (line 14-14) [tier 1 / status shipped] SKILL frontmatter name matches dir basename — **kaizen-frontmatter (SKILL name match)**
- [x] **#15** (line 15-15) [tier 1 / status shipped] trigger-phrase coverage (>=3 quoted phrases per SKILL desc) — **kaizen-frontmatter (≥3 trigger phrases)**

## bucket: `schema` (1/4 shipped)

- [x] **#16** (line 16-16) [tier 2 / status deferred] JSONSchema actually loaded at runtime — **kaizen-schema-load-coverage**
- [ ] **#17** (line 17-17) [tier 4 / status deferred] schema-file naming convention
- [ ] **#18** (line 18-18) [tier 2 / status deferred] validator-wiring (loader calls .validate)
- [ ] **#19** (line 19-19) [tier 3 / status deferred] domain-YAML PyYAML-strict lint

## bucket: `tests` (2/5 shipped)

- [x] **#20** (line 20-20) [tier 2 / status deferred] test-density per public function — **kaizen-density**
- [ ] **#21** (line 21-21) [tier 3 / status deferred] skipped-test ratio
- [x] **#22** (line 22-22) [tier 1 / status deferred] test-isolation env-sandbox AST scan — **kaizen-sandbox-check**
- [ ] **#23** (line 23-23) [tier 2 / status deferred] mock-vs-real coverage pairing
- [ ] **#24** (line 24-24) [tier 2 / status deferred] mutation-testing kill-ratio (mutmut)

## bucket: `perf` (1/5 shipped)

- [ ] **#25** (line 25-25) [tier 4 / status deferred] hook latency timeout coverage
- [ ] **#26** (line 26-26) [tier 3 / status deferred] MCP tool latency budget p50/p95
- [x] **#27** (line 27-27) [tier 2 / status deferred] heavy-import detection (eager torch/transformers) — **kaizen-heavy-imports**
- [ ] **#28** (line 28-28) [tier 3 / status deferred] per-feature cold-start time
- [ ] **#29** (line 29-29) [tier 3 / status deferred] cold-start cost map

## bucket: `obs` (3/4 shipped)

- [x] **#30** (line 30-30) [tier 2 / status deferred] hook trace coverage extension — **kaizen-hook-trace-coverage**
- [x] **#31** (line 31-31) [tier 2 / status deferred] MCP trace-event coverage — **kaizen-mcp-trace-coverage**
- [x] **#32** (line 32-32) [tier 2 / status deferred] error-capture AST scan (subprocess.run returncode) — **kaizen-subprocess-rc**
- [ ] **#33** (line 33-33) [tier 3 / status deferred] dxm-event-type registry

## bucket: `wiring` (5/5 shipped)

- [x] **#34** (line 34-34) [tier 1 / status deferred] plugin.json perm coverage per script — **kaizen-perm-coverage**
- [x] **#35** (line 35-35) [tier 1 / status deferred] hooks.json wiring coverage — **kaizen-hook-coverage**
- [x] **#36** (line 36-36) [tier 1 / status deferred] bin-wrapper per argparse-main script — **kaizen-bin-coverage**
- [x] **#37** (line 37-37) [tier 1 / status deferred] slash-command allowed-tools coverage — **kaizen-command-allowed-tools-coverage**
- [x] **#38** (line 38-38) [tier 1 / status deferred] MCP-server in plugin.json mcpServers — **kaizen-mcp-coverage**

## bucket: `docs` (0/4 shipped)

- [ ] **#39** (line 39-39) [tier 3 / status deferred] SKILL.md required-sections audit
- [ ] **#40** (line 40-40) [tier 3 / status deferred] references/ link coverage from SKILL.md
- [ ] **#41** (line 41-41) [tier 3 / status deferred] slash-command docstring presence
- [ ] **#42** (line 42-42) [tier 3 / status deferred] CHANGELOG entry per release tag

## bucket: `security` (0/4 shipped)

- [ ] **#43** (line 43-43) [tier 4 / status deferred] secret-pattern coverage
- [ ] **#44** (line 44-44) [tier 4 / status deferred] path-traversal scan on Path() concat
- [ ] **#45** (line 45-45) [tier 4 / status deferred] shell-injection scan extension
- [ ] **#46** (line 46-46) [tier 4 / status deferred] tarfile filter='data' coverage

## bucket: `convention` (0/4 shipped)

- [ ] **#47** (line 47-47) [tier 2 / status deferred] iron-law conformance per-feature
- [ ] **#48** (line 48-48) [tier 3 / status deferred] Conventional Commits CHANGELOG vs git log drift
- [ ] **#49** (line 49-49) [tier 3 / status deferred] architecture-log row alignment per new file
- [ ] **#50** (line 50-50) [tier 4 / status deferred] license-header coverage (SPDX)

## bucket: `vertical-A` (0/10 shipped)

- [ ] **#51** (line 51-51) [tier ? / status deferred] per-feature event timeline view
- [ ] **#52** (line 52-52) [tier ? / status deferred] per-feature call-graph (hooks->tools->MCPs)
- [ ] **#53** (line 53-53) [tier ? / status deferred] per-feature latency histogram
- [ ] **#54** (line 54-54) [tier ? / status deferred] per-feature error rate
- [ ] **#55** (line 55-55) [tier ? / status deferred] per-feature first-fire/last-fire dates
- [ ] **#56** (line 56-56) [tier ? / status deferred] per-feature hour-of-day heat-map
- [ ] **#57** (line 57-57) [tier 1 / status top-pick] per-feature lifecycle audit (git+trace)
- [ ] **#58** (line 58-58) [tier ? / status deferred] per-feature peak concurrency
- [ ] **#59** (line 59-59) [tier ? / status deferred] per-feature retry rate
- [ ] **#60** (line 60-60) [tier ? / status deferred] per-feature p95 regression detection

## bucket: `horizontal-B` (1/10 shipped)

- [ ] **#61** (line 61-61) [tier ? / status deferred] tool-chain frequency 3-grams
- [x] **#62** (line 62-62) [tier 1 / status top-pick] hook-fire cascade detection — **kaizen-hook-cascade**
- [ ] **#63** (line 63-63) [tier ? / status deferred] cross-feature correlation matrix
- [ ] **#64** (line 64-64) [tier ? / status deferred] cross-feature data-flow path intersect
- [ ] **#65** (line 65-65) [tier ? / status deferred] tool-use burst Poisson-deviation
- [ ] **#66** (line 66-66) [tier ? / status deferred] skill activation graph co-load edges
- [ ] **#67** (line 67-67) [tier ? / status deferred] cross-session anomaly detection
- [ ] **#68** (line 68-68) [tier ? / status deferred] cohort comparison by session-mode
- [ ] **#69** (line 69-69) [tier ? / status deferred] cross-MCP routing waste detection
- [ ] **#70** (line 70-70) [tier ? / status deferred] feature usage decay curves

## bucket: `live-C` (1/10 shipped)

- [ ] **#71** (line 71-71) [tier ? / status deferred] live activity feed tail
- [ ] **#72** (line 72-72) [tier ? / status deferred] live token-budget meter
- [ ] **#73** (line 73-73) [tier ? / status deferred] live hook-latency rolling p50/p95
- [ ] **#74** (line 74-74) [tier ? / status deferred] live error stream
- [ ] **#75** (line 75-75) [tier ? / status deferred] live tool-call rate surge detection
- [ ] **#76** (line 76-76) [tier ? / status deferred] real-time skill-load tracking since last UserPromptSubmit
- [ ] **#77** (line 77-77) [tier ? / status deferred] live MCP queue depth
- [x] **#78** (line 78-78) [tier 1 / status top-pick] per-prompt event diff — **kaizen-prompt-event-diff**
- [ ] **#79** (line 79-79) [tier ? / status deferred] live concurrency map
- [ ] **#80** (line 80-80) [tier ? / status deferred] live hot-feature surface top-5

## bucket: `lifetime-D` (0/10 shipped)

- [ ] **#81** (line 81-81) [tier ? / status deferred] top-N most-fired hooks
- [ ] **#82** (line 82-82) [tier ? / status deferred] top-N most-called tools
- [ ] **#83** (line 83-83) [tier ? / status deferred] never-used features extended to bins/cmds
- [ ] **#84** (line 84-84) [tier ? / status deferred] feature half-life
- [ ] **#85** (line 85-85) [tier ? / status deferred] feature adoption curve time-to-first-N
- [ ] **#86** (line 86-86) [tier ? / status deferred] multi-session 3-motif mining
- [ ] **#87** (line 87-87) [tier ? / status deferred] most-touched files lifetime
- [ ] **#88** (line 88-88) [tier ? / status deferred] cross-project comparison
- [ ] **#89** (line 89-89) [tier ? / status deferred] lifetime cost estimation
- [ ] **#90** (line 90-90) [tier ? / status deferred] hook reliability over time

## bucket: `join-E` (1/10 shipped)

- [ ] **#91** (line 91-91) [tier ? / status deferred] trace + dxm union timeline
- [ ] **#92** (line 92-92) [tier 1 / status top-pick] trace + token-bloat causal weight
- [ ] **#93** (line 93-93) [tier ? / status deferred] dxm + coverage gaps (untested=touched more?)
- [ ] **#94** (line 94-94) [tier ? / status deferred] trace + handoff log preceding patterns
- [ ] **#95** (line 95-95) [tier ? / status deferred] dxm + intent rules per-rule hit rate
- [ ] **#96** (line 96-96) [tier ? / status deferred] trace + git history commit-to-activity
- [ ] **#97** (line 97-97) [tier ? / status deferred] dxm + session-mode tool-mix delta
- [ ] **#98** (line 98-98) [tier ? / status deferred] trace + memory writes feature contribution
- [ ] **#99** (line 99-99) [tier ? / status deferred] dxm + name-quality bad-named touched-more
- [x] **#100** (line 100-100) [tier ? / status shipped] trace + token-bloat per-session weighting — **trace + token-bloat per-session weighting**

## bucket: `session-F` (2/10 shipped)

- [x] **#101** (line 101-101) [tier 1 / status top-pick] turn-density events per UserPromptSubmit — **kaizen-turn-density**
- [x] **#102** (line 102-102) [tier 1 / status top-pick] prompt-rhythm time between prompts (stuck signal) — **kaizen-prompt-rhythm**
- [ ] **#103** (line 103-103) [tier ? / status deferred] tool-mix per turn (Edit/Bash/Read heavy)
- [ ] **#104** (line 104-104) [tier ? / status deferred] cost-per-turn token distribution
- [ ] **#105** (line 105-105) [tier ? / status deferred] conversation phase detection
- [ ] **#106** (line 106-106) [tier ? / status deferred] turn-to-commit ratio
- [ ] **#107** (line 107-107) [tier ? / status deferred] self-correction count Edit-retry on same file
- [ ] **#108** (line 108-108) [tier ? / status deferred] Read-then-Edit ratio (confidence proxy)
- [ ] **#109** (line 109-109) [tier ? / status deferred] skill-load density per turn
- [ ] **#110** (line 110-110) [tier ? / status deferred] end-of-turn shape (last-N before Stop)

## bucket: `feedback-G` (0/10 shipped)

- [ ] **#111** (line 111-111) [tier ? / status deferred] redirect detection (actually/wait/no)
- [ ] **#112** (line 112-112) [tier ? / status deferred] praise signal (perfect/great/nice)
- [ ] **#113** (line 113-113) [tier ? / status deferred] interruption events during in-flight tool
- [ ] **#114** (line 114-114) [tier ? / status deferred] question count (prompts ending ?)
- [ ] **#115** (line 115-115) [tier ? / status deferred] imperative vs reflective prompts
- [ ] **#116** (line 116-116) [tier ? / status deferred] prompt length distribution
- [ ] **#117** (line 117-117) [tier ? / status deferred] repeat-keyword unclear delivery signal
- [ ] **#118** (line 118-118) [tier ? / status deferred] acceptance latency (turns to yes go)
- [ ] **#119** (line 119-119) [tier ? / status deferred] roll-back signals (undo/revert/drop)
- [ ] **#120** (line 120-120) [tier ? / status deferred] user-extension signals (also do X)

## bucket: `subagent-H` (0/10 shipped)

- [ ] **#121** (line 121-121) [tier ? / status deferred] subagent dispatch rate
- [ ] **#122** (line 122-122) [tier ? / status deferred] subagent depth (nested layers)
- [ ] **#123** (line 123-123) [tier ? / status deferred] subagent cost vs quality
- [ ] **#124** (line 124-124) [tier ? / status deferred] subagent isolation audit
- [ ] **#125** (line 125-125) [tier ? / status deferred] subagent overlap (same task twice)
- [ ] **#126** (line 126-126) [tier ? / status deferred] subagent completion rate
- [ ] **#127** (line 127-127) [tier ? / status deferred] subagent type-usage distribution
- [ ] **#128** (line 128-128) [tier ? / status deferred] parent-subagent context transfer cost
- [ ] **#129** (line 129-129) [tier ? / status deferred] SubagentStop next-event pattern
- [ ] **#130** (line 130-130) [tier ? / status deferred] subagent vs in-process tradeoff

## bucket: `longitudinal-I` (0/10 shipped)

- [ ] **#131** (line 131-131) [tier ? / status deferred] returning-user signals
- [ ] **#132** (line 132-132) [tier ? / status deferred] session-mode evolution
- [ ] **#133** (line 133-133) [tier ? / status deferred] skill drift load-count over time
- [ ] **#134** (line 134-134) [tier ? / status deferred] bin-adoption curve
- [ ] **#135** (line 135-135) [tier ? / status deferred] feature-deprecation candidates no-fire N sessions
- [ ] **#136** (line 136-136) [tier ? / status deferred] pattern memorisation fix repeat
- [ ] **#137** (line 137-137) [tier ? / status deferred] memory recall rate
- [ ] **#138** (line 138-138) [tier ? / status deferred] persona top-belief utilization
- [ ] **#139** (line 139-139) [tier ? / status deferred] handoff effectiveness resume vs cold-start
- [ ] **#140** (line 140-140) [tier ? / status deferred] brain growth rate notes/persona deltas

## bucket: `failure-J` (1/10 shipped)

- [x] **#141** (line 141-141) [tier 1 / status top-pick] silent-fail detection hook-returned-empty — **kaizen-silent-fail**
- [ ] **#142** (line 142-142) [tier ? / status deferred] empty-tool-result tracking
- [ ] **#143** (line 143-143) [tier ? / status deferred] tool-error catalog top-N
- [ ] **#144** (line 144-144) [tier ? / status deferred] iron-law violation introduction rate
- [ ] **#145** (line 145-145) [tier ? / status deferred] test-flake detection intermittent
- [ ] **#146** (line 146-146) [tier ? / status deferred] commit-revert rate
- [ ] **#147** (line 147-147) [tier ? / status deferred] plan-deviation rate
- [ ] **#148** (line 148-148) [tier ? / status deferred] Stop-hook block rate
- [ ] **#149** (line 149-149) [tier ? / status deferred] permission-prompt frequency catalog
- [ ] **#150** (line 150-150) [tier ? / status deferred] cache-hit rate (skill/context)

## bucket: `substrate-K` (0/10 shipped)

- [ ] **#151** (line 151-151) [tier 1 / status top-pick] append-to universal pattern across emitters
- [ ] **#152** (line 152-152) [tier ? / status deferred] generic kaizen-stream <source> append-to <target>
- [ ] **#153** (line 153-153) [tier 1 / status top-pick] stream join CLI trace+dxm on session_id
- [ ] **#154** (line 154-154) [tier ? / status deferred] stream pipe trace|bloat correlate
- [ ] **#155** (line 155-155) [tier ? / status deferred] uniform window flags across emitters
- [ ] **#156** (line 156-156) [tier ? / status deferred] format adapters md/jsonl/csv/human
- [ ] **#157** (line 157-157) [tier ? / status deferred] --where filter DSL
- [ ] **#158** (line 158-158) [tier ? / status deferred] stream tee fan-out
- [ ] **#159** (line 159-159) [tier ? / status deferred] --follow tail-and-follow live
- [ ] **#160** (line 160-160) [tier ? / status deferred] --max-rate backpressure

## bucket: `axis-as-query-L` (0/10 shipped)

- [ ] **#161** (line 161-161) [tier 1 / status top-pick] axis-as-yaml + generic runner
- [ ] **#162** (line 162-162) [tier ? / status deferred] coverage delta N-th vs latest
- [ ] **#163** (line 163-163) [tier ? / status deferred] trend sparkline per axis
- [ ] **#164** (line 164-164) [tier ? / status deferred] auto-promote stable axis lower frequency
- [ ] **#165** (line 165-165) [tier ? / status deferred] auto-fire spike additionalContext
- [ ] **#166** (line 166-166) [tier ? / status deferred] coverage event stream <axis>.scanned
- [ ] **#167** (line 167-167) [tier ? / status deferred] coverage rubric yaml-driven scoring
- [ ] **#168** (line 168-168) [tier ? / status deferred] per-axis token budget
- [ ] **#169** (line 169-169) [tier ? / status deferred] debt curve accumulate vs pay-down
- [ ] **#170** (line 170-170) [tier ? / status deferred] cross-axis correlation matrix

## bucket: `radical-M` (0/10 shipped)

- [ ] **#171** (line 171-171) [tier ? / status radical] findings ARE events not files
- [ ] **#172** (line 172-172) [tier ? / status radical] plans ARE event projections
- [ ] **#173** (line 173-173) [tier ? / status radical] CHANGELOG IS a trace projection
- [ ] **#174** (line 174-174) [tier ? / status radical] backlog IS a query of .candidate events
- [ ] **#175** (line 175-175) [tier ? / status radical] tests ARE replayed event sequences
- [ ] **#176** (line 176-176) [tier ? / status radical] handoff IS a stream snapshot
- [ ] **#177** (line 177-177) [tier ? / status radical] persona IS a slow aggregation
- [ ] **#178** (line 178-178) [tier ? / status radical] audit reports ARE stream filters
- [ ] **#179** (line 179-179) [tier ? / status radical] architecture-log IS commit-event projection
- [ ] **#180** (line 180-180) [tier ? / status radical] skill suggestions ARE intent-event matches

## bucket: `mining-N` (0/10 shipped)

- [ ] **#181** (line 181-181) [tier ? / status research] frequent-itemset Apriori on tool 3-grams
- [ ] **#182** (line 182-182) [tier ? / status research] z-score anomaly per tool
- [ ] **#183** (line 183-183) [tier ? / status research] Markov-chain tool transitions
- [ ] **#184** (line 184-184) [tier ? / status research] session clustering by tool-mix vector
- [ ] **#185** (line 185-185) [tier ? / status research] hot-edit co-change pairs
- [ ] **#186** (line 186-186) [tier ? / status research] sequence-to-feature inference
- [ ] **#187** (line 187-187) [tier ? / status research] outlier-feature event signature
- [ ] **#188** (line 188-188) [tier ? / status research] causal-inference graph A->B
- [ ] **#189** (line 189-189) [tier ? / status research] bottleneck detection longest p95 gap
- [ ] **#190** (line 190-190) [tier ? / status research] goldilocks zone per session-mode

## bucket: `self-O` (0/10 shipped)

- [ ] **#191** (line 191-191) [tier ? / status long-arc] auto-deprecate never-fired K weeks
- [ ] **#192** (line 192-192) [tier ? / status long-arc] auto-promote ad-hoc patterns to skill
- [ ] **#193** (line 193-193) [tier ? / status long-arc] auto-rebalance allocate next iteration
- [ ] **#194** (line 194-194) [tier ? / status long-arc] auto-budget predict session spend
- [ ] **#195** (line 195-195) [tier ? / status long-arc] auto-handoff cause-of-death log
- [ ] **#196** (line 196-196) [tier ? / status long-arc] auto-coverage-axis from repeating bugs
- [ ] **#197** (line 197-197) [tier ? / status long-arc] auto-skill-suggest from phrase-load pairs
- [ ] **#198** (line 198-198) [tier ? / status long-arc] auto-intent-rule from phrase clusters
- [ ] **#199** (line 199-199) [tier ? / status long-arc] auto-rubric from frequent decisions
- [ ] **#200** (line 200-200) [tier ? / status long-arc] auto-test from known-good replay

## bucket: `sql-P` (1/15 shipped)

- [x] **#201** (line 201-201) [tier 1 / status top-pick] kaizen-sql DuckDB wrapper over JSONL — **kaizen-sql**
- [ ] **#202** (line 202-202) [tier ? / status deferred] pre-built views latest_session / tool_calls_today
- [ ] **#203** (line 203-203) [tier ? / status deferred] JSONL-as-table for trace/dxm/bloat history
- [ ] **#204** (line 204-204) [tier ? / status deferred] cross-stream JOIN via SQL
- [ ] **#205** (line 205-205) [tier ? / status deferred] window-function cumulative cost
- [ ] **#206** (line 206-206) [tier ? / status deferred] CTE multi-stage reports
- [ ] **#207** (line 207-207) [tier ? / status deferred] materialised views slow queries
- [ ] **#208** (line 208-208) [tier ? / status deferred] SQL-driven coverage axes
- [ ] **#209** (line 209-209) [tier ? / status deferred] time_bucket hourly daily rollups
- [ ] **#210** (line 210-210) [tier ? / status deferred] approx_quantile p95 dashboards
- [ ] **#211** (line 211-211) [tier ? / status deferred] EXPLAIN auto for slow queries
- [ ] **#212** (line 212-212) [tier ? / status deferred] kaizen-sql shell REPL
- [ ] **#213** (line 213-213) [tier ? / status deferred] SQL to markdown report renderer
- [ ] **#214** (line 214-214) [tier ? / status deferred] per-session VIEW snapshot
- [ ] **#215** (line 215-215) [tier ? / status deferred] Parquet long-term archive COPY

## bucket: `radon-Q` (1/15 shipped)

- [x] **#216** (line 216-216) [tier 1 / status top-pick] kaizen-complexity cyclomatic via radon cc — **kaizen-complexity**
- [ ] **#217** (line 217-217) [tier ? / status deferred] MI per file via radon mi
- [ ] **#218** (line 218-218) [tier ? / status deferred] Halstead volume/effort
- [ ] **#219** (line 219-219) [tier ? / status deferred] CC SUB_GATE advisory
- [ ] **#220** (line 220-220) [tier ? / status deferred] CC trend over time
- [ ] **#221** (line 221-221) [tier ? / status deferred] CC vs test-coverage correlation
- [ ] **#222** (line 222-222) [tier ? / status deferred] CC vs bloat correlation
- [ ] **#223** (line 223-223) [tier ? / status deferred] per-feature CC budget
- [ ] **#224** (line 224-224) [tier ? / status deferred] function-length histogram
- [ ] **#225** (line 225-225) [tier ? / status deferred] LCOM class cohesion
- [ ] **#226** (line 226-226) [tier ? / status deferred] import-fanout dep complexity
- [ ] **#227** (line 227-227) [tier ? / status deferred] PR CC gate
- [ ] **#228** (line 228-228) [tier ? / status deferred] big-bang refactor candidates top-N
- [ ] **#229** (line 229-229) [tier ? / status deferred] dead-complexity radon+vulture+trace
- [ ] **#230** (line 230-230) [tier ? / status deferred] hotspot CC times churn

## bucket: `viz-R` (0/15 shipped)

- [ ] **#231** (line 231-231) [tier ? / status deferred] statusline live cost + bloat
- [ ] **#232** (line 232-232) [tier ? / status deferred] ASCII sparkline trends
- [ ] **#233** (line 233-233) [tier ? / status deferred] Sankey diagram tool-chain
- [ ] **#234** (line 234-234) [tier ? / status deferred] heatmap PNG hour x day x tool
- [ ] **#235** (line 235-235) [tier ? / status deferred] timeline graph per session
- [ ] **#236** (line 236-236) [tier ? / status deferred] Mermaid from rubric YAML
- [ ] **#237** (line 237-237) [tier ? / status deferred] colour terminal tables rich/tabulate
- [ ] **#238** (line 238-238) [tier ? / status deferred] HTML report bundle build
- [ ] **#239** (line 239-239) [tier ? / status deferred] live dashboard server
- [ ] **#240** (line 240-240) [tier ? / status deferred] visual snapshot diff
- [ ] **#241** (line 241-241) [tier ? / status deferred] file-touch frequency heatmap
- [ ] **#242** (line 242-242) [tier ? / status deferred] skill-load co-occurrence graphviz
- [ ] **#243** (line 243-243) [tier ? / status deferred] cost-gauge glyph statusline
- [ ] **#244** (line 244-244) [tier ? / status deferred] per-prompt cost mini-table
- [ ] **#245** (line 245-245) [tier ? / status deferred] end-of-session card

## bucket: `ci-S` (0/15 shipped)

- [ ] **#246** (line 246-246) [tier ? / status deferred] GH Actions kaizen gatekeeper annotations
- [ ] **#247** (line 247-247) [tier ? / status deferred] pre-commit framework integration
- [ ] **#248** (line 248-248) [tier ? / status deferred] PR coverage-delta comment bot
- [ ] **#249** (line 249-249) [tier ? / status deferred] auto-label PRs by feature changed
- [ ] **#250** (line 250-250) [tier ? / status deferred] kaizen-bench latency baselines
- [ ] **#251** (line 251-251) [tier ? / status deferred] failure-replay artifact upload
- [ ] **#252** (line 252-252) [tier ? / status deferred] PR token-bloat report comment
- [ ] **#253** (line 253-253) [tier ? / status deferred] snapshot-diff bot for plan files
- [ ] **#254** (line 254-254) [tier ? / status deferred] branch protection red-gate blocks
- [ ] **#255** (line 255-255) [tier ? / status deferred] dependabot equivalent for vendored skills
- [ ] **#256** (line 256-256) [tier ? / status deferred] auto-publish to marketplace on tag
- [ ] **#257** (line 257-257) [tier ? / status deferred] release-notes generator
- [ ] **#258** (line 258-258) [tier ? / status deferred] CI hook health-check
- [ ] **#259** (line 259-259) [tier ? / status deferred] CI MCP smoke-test
- [ ] **#260** (line 260-260) [tier ? / status deferred] cross-OS matrix linux/mac/win

## bucket: `multiuser-T` (0/15 shipped)

- [ ] **#261** (line 261-261) [tier ? / status deferred] per-user session-mode prefs
- [ ] **#262** (line 262-262) [tier ? / status deferred] shared team brain overlays
- [ ] **#263** (line 263-263) [tier ? / status deferred] pair-coding session linking
- [ ] **#264** (line 264-264) [tier ? / status deferred] code-review handoff
- [ ] **#265** (line 265-265) [tier ? / status deferred] conflict detection kaizen.toml
- [ ] **#266** (line 266-266) [tier ? / status deferred] team-wide axis pinning
- [ ] **#267** (line 267-267) [tier ? / status deferred] per-user inbox routing
- [ ] **#268** (line 268-268) [tier ? / status deferred] per-user audit log
- [ ] **#269** (line 269-269) [tier ? / status deferred] perm-grant approval workflow
- [ ] **#270** (line 270-270) [tier ? / status deferred] cross-user backlog
- [ ] **#271** (line 271-271) [tier ? / status deferred] shared metric dashboards
- [ ] **#272** (line 272-272) [tier ? / status deferred] per-user iron-law overrides
- [ ] **#273** (line 273-273) [tier ? / status deferred] mentor/junior roles
- [ ] **#274** (line 274-274) [tier ? / status deferred] brain-export knowledge handoff
- [ ] **#275** (line 275-275) [tier ? / status deferred] team retrospective generator

## bucket: `privacy-U` (0/15 shipped)

- [ ] **#276** (line 276-276) [tier ? / status deferred] auto-redact secrets in trace events
- [ ] **#277** (line 277-277) [tier ? / status deferred] per-event PII tagger
- [ ] **#278** (line 278-278) [tier ? / status deferred] redaction profile per surface
- [ ] **#279** (line 279-279) [tier ? / status deferred] network-egress trace
- [ ] **#280** (line 280-280) [tier ? / status deferred] SBOM-style MCP reach audit
- [ ] **#281** (line 281-281) [tier ? / status deferred] hash-only event storage
- [ ] **#282** (line 282-282) [tier ? / status deferred] local-only mode block network MCPs
- [ ] **#283** (line 283-283) [tier ? / status deferred] time-limited brain notes auto-expire
- [ ] **#284** (line 284-284) [tier ? / status deferred] per-skill data classification
- [ ] **#285** (line 285-285) [tier ? / status deferred] encrypted trace storage option
- [ ] **#286** (line 286-286) [tier ? / status deferred] audit-log hash-chain immutability
- [ ] **#287** (line 287-287) [tier ? / status deferred] sandbox profile per untrusted skill
- [ ] **#288** (line 288-288) [tier ? / status deferred] network-egress allowlist
- [ ] **#289** (line 289-289) [tier ? / status deferred] memory cleanse on logout
- [ ] **#290** (line 290-290) [tier ? / status deferred] per-project data residency boundaries

## bucket: `cost-V` (0/10 shipped)

- [ ] **#291** (line 291-291) [tier ? / status deferred] per-tool token cost coefficient table
- [ ] **#292** (line 292-292) [tier ? / status deferred] per-session USD estimate via pricing
- [ ] **#293** (line 293-293) [tier ? / status deferred] burn-rate alert tokens/min
- [ ] **#294** (line 294-294) [tier ? / status deferred] cost forecast from rolling rate
- [ ] **#295** (line 295-295) [tier ? / status deferred] most-expensive tool calls top-N
- [ ] **#296** (line 296-296) [tier ? / status deferred] per-feature cost attribution
- [ ] **#297** (line 297-297) [tier ? / status deferred] cost-vs-value heatmap
- [ ] **#298** (line 298-298) [tier ? / status deferred] per-month cost rollup
- [ ] **#299** (line 299-299) [tier ? / status deferred] cost-regression detector vs lifetime
- [ ] **#300** (line 300-300) [tier ? / status deferred] compact suggestion when over threshold

