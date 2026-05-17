# Envelope retrofit inventory + roadmap

**Last regenerated**: 2026-05-17 (auto-generatable via the script at the bottom of this file).

Tracks which kaizen tools emit the canonical tool-output envelope (`assets/schemas/tool-output.schema.json`) and which don't yet. Continuous reference for the "programmable + reproducible + consistent output" effort.

## Status legend

- **✅ emit** — emits canonical envelope via `_envelope.emit()` / `_envelope.emitter()`
- **🔄 retrofit-pending** — has `--json` flag; emits bare JSON; needs envelope wrap (mechanical, ~5 LOC per tool)
- **🟡 needs-json-flag** — has CLI `main()` but no `--json` flag; needs flag wiring first (medium effort)
- **🔵 no-cli** — file is a library / supports no command-line entry (no retrofit needed)
- **n/a (helper)** — `_*.py` underscore-prefixed; imported module, not CLI
- **mcp** — `*_mcp.py` MCP server; uses MCP protocol envelope (separate concern)
- **shell** — `.sh` script; separate retrofit story (some emit JSON via `python3 -c` shims)

## Summary

| Status | Count | Notes |
|---|---|---|
| ✅ emit | 5 | gatekeeper, surface, iron_laws, metrics, roadmap_status |
| 🔄 retrofit-pending | 26 | one commit's worth of mechanical work each |
| 🟡 needs-json-flag | 17 | needs --json wiring before envelope wrap |
| 🔵 no-cli | 35 | most are _-prefixed helpers (n/a) |
| mcp | 22 | separate envelope story (MCP protocol output) |
| shell | 27 | separate story (.sh) |
| **Total CLI Python** | **55** | (excluding helpers + mcp + shell) |

**Envelope coverage**: 5 / (55 − 17 needs-json-flag) = **5/38 = 13.2%** of "has --json flag" tools.

After retrofitting the 26 pending: **31/38 = 81.6%** coverage. The remaining 17 need flag wiring before they can join.

## Tools by category (this doc replaces the prior tribal-knowledge "what's done where")

### ✅ Emit canonical envelope (5)

| Tool | Path | Commit landed |
|---|---|---|
| `gatekeeper` | `skills/workflow/scripts/gatekeeper.py` | `71a5ac3` |
| `surface` | `skills/workflow/scripts/surface.py` | `71a5ac3` |
| `iron_laws` | `skills/workflow/scripts/iron_laws.py` | `71a5ac3` |
| `metrics` | `skills/workflow/scripts/metrics.py` | `2f6a531` |
| `roadmap_status` | `skills/workflow/scripts/roadmap_status.py` | `2f6a531` |

### 🔄 Retrofit-pending (26 — has `--json`, needs envelope wrap)

Ordered by estimated agent traffic (highest first — best ROI per retrofit).

#### High traffic (search + observability — agents call these constantly)

| Tool | LOC | Notes |
|---|---|---|
| `trace.py` | 437 | trace event writer/reader; agents read trace logs |
| `claude_docs_index.py` | 537 | claude.ai docs semantic search |
| `search_flow.py` | 485 | search orchestrator (multi-tool dispatcher) |
| `loc_index.py` | 1490 | code-loc semantic index |
| `onboard_index.py` | 1797 | per-repo onboarding index |

#### Medium traffic (audit + brain — periodic but valuable)

| Tool | LOC | Notes |
|---|---|---|
| `brain_audit.py` | 433 | end-of-session brain audit |
| `brain_evolve.py` | 337 | brain consolidation flow |
| `brain_promote.py` | 367 | project-memory → brain promotion |
| `self_audit.py` | 696 | plugin self-audit |
| `self_audit_agent.py` | 672 | agent-driven self-audit |
| `validate.py` | 521 | plugin-development feature validator |
| `hygiene.py` | 414 | repo hygiene checks |

#### Low traffic (specialist tools)

| Tool | LOC | Notes |
|---|---|---|
| `karpathy/scripts/*.py` (4) | ~250 each | complexity_checker, diff_surgeon, assumption_linter, goal_verifier |
| `config.py` | 344 | config inspection / .kaizen.toml access |
| `docs_flow.py` | 298 | per-package doc generation orchestrator |
| `drift_cli.py` | 144 | drift detection CLI |
| `handoff.py` | 210 | handoff CLI |
| `index_flow.py` | 278 | indexer orchestrator |
| `loop_state.py` | 606 | loop state machine |
| `manifests_cli.py` | 93 | manifests CLI |
| `models.py` | 633 | model management |
| `observe.py` | 745 | unified observability across 6 data-stream layers |
| `scrape_index.py` | 1081 | scrape → semantic index pipeline |

### 🟡 Needs `--json` flag wired first (17)

Add `--json` to argparse, then envelope-wrap.

| Tool | LOC | Why no `--json` today |
|---|---|---|
| `backlog.py` | 346 | Text-only CLI; many subcommands, each needs flag |
| `brain.py` | 578 | Schema-driven brain CLI; large surface |
| `brain_index.py` | 634 | Brain semantic index |
| `cache.py` | 177 | Cache CRUD; small surface |
| `context.py` | 120 | Context-window state reporter |
| `daemon.py` | 854 | Daemon control (mostly side-effects, but `status` would benefit) |
| `docs_gen.py` | 1142 | Doc generator |
| `export_target.py` | 515 | Bundle export to sibling AI-CLIs |
| `flow.py` | 643 | Async Node+Flow demo |
| `inbox.py` | 347 | Message inbox CLI |
| `knowledge_index.py` | 746 | Knowledge semantic index |
| `llm_proxy.py` | 344 | LLM trace proxy control |
| `loop_ledger.py` | 459 | Loop ledger CRUD |
| `rules.py` | 391 | Brain-sourced rule lookup |
| `shim.py` | 425 | Bin-symlink resolution |
| `trace_index.py` | 525 | Trace event index builder |
| `workflow_runner.py` | 500 | Workflow state machine runner |

### MCP servers (22 — separate envelope story)

The MCP protocol has its own response envelope. Currently tools like `gatekeeper_mcp.py` wrap the underlying CLI script (`gatekeeper.py`) and re-emit; if the CLI emits canonical envelope, the MCP wrapper passes it through.

**Future work**: define an MCP-to-canonical-envelope adapter so MCP responses ALSO carry the kaizen envelope shape. Not blocking; agents calling MCP tools already get structured returns natively.

### Shell scripts (27 — separate retrofit story)

Most are install/setup scripts (`setup.sh`, `enable_all.sh`, etc.) — they emit human-readable progress lines. A few produce structured output (`audit.sh` has `--json`). Those would be retrofitted via a `python3 -c "$(cat <<PY ... PY)"` shim that uses `_envelope.emit()`. Lower priority — agents don't typically pipe shell-script JSON.

## Retrofit pattern (canonical)

The minimum work per tool with an existing `--json` flag:

```python
# 1. Add the import + emitter at module top
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _envelope
_emit = _envelope.emitter("kaizen-mytool", tool_version="1.0.0")

# 2. In each --json branch:
if args.json:
    _emit(data, verdict=verdict_or_none, counts=counts_or_none)
    return 0
else:
    print(text_render(...))

# 3. Append to _RETROFIT_TOOLS in tests/test_envelope.py:
("mytool",  [str(_SCRIPTS / "mytool.py"), "subcmd", "--json"]),
```

## Roadmap (priority order)

Rough effort estimate: **~1 commit per 3-5 retrofits** (mechanical work). DRY pattern via `_envelope.emitter()` keeps per-tool work small.

| Phase | Tools | Estimated commits |
|---|---|---|
| Phase A — search hot-path | trace, trace_index, search_flow, loc_index, onboard_index, claude_docs_index, knowledge_index | 2-3 |
| Phase B — brain + audit | brain_audit, brain_evolve, brain_promote, self_audit, validate, hygiene | 2 |
| Phase C — karpathy bundle | complexity_checker, diff_surgeon, assumption_linter, goal_verifier | 1 |
| Phase D — specialists | the remaining 9 retrofit-pending tools | 2-3 |
| Phase E — needs-json-flag | the 17 tools that need flag wiring first | 4-6 (heavier) |
| Phase F — MCP adapter | unified MCP+CLI envelope | 1-2 |
| **Total** | | **~12-17 commits** |

## How to regenerate this inventory

```bash
python3 - <<'PY'
from pathlib import Path
import re
ROOT = Path("plugins/kaizen")
EMITS = {"gatekeeper", "surface", "iron_laws", "metrics", "roadmap_status"}
for script in sorted(ROOT.glob("skills/*/scripts/*.py")):
    if script.stem in EMITS:
        status = "✅"
    elif script.name.startswith("_") or script.name.endswith("_mcp.py"):
        continue
    else:
        text = script.read_text(errors="ignore")
        has_json = bool(re.search(r"--json|args\.json", text))
        has_main = "def main(" in text or '__main__' in text
        status = "🔄" if has_json else ("🟡" if has_main else "🔵")
    print(f"{status} {script.relative_to(ROOT)}  ({len(text.splitlines())} LOC)")
PY
```

Re-run before each retrofit batch to see what's actually pending.
