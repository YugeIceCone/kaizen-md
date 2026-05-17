---
created: 2026-05-12
updated: 2026-05-12
type: belief
confidence: 0.95
tags: [preference, discipline, onion, tdd, schema-driven, reproducibility]
sources_count: 1
freshness: stable
kaizen:
  rule_type: discipline
  trigger_match:
    - "implement"
    - "refactor"
    - "add feature"
    - "fix bug"
    - "code task"
  schema: onion-tdd-strict
  schema_path: ~/.claude/.kaizen/schemas/onion-tdd-strict/schema.yaml
---

# Deterministic code-task discipline: onion-tdd-strict

User wants predictable, consistent, reproducible code outputs. Every
code task — net-new feature, refactor, bug fix — applies the same
discipline schema in the same order, with the same gates, producing
the same artifact shape.

## The discipline (9 stages, each gated)

1. **audit** — find existing patterns; identify target layer
2. **design-layers** — split into Domain / Application / Infrastructure / Presentation
3. **red-test** — write failing unit tests on the Domain layer FIRST
4. **green-impl** — minimal Domain code; pure functions only
5. **refactor** — DRY / KISS / SoC sweep; no behaviour change
6. **adapters** — Protocol ports + concrete impls for I/O
7. **composition** — PocketFlow Flow wiring Domain + Adapters
8. **supervisor** — cookbook quality gate per pocketflow-supervisor
9. **trace-wire** — every node phase emits structured trace event
10. **verify** — tests pass, smoke green, audit delta clean

Each stage has a machine-checkable gate. Gate failure blocks advancement
to the next stage. Full schema at
`~/.claude/.kaizen/schemas/onion-tdd-strict/schema.yaml`.

## Invariants enforced across all stages

- **Layer purity:** Domain imports zero infra (`urllib`, `sqlite3`,
  `os.environ`, file I/O). Adapters contain no business logic.
- **Testability:** Every public Domain function has at least one unit test.
  Tests run from a clean process; no shared mutable state.
- **Config resolution:** No module-level env reads. Resolver functions
  called per request. Backends through `_kaizen_shared.resolve_*_backend()`.
- **Trace discipline:** Every Node phase emits an event. Names follow
  `<subject>.<action>` convention. Trace path resolved per call.
- **Schema discipline:** Any new persisted shape declares `schema_version`
  meta. Per-row dim / dtype tracked. Migrations idempotent.
- **LLM output shape:** Any structured LLM output uses
  `response_format=json_schema` with `strict=true` — grammar-constrained
  generation, not regex parsing. Model-specific quirks live in
  `_model_cards.py`; code dispatches off the card, never on hardcoded
  model names. Assistant messages preceding `role:tool` results use
  canonical openai `tool_calls` shape (rewrite if model returned raw JSON).
  Defensive `card.clean_response()` on every outgoing message.

## Cookbook pattern references (PocketFlow)

Apply when relevant — these are the canonical shapes:

- **Supervisor** — validate + route to heal (cookbook/pocketflow-supervisor)
- **Self-healing** — detector + writer loop (cookbook/pocketflow-self-healing-mermaid)
- **Parallel batch** — AsyncParallelBatchNode (cookbook/pocketflow-parallel-batch)
- **Streaming** — SSE parse for TTFT split (cookbook/pocketflow-llm-streaming)
- **Agentic RAG** — tool-loop with decide/run/answer (cookbook/pocketflow-agentic-rag)
- **Visualization** — mermaid from Flow (cookbook/pocketflow-visualization)

## How to apply

When the user starts a code task matching the triggers above:

1. **Invoke the schema explicitly**:
   `/workflow schema=onion-tdd-strict prompt="<task>"`
2. **OR drive the schema manually**: read the schema, work each artifact
   in order, run the gate command, advance only on green.
3. **Pair with required skill chain**:
   - `onion-ddd-theory` (background)
   - `coding-skills:*` (DRY / KISS / SoC / SOLID / LoD / YAGNI / Boy-Scout / Convention)
   - `tdd` (red → green → refactor)
4. **Surface deviations.** If a stage gate can't be met, stop and ask
   before bypassing. The whole point is predictability.

## Reference implementation (this session)

Session: 2026-05-12. Feature: chunked HTTP embedding pipeline that works
around nomic-embed-text-v2's 512-token context limit.

Files produced (this is what the discipline output looks like):

- `~/.claude/.kaizen/scripts/_chunking.py` (183 LOC) — pure Domain
- `~/.claude/.kaizen/scripts/test__chunking.py` (249 LOC, 34 tests)
- `~/.claude/.kaizen/scripts/_kaizen_shared.py` (114 LOC) — DRY helpers
- `~/.claude/.kaizen/scripts/_adapters.py` (220 LOC) — HttpTransport, OnboardRepository
- `~/.claude/.kaizen/scripts/_pocketflow.py` (105 LOC) — vendored upstream
- `~/.claude/.kaizen/scripts/embed_chunked.py` (1019 LOC) — composition + CLI

Verification: 34/34 unit tests pass, 1017-row reindex in 4.3 sec, all
phases traced, supervisor reports zero degenerate rows.

## Why

User explicitly requested predictability + reproducibility: "need
predictable, consistent and reproducible code output with schemas.
example for this session would be applying onion-ddd + tdd + unit
tests on any code task" (2026-05-12).

Pattern across multiple audit iterations this session: the user
repeatedly invoked `/kaizen:audit`, identified gaps, and demanded
remediation. The audit gaps were always the same family: missing
tests, layer violations, schema drift, trace gaps. Codifying the
discipline schema ends the audit-fix-audit-fix loop — the schema
forecloses those gaps at the source.

## Evidence

- source: session 2026-05-12 audit iterations
  quote: "tracing + full async hooks claude code cli chat"
  quote: "tech debt schema coverage onion-ddd coding-skills"
  quote: "production ready, code quality, fully wired, pocketflow wireframe, complete node wire for tracing every layer including local llm"
  quote: "need predictable, consistent and reproducible code output with schemas"
  date: 2026-05-12
- source: ~/.claude/.kaizen/scripts/embed_chunked.py + _chunking.py + _adapters.py + test__chunking.py
  quote: "(reference implementation — 34 tests passing, layered, traced, supervised)"
  date: 2026-05-12
