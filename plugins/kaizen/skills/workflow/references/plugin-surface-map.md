# Plugin surface map — entry/exit paths

Every place where data enters or leaves the kaizen plugin, with the
flow-coverage status. Goal: every meaningful pipeline is a Node+Flow
graph (see `node-flow.md` for the primitives).

## Entry points (data → plugin)

| Surface | Count | Examples | Node+Flow status |
|---|---|---|---|
| Slash commands | 40 | `kaizen-onboard`, `kaizen-knowledge`, `/kaizen:search`, `kaizen-scrape` | command files are thin shells; the pipelines they invoke ARE the flow targets |
| MCP tool calls | 9 servers × ~5–10 tools each | `onboard_search`, `knowledge_search`, `workflow_advance` | servers wrap `do_*` helpers; Node+Flow lives one layer below |
| Hook events | 10 | PreToolUse, PostToolUse, UserPromptSubmit, Stop, SubagentStop, … | hook handlers are imperative shell/Python; flow ceremony adds no value |
| Pre-commit gate | 1 | `pre-commit.sh` iterating `domain/git-discipline.yaml::pre_commit_gates` | already declarative (yaml-driven); flow shape would be redundant |
| Indexers (filesystem → SQLite) | 5 | onboard, knowledge, scrape, trace, claude_docs | **canonical IndexFlow target** — onboard wrapped (`IndexFlow`); others share the same shape |

## Internal pipelines (plugin-internal data flow)

| Pipeline | Where | Node+Flow status |
|---|---|---|
| Search (query → ranked results) | `search_flow.py` (onboard) | ✅ `SearchFlow` (5 nodes) |
| Index (filesystem → embedded chunks) | `onboard_index.do_index` + `index_flow.py` | ✅ `IndexFlow` (5 nodes) |
| Docs gen (workspace → docs/crates/*.md) | `docs_gen.cmd_scan` + `docs_flow.py` | ✅ `DocsFlow` (4 nodes, with asyncio.gather fan-out) |
| Scrape (URLs → semantic store) | `scrape_index.py` | ⚠️ vendored inline AsyncNode; should migrate to `flow.py` primitives |
| Knowledge index (brain notes → SQLite) | `knowledge_index.py` | ⚠️ same do_dump/do_filter shape as onboard; not yet flow-wrapped |
| Trace index (event log → SQLite) | `trace_index.py` | ⚠️ similar shape; not yet flow-wrapped |
| Claude-docs index (markdown mirror → SQLite) | `claude_docs_index.py` | ⚠️ similar shape; not yet flow-wrapped |
| Workflow state machine | `workflow.sh` + yaml | ☑️ state-machine shape; shell, not Python; ceremony to flow-wrap |

## Exit points (plugin → out)

| Surface | Examples | Notes |
|---|---|---|
| stdout / stderr | CLI tools, slash commands | each terminal node writes via `print()` or returns dict for JSON serialization |
| SQLite writes | onboard.db, knowledge.db, scrape.db, trace.db, claude-docs.db | per-indexer; terminal node in each IndexFlow does the write |
| JSONL / Markdown writes | `docs/crates/*.{md,json}`, `.kaizen/workflow/*.{md,json}`, audit reports | terminal nodes in DocsFlow / ReportFlow |
| MCP tool responses | dict returns from `@mcp.tool()` handlers | servers wrap `do_*`; flow shape is one layer deeper |
| External HTTP | llama-server `/v1/embeddings`, ollama, scrape targets | hidden inside `_embed.py` + scrape_index nodes |
| Process side effects | `git add`, `git mv` (in pre-commit handlers + install scripts) | NOT pipeline material — direct subprocess |

## Coverage scorecard (v1.31.0+)

- **Search**: ✅ wrapped (`search_flow.py`)
- **Index**: ✅ wrapped (`index_flow.py`)
- **Docs gen**: ✅ wrapped (`docs_flow.py`)
- **Scrape**: ⚠️ vendored inline AsyncNode — should converge on `flow.py` primitives
- **Knowledge / Trace / Claude-docs indexers**: ⚠️ same shape as onboard; not yet wrapped but `IndexFlow` is parameterizable
- **Slash commands / MCP servers / hooks**: ☑️ thin shells over the wrapped pipelines; Node+Flow at this layer would be ceremony

## Why not wrap *everything*?

Node+Flow is a *useful* shape for multi-stage data pipelines with
internal state and explicit transitions. Wrapping a one-line MCP tool
handler or a 5-line shell hook adds ceremony without benefit. The
heuristic: if there are ≥3 sequential stages with shared state, it's
a flow candidate. Otherwise, leave it imperative.

The four wrapped pipelines (search, index, docs, the reference
example in `flow.py`) all clear the bar. The scrape pipeline already
has 5 internal nodes — it should move to the canonical `flow.py`
primitive when the scrape work next gets touched.
