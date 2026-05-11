---
name: flow
description: Run the pocketflow Node+Flow demo against the current backlog. 3-node pipeline (ReadBacklog → Analyze → Report) demonstrates the Node/Flow discipline (single-responsibility, prep/exec/post phases, shared store) over a real artifact.
---

# kaizen flow demo

Demonstrates the **Node + Flow discipline** (single-responsibility steps, `prep` / `exec` / `post` phases, shared store between nodes) using the project's own backlog as input. Pure offline — no LLM calls.

Run:

!`python3 ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/flow_demo.py`

## The Flow

```
ReadBacklogNode  →  AnalyzeNode  →  ReportNode
```

| Node | Responsibility |
|---|---|
| **ReadBacklogNode** | `prep`: resolve `backlog.json` path. `exec`: parse JSON. `post`: store data in shared. |
| **AnalyzeNode** | `prep`: pull data. `exec`: count items per section + tag, identify items missing probe/verify. `post`: store analysis. |
| **ReportNode** | `prep`: pull analysis. `exec`: format as human-readable text. `post`: store report. |

The Flow itself is wired with `>>`:

```python
read >> analyze >> report
flow = Flow(start=read)
flow.run({"backlog_path": path})
```

## Why this pattern?

Every LLM-driven feature in the shodan workspace (and any project following the bundled `onion-ddd-workflow` skill) MUST decompose into:

1. **Node impls** — each discrete step is a `Node` with one responsibility
2. **A Flow** — composes the nodes, defines transitions
3. **Explicit state machine** — shared store carries data; no hidden globals

The demo is the simplest possible instance: 3 nodes, no LLM, no branching. Real Modes (chat, plan, agent) add branching and LlmClient nodes, but follow the same skeleton.

## Install once

```bash
pip install --user --break-system-packages pocketflow
```

(Or via pipx / a virtualenv if you prefer isolated installs.)

## Sample output

```
Backlog analysis (pocketflow Flow demo)
========================================
Total items:       8
  in_flight:       0
  next_up:         5
  done:            0
  parked:          3
Decisions:         6

Top 5 tags:
  observability        7
  bus                  2
  lsp                  1
  ...

Discipline gaps:
  items missing probe field:   0
  items missing verify field:  0
```

The "Discipline gaps" line is the load-bearing metric — items missing `probe` or `verify` fields are unsized work, breaking the sizing rule.
