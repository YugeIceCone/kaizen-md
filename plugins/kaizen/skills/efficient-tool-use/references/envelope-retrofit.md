# Envelope retrofit inventory + roadmap

**Last regenerated**: 2026-05-17 (auto-generatable via the script at the bottom of this file).

Tracks which kaizen tools emit the canonical tool-output envelope (`assets/schemas/tool-output.schema.json`) and which don't yet. Continuous reference for the "programmable + reproducible + consistent output" effort.

## Status legend

- **✅ emit** — emits canonical envelope via `_envelope.emit()` / `_envelope.emitter()`
- **🔄 retrofit-pending** — has `--json` flag; emits bare JSON; needs envelope wrap (mechanical, ~5 LOC per tool)
- **🟡 needs-json-flag** — has CLI `main()` but no `--json` flag; needs flag wiring first (medium effort)
- **🔵 no-cli** — file is a library / supports no command-line entry (no retrofit needed)
- **mcp** — `*_mcp.py` MCP server; uses MCP protocol envelope (separate concern)
- **shell** — `.sh` script; separate retrofit story

## Summary

| Status | Count |
|---|---|
| ✅ emit | 33 |
| 🔄 retrofit-pending | 0 |
| 🟡 needs-json-flag | 19 |
| 🔵 no-cli | 3 |
| mcp | 22 |
| shell | 27 |
| **Total CLI Python** | **52** |

**Envelope coverage**: 33 / (52 − 19 needs-json-flag) = **33/33 = 100%** of "has --json flag" tools.

All `--json`-capable tools now emit canonical envelope. Remaining 19 need flag wiring before they can join (Phase E).

## Tools by category

### ✅ Emit canonical envelope (33)

Phase A-C landed search hot-path + brain/audit + karpathy bundle (11 tools). Phase D landed observe / scrape / manifests / handoff / drift / config / docs_flow (7 tools). Phase D2 landed the remaining 7 (trace_index / knowledge_index / validate / index_flow / loop_state / models / self_audit_agent).

| Tool | Path | Phase |
|---|---|---|
| `gatekeeper` | `skills/workflow/scripts/gatekeeper.py` | initial |
| `surface` | `skills/workflow/scripts/surface.py` | initial |
| `iron_laws` | `skills/workflow/scripts/iron_laws.py` | initial |
| `metrics` | `skills/workflow/scripts/metrics.py` | initial |
| `roadmap_status` | `skills/workflow/scripts/roadmap_status.py` | initial |
| `trace` | `skills/workflow/scripts/trace.py` | A |
| `loc_index` | `scripts/indexers/loc_index.py` | A |
| `search_flow` | `skills/workflow/scripts/search_flow.py` | A |
| `claude_docs_index` | `scripts/indexers/claude_docs_index.py` | A |
| `onboard_index` | `scripts/indexers/onboard_index.py` | A |
| `brain_audit` | `scripts/brain/brain_audit.py` | B |
| `brain_evolve` | `scripts/brain/brain_evolve.py` | B |
| `brain_promote` | `scripts/brain/brain_promote.py` | B |
| `self_audit` | `skills/workflow/scripts/self_audit.py` | B |
| `hygiene` | `skills/workflow/scripts/hygiene.py` | B |
| `complexity_checker` | `skills/karpathy/scripts/complexity_checker.py` | C |
| `diff_surgeon` | `skills/karpathy/scripts/diff_surgeon.py` | C |
| `assumption_linter` | `skills/karpathy/scripts/assumption_linter.py` | C |
| `goal_verifier` | `skills/karpathy/scripts/goal_verifier.py` | C |
| `observe` | `skills/workflow/scripts/observe.py` | D |
| `scrape_index` | `scripts/indexers/scrape_index.py` | D |
| `manifests_cli` | `skills/workflow/scripts/manifests_cli.py` | D |
| `handoff` | `skills/workflow/scripts/handoff.py` | D |
| `drift_cli` | `skills/workflow/scripts/drift_cli.py` | D |
| `config` | `skills/workflow/scripts/config.py` | D |
| `docs_flow` | `skills/workflow/scripts/docs_flow.py` | D |
| `trace_index` | `scripts/indexers/trace_index.py` | D2 |
| `knowledge_index` | `scripts/indexers/knowledge_index.py` | D2 |
| `validate` | `skills/plugin-development/scripts/validate.py` | D2 |
| `index_flow` | `skills/workflow/scripts/index_flow.py` | D2 |
| `loop_state` | `skills/workflow/scripts/loop_state.py` | D2 |
| `models` | `skills/workflow/scripts/models.py` | D2 |
| `self_audit_agent` | `skills/workflow/scripts/self_audit_agent.py` | D2 |

### 🔄 Retrofit-pending (0)

All `--json`-capable tools now emit canonical envelope. The 19 below need flag wiring before they can be retrofitted.

### 🟡 Needs `--json` flag wired first (19)

Add `--json` to argparse, then envelope-wrap. Phase E work.

| Tool | Notes |
|---|---|
| `backlog.py` | Text-only CLI; many subcommands |
| `brain.py` | Schema-driven brain CLI; large surface |
| `build_index.py` | Brain semantic index |
| `cache.py` | Cache CRUD; small surface |
| `context.py` | Context-window state reporter |
| `daemon.py` | Daemon control (status would benefit) |
| `docs_gen.py` | Doc generator |
| `export_target.py` | Bundle export to sibling AI-CLIs |
| `flow.py` | Async Node+Flow demo |
| `gateway.py` | Single FastMCP gateway router |
| `inbox.py` | Message inbox CLI |
| `lint_fix_setup.py` | Local-LLM setup (`setup_summary()` already json-able) |
| `llm_proxy.py` | LLM trace proxy control |
| `loop_ledger.py` | Loop ledger CRUD |
| `rules.py` | Brain-sourced rule lookup |
| `schemas.py` | Schema dataclass surface |
| `shim.py` | Bin-symlink resolution |
| `trace_index_gpu.py` | GPU variant of trace_index |
| `workflow_runner.py` | Workflow state machine runner |

### MCP servers (22 — separate envelope story)

The MCP protocol has its own response envelope. Currently MCP wrappers like `gatekeeper_mcp.py` wrap the underlying CLI script (`gatekeeper.py`) and re-emit; if the CLI emits canonical envelope, the MCP wrapper passes it through.

**Phase F work**: define an MCP-to-canonical-envelope adapter so MCP responses ALSO carry the kaizen envelope shape. Not blocking; agents calling MCP tools already get structured returns natively.

### Shell scripts (27 — separate retrofit story)

Most are install/setup scripts — they emit human-readable progress lines. A few produce structured output. Lower priority.

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

Rough effort estimate: **~1 commit per 3-5 retrofits**. DRY pattern via `_envelope.emitter()` keeps per-tool work small.

| Phase | Tools | Estimated commits | Status |
|---|---|---|---|
| Phase A — search hot-path | trace, loc_index, search_flow, onboard_index, claude_docs_index | 2-3 | ✅ landed |
| Phase B — brain + audit | brain_audit, brain_evolve, brain_promote, self_audit, hygiene | 2 | ✅ landed |
| Phase C — karpathy bundle | complexity_checker, diff_surgeon, assumption_linter, goal_verifier | 1 | ✅ landed |
| Phase D — specialists | observe, scrape_index, manifests_cli, handoff, drift_cli, config, docs_flow | 1-2 | ✅ landed |
| Phase D2 — remaining-pending | trace_index, knowledge_index, validate, index_flow, loop_state, models, self_audit_agent | 1-2 | ✅ landed |
| Phase E — needs-json-flag | the 19 tools that need flag wiring first | 4-6 (heavier) | pending |
| Phase F — MCP adapter | unified MCP+CLI envelope | 1-2 | pending |
| **Total remaining** | | **~5-8 commits** | |

## How to regenerate this inventory

```bash
python3 - <<'PY'
from pathlib import Path
import re
ROOT = Path("plugins/kaizen")
emits, pending, needs_flag, no_cli = [], [], [], []
for script in sorted(ROOT.glob("skills/*/scripts/*.py")):
    name = script.name
    if name.startswith("_") or name.endswith("_mcp.py"):
        continue
    text = script.read_text(errors="ignore")
    if "import _envelope" in text or "from _envelope" in text:
        emits.append(script.relative_to(ROOT))
        continue
    has_json = bool(re.search(r"--json|args\.json", text))
    has_main = "def main(" in text or '__main__' in text
    if has_json:
        pending.append(script.relative_to(ROOT))
    elif has_main:
        needs_flag.append(script.relative_to(ROOT))
    else:
        no_cli.append(script.relative_to(ROOT))
print(f"emit:             {len(emits)}")
print(f"retrofit-pending: {len(pending)}")
print(f"needs-json-flag:  {len(needs_flag)}")
print(f"no-cli:           {len(no_cli)}")
PY
```

Re-run before each retrofit batch to see what's actually pending.
