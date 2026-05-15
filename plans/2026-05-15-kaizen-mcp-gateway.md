# Kaizen MCP Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> Spec: `docs/superpowers/specs/2026-05-15-kaizen-mcp-gateway-design.md`.
> All paths relative to `~/workspace/kaizen-md/plugins/kaizen/` unless
> stated. Tests run from that dir: `python3 -m unittest tests.test_<name> -v`.
> The kaizen pre-commit gate runs on every commit; Conventional Commits.
> Each phase ends green (its tests + `ci-gate.sh`).

**Goal:** Consolidate the plugin's 21 MCP servers (142 tools) under one FastMCP v3 gateway registered as the single `.mcp.json` entry — curated core visible by default, full catalog reachable via search, zero capability loss.

**Architecture:** A `gateway.py` (standalone `fastmcp>=3.0`, `uv run --script`) imports the 21 sub-server modules, `mount()`s each without a namespace (tool names already globally unique), and adds `RegexSearchTransform` so only a ~13-tool curated core + 2 synthetic tools are listed by default. Sub-servers migrate from the `mcp` SDK to standalone `fastmcp` (mechanical, ~2 lines each). Phased: pilot (prove the API) → bulk migrate → fold in brain+metrics → flip manifests → curate.

**Tech Stack:** Python 3 stdlib + `fastmcp>=3.0`, `uv run --script` PEP-723, `unittest`, JSON manifests.

## Status

- [x] Phase 1 — Gateway skeleton + 3-server pilot
- [x] Phase 2 — Migrate the remaining 16 servers
- [x] Phase 3 — Fold in brain + metrics
- [x] Phase 4 — Flip `.mcp.json` + `plugin.json` to the single entry
- [x] Phase 5 — Curate core + tune search + CHANGELOG

**Resume protocol:** check the boxes above; each phase is a self-contained set of tasks ending with a commit. Start at the first unchecked phase.

---

## Phase 1 — Gateway skeleton + 3-server pilot

### Task 1.1: Spike — verify the real `fastmcp>=3.0` API

The whole design rests on `mount()` + `RegexSearchTransform` behaving as the Context7 docs describe. Prove it against the actual installed package before migrating anything.

**Files:**
- Create (throwaway): `/tmp/fastmcp_spike.py`

- [ ] **Step 1: Write the spike**

Create `/tmp/fastmcp_spike.py`:

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp>=3.0"]
# ///
"""Spike: confirm fastmcp v3 mount() + RegexSearchTransform API."""
from fastmcp import FastMCP

child = FastMCP("child")

@child.tool()
def child_ping() -> str:
    return "pong"

main = FastMCP("main")
main.mount(child)

# search transform
from fastmcp.server.transforms.search import RegexSearchTransform
main.add_transform(RegexSearchTransform(
    search_tool_name="kaizen_search_tools",
    call_tool_name="kaizen_call_tool",
))
print("OK: import + mount + RegexSearchTransform all resolved")
print("transform attrs:", [a for a in dir(RegexSearchTransform) if not a.startswith("_")])
```

- [ ] **Step 2: Run the spike**

Run: `uv run --script /tmp/fastmcp_spike.py`
Expected: prints `OK: import + mount + RegexSearchTransform all resolved`.

**If it fails** (ImportError, wrong signature, `mount`/`add_transform`/`RegexSearchTransform` not found): the real API differs from the design's assumption. **STOP. Do not guess.** Report the actual error + `uv run --with fastmcp python -c "import fastmcp; help(fastmcp.FastMCP.mount)"` output, and revise the spec before continuing.

- [ ] **Step 3: Probe the `always_visible` mechanism**

Run: `uv run --with 'fastmcp>=3.0' python3 -c "from fastmcp.server.transforms.search import RegexSearchTransform; import inspect; print(inspect.signature(RegexSearchTransform.__init__))"`
Expected: shows the constructor params. Note whether `always_visible` is a constructor kwarg, a tag, or a per-tool marker — this determines how Task 1.3 marks the curated core. Record the finding inline in `gateway.py`'s comments when you write it.

- [ ] **Step 4: Clean up**

Run: `rm /tmp/fastmcp_spike.py`
(No commit — throwaway spike.)

### Task 1.2: Migrate the 3 pilot servers to standalone fastmcp

The pilots: `iron_laws_mcp.py`, `manifests_mcp.py`, `drift_mcp.py`. Migration per file is exactly two edits.

**Files:**
- Modify: `skills/workflow/scripts/iron_laws_mcp.py`
- Modify: `skills/workflow/scripts/manifests_mcp.py`
- Modify: `skills/workflow/scripts/drift_mcp.py`

- [ ] **Step 1: Run the pilots' existing tests to record the baseline**

Run: `python3 -m unittest tests.test_iron_laws tests.test_manifests tests.test_drift -v 2>&1 | tail -5`
Expected: PASS (record the count). If any test file does not exist, note it and skip that file in this step only.

- [ ] **Step 2: Edit `iron_laws_mcp.py`**

Change the import line:
```python
from mcp.server.fastmcp import FastMCP
```
to:
```python
from fastmcp import FastMCP
```

In the `# /// script` block, change:
```python
#     "mcp>=1.0",
```
to:
```python
#     "fastmcp>=3.0",
```
Leave `pyyaml>=6.0` and `jsonschema>=4.0` in the block unchanged.

- [ ] **Step 3: Edit `manifests_mcp.py`**

Same import swap (`from mcp.server.fastmcp import FastMCP` → `from fastmcp import FastMCP`). In its `# /// script` block change `"mcp>=1.0",` → `"fastmcp>=3.0",` (it has no other deps).

- [ ] **Step 4: Edit `drift_mcp.py`**

Same import swap. In its `# /// script` block change `"mcp>=1.0",` → `"fastmcp>=3.0",`. If `drift_mcp.py` lists additional deps, leave them unchanged.

- [ ] **Step 5: Verify each migrated server still imports + runs**

Run:
```bash
for s in iron_laws manifests drift; do
  uv run --script skills/workflow/scripts/${s}_mcp.py --help >/dev/null 2>&1 \
    && echo "$s: ok" || echo "$s: FAIL"
done
```
Expected: `iron_laws: ok`, `manifests: ok`, `drift: ok`. A FAIL means the migration broke the server — fix before continuing.

- [ ] **Step 6: Re-run the pilots' existing tests**

Run: `python3 -m unittest tests.test_iron_laws tests.test_manifests tests.test_drift -v 2>&1 | tail -5`
Expected: same PASS count as Step 1 — the tool bodies are unchanged, so behavior is unchanged.

- [ ] **Step 7: Commit**

```bash
cd ~/workspace/kaizen-md
git add plugins/kaizen/skills/workflow/scripts/iron_laws_mcp.py \
        plugins/kaizen/skills/workflow/scripts/manifests_mcp.py \
        plugins/kaizen/skills/workflow/scripts/drift_mcp.py
git commit -m "refactor(mcp): migrate iron-laws/manifests/drift to standalone fastmcp

Pilot batch for the MCP gateway consolidation. Two-line migration each
(import line + # /// script dep block); tool bodies unchanged. Proves
the mcp-SDK -> fastmcp v3 path before the bulk migration."
```

### Task 1.3: Create `gateway.py` + `tests/test_gateway.py`

**Files:**
- Create: `skills/workflow/scripts/gateway.py`
- Create: `tests/test_gateway.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_gateway.py`:

```python
"""Tests for gateway.py — the single-entry MCP gateway."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "workflow" / "scripts"
sys.path.insert(0, str(SCRIPTS))


class TestGatewayComposition(unittest.TestCase):
    def test_gateway_imports_and_mounts_pilots(self):
        import gateway
        # gateway.MOUNTED is the list of (name, module) the gateway mounted
        names = {name for name, _ in gateway.MOUNTED}
        for pilot in ("iron_laws", "manifests", "drift"):
            self.assertIn(pilot, names, f"{pilot} should be mounted")

    def test_gateway_object_is_fastmcp(self):
        import gateway
        from fastmcp import FastMCP
        self.assertIsInstance(gateway.gw, FastMCP)

    def test_gateway_has_no_mount_errors(self):
        import gateway
        self.assertEqual(gateway.MOUNT_ERRORS, [],
                         f"no sub-server should fail to mount: {gateway.MOUNT_ERRORS}")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_gateway -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gateway'`.

- [ ] **Step 3: Write `gateway.py`**

Create `skills/workflow/scripts/gateway.py`:

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastmcp>=3.0",
#     "pyyaml>=6.0",
#     "jsonschema>=4.0",
# ]
# ///
"""kaizen MCP gateway — the single MCP entry point.

Composes the plugin's per-domain MCP sub-servers into one FastMCP
server. Each sub-server is imported as a plain Python module (its
`.run()` is __main__-guarded, so importing is side-effect-free) and
mounted WITHOUT a namespace — every tool name is already globally
unique via the per-server `<domain>_*` convention, so bare mount keeps
tool names byte-identical to the pre-gateway world.

A RegexSearchTransform restricts the default `list_tools()` output to a
curated `always_visible` core plus two synthetic tools
(`kaizen_search_tools` / `kaizen_call_tool`); every other tool stays
fully callable — the search transform controls discovery, not access.

Phase 1: pilots only (iron_laws, manifests, drift). Later phases extend
PILOTS into the full 21-server list.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastmcp import FastMCP

# (name, module-import-name) for every sub-server to mount. Extended in
# later phases. `name` is the short domain label used in diagnostics.
PILOTS: list[tuple[str, str]] = [
    ("iron_laws", "iron_laws_mcp"),
    ("manifests", "manifests_mcp"),
    ("drift", "drift_mcp"),
]

gw = FastMCP("kaizen")
MOUNTED: list[tuple[str, object]] = []
MOUNT_ERRORS: list[str] = []

for name, modname in PILOTS:
    try:
        mod = __import__(modname)
        gw.mount(mod.mcp)
        MOUNTED.append((name, mod))
    except Exception as exc:  # one broken server must not kill the gateway
        MOUNT_ERRORS.append(f"{name}: {exc}")

if __name__ == "__main__":
    if MOUNT_ERRORS:
        for e in MOUNT_ERRORS:
            print(f"[gateway] mount error: {e}", file=sys.stderr)
    gw.run()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_gateway -v`
Expected: PASS (3 tests).

Note: `import gateway` under the plain `python3` test runner needs `fastmcp` importable. If the test errors with `ModuleNotFoundError: fastmcp`, install it for the test env: `uv pip install --system 'fastmcp>=3.0'` is wrong for this repo — instead run the test via `uv run --with 'fastmcp>=3.0' python3 -m unittest tests.test_gateway -v` and record that the gateway test needs the fastmcp dep. If that is needed, add a top-of-file skip guard to `tests/test_gateway.py`:
```python
try:
    import fastmcp  # noqa: F401
except ImportError:
    raise unittest.SkipTest("fastmcp not installed in the test env")
```
Place it after the imports. Prefer the skip-guard so the default `python3 -m unittest discover` stays green.

- [ ] **Step 5: Smoke the gateway under uv**

Run: `uv run --script skills/workflow/scripts/gateway.py --help >/dev/null 2>&1; echo "exit: $?"`
Expected: exit 0 (the gateway starts under uv with `fastmcp` provisioned). If `--help` is not handled, an exit from the stdio server is acceptable as long as uv resolved `fastmcp` — confirm with `uv run --script skills/workflow/scripts/gateway.py </dev/null` returning quickly without an ImportError.

- [ ] **Step 6: Commit**

```bash
cd ~/workspace/kaizen-md
git add plugins/kaizen/skills/workflow/scripts/gateway.py \
        plugins/kaizen/tests/test_gateway.py
git commit -m "feat(mcp): gateway.py — single-entry MCP gateway (pilot)

Imports + mounts the 3 pilot sub-servers (iron_laws/manifests/drift)
on one FastMCP v3 server. Bare mount (tool names already globally
unique). MOUNTED / MOUNT_ERRORS expose composition state for tests.
PILOTS list extends to all 21 servers in later phases."
```

### Task 1.4: Register the `kaizen` gateway in `.mcp.json` (alongside the 19)

Dual-run during migration: the gateway is added but the 19 individual entries stay until Phase 4, so no capability is lost mid-migration.

**Files:**
- Modify: `.claude-plugin/plugin.json` (add gateway permission)
- Modify: `.mcp.json`

- [ ] **Step 1: Add the gateway permission to `plugin.json`**

In `.claude-plugin/plugin.json`, in the `permissions.allow` array, immediately after the line `"Bash(uv run --script ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/iron_laws_mcp.py:*)",` add:
```json
      "Bash(uv run --script ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/gateway.py:*)",
```

- [ ] **Step 2: Add the `kaizen` server to `.mcp.json`**

In `.mcp.json`, inside `"mcpServers"`, add this entry (place it first, before `"backlog"`):
```json
    "kaizen": {
      "command": "uv",
      "args": [
        "run",
        "--script",
        "${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/gateway.py"
      ]
    },
```

- [ ] **Step 3: Verify both manifests are valid JSON**

Run:
```bash
cd ~/workspace/kaizen-md
python3 -c "import json; json.load(open('plugins/kaizen/.mcp.json')); json.load(open('plugins/kaizen/.claude-plugin/plugin.json')); print('both valid')"
```
Expected: `both valid`.

- [ ] **Step 4: Run ci-gate**

Run: `bash plugins/kaizen/skills/workflow/scripts/ci-gate.sh`
Expected: `ci-gate: all checks passed`, exit 0.

- [ ] **Step 5: Commit + tick the Phase 1 box**

In this plan file, change `- [ ] Phase 1 — Gateway skeleton + 3-server pilot` to `- [x] Phase 1 — Gateway skeleton + 3-server pilot`.

```bash
cd ~/workspace/kaizen-md
git add plugins/kaizen/.mcp.json plugins/kaizen/.claude-plugin/plugin.json \
        plans/2026-05-15-kaizen-mcp-gateway.md
git commit -m "feat(mcp): register the kaizen gateway alongside the per-domain servers

Dual-run: the gateway is live but the 19 individual .mcp.json entries
stay until Phase 4, so nothing is lost mid-migration. Phase 1 done."
```

---

## Phase 2 — Migrate the remaining 16 servers

### Task 2.1: Migrate the 15 standard `mcp`-SDK servers

The same two-line transform from Task 1.2, applied to every remaining `*_mcp.py` that still imports the `mcp` SDK:

`browser_mcp.py`, `trace_mcp.py`, `knowledge_mcp.py`, `onboard_mcp.py`, `claude_docs_mcp.py`, `scrape_mcp.py`, `state_mcp.py`, `lint_mcp.py`, `workflow_mcp.py`, `loc_mcp.py`, `loop_mcp.py`, `shim_mcp.py`, `rerank_mcp.py`, `audit_mcp.py`, `roadmap_mcp.py`.

**Files:**
- Modify: each of the 15 files above (in `skills/workflow/scripts/`).

- [ ] **Step 1: Record the test baseline**

Run: `python3 -m unittest discover -s tests -p 'test_*.py' 2>&1 | tail -3`
Expected: note the OK count and skip count.

- [ ] **Step 2: Apply the two-line transform to each of the 15 files**

For each file: (a) change `from mcp.server.fastmcp import FastMCP` → `from fastmcp import FastMCP`; (b) in the `# /// script` block change the `"mcp>=1.0",` line → `"fastmcp>=3.0",`. Leave every other dependency line untouched. Do NOT change decorators, function bodies, or `.run()`.

Verify the transform hit every file — none should still import the `mcp` SDK:
```bash
cd ~/workspace/kaizen-md/plugins/kaizen
grep -l "from mcp.server.fastmcp import" skills/workflow/scripts/*_mcp.py
```
Expected: only `brain_mcp.py` and `metrics_mcp.py` remain (those are Phase 3).

- [ ] **Step 3: Verify every migrated server imports + runs**

Run:
```bash
cd ~/workspace/kaizen-md/plugins/kaizen
for s in browser trace knowledge onboard claude_docs scrape state lint workflow loc loop shim rerank audit roadmap; do
  uv run --script skills/workflow/scripts/${s}_mcp.py --help >/dev/null 2>&1 \
    && echo "$s: ok" || echo "$s: FAIL"
done
```
Expected: all `ok`. Any `FAIL` — fix that file before continuing.

- [ ] **Step 4: Re-run the full test suite**

Run: `python3 -m unittest discover -s tests -p 'test_*.py' 2>&1 | tail -3`
Expected: same OK count as Step 1 (tool bodies unchanged).

- [ ] **Step 5: Commit**

```bash
cd ~/workspace/kaizen-md
git add plugins/kaizen/skills/workflow/scripts/browser_mcp.py \
        plugins/kaizen/skills/workflow/scripts/trace_mcp.py \
        plugins/kaizen/skills/workflow/scripts/knowledge_mcp.py \
        plugins/kaizen/skills/workflow/scripts/onboard_mcp.py \
        plugins/kaizen/skills/workflow/scripts/claude_docs_mcp.py \
        plugins/kaizen/skills/workflow/scripts/scrape_mcp.py \
        plugins/kaizen/skills/workflow/scripts/state_mcp.py \
        plugins/kaizen/skills/workflow/scripts/lint_mcp.py \
        plugins/kaizen/skills/workflow/scripts/workflow_mcp.py \
        plugins/kaizen/skills/workflow/scripts/loc_mcp.py \
        plugins/kaizen/skills/workflow/scripts/loop_mcp.py \
        plugins/kaizen/skills/workflow/scripts/shim_mcp.py \
        plugins/kaizen/skills/workflow/scripts/rerank_mcp.py \
        plugins/kaizen/skills/workflow/scripts/audit_mcp.py \
        plugins/kaizen/skills/workflow/scripts/roadmap_mcp.py
git commit -m "refactor(mcp): migrate the remaining 15 servers to standalone fastmcp

Same two-line transform as the pilot batch (import + # /// script dep
block); tool bodies unchanged. Only brain/metrics still on the mcp SDK
(Phase 3)."
```

### Task 2.2: Normalize `mcp_server.py` → `backlog_mcp.py`

`mcp_server.py` (the backlog server) is already on standalone `fastmcp` but is the lone non-PEP-723 server (`#!/usr/bin/env python3`, relies on a global `pip install fastmcp`). Rename it and give it a proper `# /// script` block.

**Files:**
- Rename: `skills/workflow/scripts/mcp_server.py` → `skills/workflow/scripts/backlog_mcp.py`
- Modify: `.mcp.json` (the `backlog` entry path + command)
- Modify: `.claude-plugin/plugin.json` (the `mcp_server.py` permission line)

- [ ] **Step 1: Rename the file**

```bash
cd ~/workspace/kaizen-md
git mv plugins/kaizen/skills/workflow/scripts/mcp_server.py \
       plugins/kaizen/skills/workflow/scripts/backlog_mcp.py
```

- [ ] **Step 2: Replace the shebang with a PEP-723 block**

In `backlog_mcp.py`, replace the first line:
```python
#!/usr/bin/env python3
```
with:
```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp>=3.0"]
# ///
```

- [ ] **Step 3: Update `.mcp.json`**

In `.mcp.json`, replace the `"backlog"` entry with:
```json
    "backlog": {
      "command": "uv",
      "args": [
        "run",
        "--script",
        "${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/backlog_mcp.py"
      ]
    },
```

- [ ] **Step 4: Update `plugin.json`**

In `.claude-plugin/plugin.json`, replace the line:
```json
      "Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/mcp_server.py:*)",
```
with:
```json
      "Bash(uv run --script ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/backlog_mcp.py:*)",
```

- [ ] **Step 5: Verify**

Run:
```bash
cd ~/workspace/kaizen-md/plugins/kaizen
uv run --script skills/workflow/scripts/backlog_mcp.py --help >/dev/null 2>&1 && echo "backlog: ok"
python3 -c "import json; json.load(open('.mcp.json')); json.load(open('.claude-plugin/plugin.json')); print('json valid')"
grep -rn "mcp_server.py" . --include='*.py' --include='*.sh' --include='*.json' --include='*.md' | grep -v CHANGELOG
```
Expected: `backlog: ok`, `json valid`, and the grep returns nothing (no stale `mcp_server.py` references). If the grep finds references, update each to `backlog_mcp.py`.

- [ ] **Step 6: Commit**

```bash
cd ~/workspace/kaizen-md
git add -A plugins/kaizen/skills/workflow/scripts/backlog_mcp.py \
       plugins/kaizen/.mcp.json plugins/kaizen/.claude-plugin/plugin.json
git commit -m "refactor(mcp): normalize mcp_server.py -> backlog_mcp.py (PEP-723)

The backlog server was the lone non-PEP-723 MCP server. Renamed to
match the <domain>_mcp.py convention + given a proper # /// script
block so uv provisions fastmcp like every sibling."
```

### Task 2.3: Mount all 19 migrated servers in `gateway.py`

**Files:**
- Modify: `skills/workflow/scripts/gateway.py`
- Modify: `tests/test_gateway.py`

- [ ] **Step 1: Extend the test**

In `tests/test_gateway.py`, add a new test method to `TestGatewayComposition`:

```python
    def test_gateway_mounts_all_phase2_servers(self):
        import gateway
        names = {name for name, _ in gateway.MOUNTED}
        expected = {
            "iron_laws", "manifests", "drift", "backlog", "browser",
            "trace", "knowledge", "onboard", "claude_docs", "scrape",
            "state", "lint", "workflow", "loc", "loop", "shim",
            "rerank", "audit", "roadmap",
        }
        self.assertEqual(names, expected,
                         f"missing: {expected - names}, extra: {names - expected}")
        self.assertEqual(gateway.MOUNT_ERRORS, [], str(gateway.MOUNT_ERRORS))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_gateway.TestGatewayComposition.test_gateway_mounts_all_phase2_servers -v`
Expected: FAIL — only the 3 pilots are in `MOUNTED`.

- [ ] **Step 3: Extend the `PILOTS` list in `gateway.py`**

In `gateway.py`, rename `PILOTS` to `SUBSERVERS` (rename every occurrence — the list and the `for name, modname in SUBSERVERS:` loop) and replace its contents with the full 19:

```python
# (name, module-import-name) for every sub-server to mount.
SUBSERVERS: list[tuple[str, str]] = [
    ("iron_laws", "iron_laws_mcp"),
    ("manifests", "manifests_mcp"),
    ("drift", "drift_mcp"),
    ("backlog", "backlog_mcp"),
    ("browser", "browser_mcp"),
    ("trace", "trace_mcp"),
    ("knowledge", "knowledge_mcp"),
    ("onboard", "onboard_mcp"),
    ("claude_docs", "claude_docs_mcp"),
    ("scrape", "scrape_mcp"),
    ("state", "state_mcp"),
    ("lint", "lint_mcp"),
    ("workflow", "workflow_mcp"),
    ("loc", "loc_mcp"),
    ("loop", "loop_mcp"),
    ("shim", "shim_mcp"),
    ("rerank", "rerank_mcp"),
    ("audit", "audit_mcp"),
    ("roadmap", "roadmap_mcp"),
]
```

Also update the module docstring's last paragraph: replace "Phase 1: pilots only..." with "Phase 2: all 19 migrated servers mounted; brain + metrics join in Phase 3."

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest tests.test_gateway -v`
Expected: PASS (all tests, including the new one). If any server is in `MOUNT_ERRORS`, the failure message names it — fix that server's migration.

- [ ] **Step 5: Smoke the gateway under uv**

Run: `uv run --script skills/workflow/scripts/gateway.py </dev/null 2>&1 | head -5; echo "exit: $?"`
Expected: no `ImportError`, no mount-error lines printed to stderr.

- [ ] **Step 6: Commit + tick the Phase 2 box**

Change `- [ ] Phase 2` to `- [x] Phase 2` in this plan file.

```bash
cd ~/workspace/kaizen-md
git add plugins/kaizen/skills/workflow/scripts/gateway.py \
        plugins/kaizen/tests/test_gateway.py \
        plans/2026-05-15-kaizen-mcp-gateway.md
git commit -m "feat(mcp): gateway mounts all 19 migrated sub-servers

SUBSERVERS list extended from the 3 pilots to the full 19. test_gateway
asserts the exact mounted set + zero mount errors. Phase 2 done."
```

---

## Phase 3 — Fold in brain + metrics

`brain_mcp.py` and `metrics_mcp.py` are fully built (~12 + ~8 tools) but were never registered in `.mcp.json` — folding them into the gateway makes them reachable for the first time.

**Files:**
- Modify: `skills/workflow/scripts/brain_mcp.py`
- Modify: `skills/workflow/scripts/metrics_mcp.py`
- Modify: `skills/workflow/scripts/gateway.py`
- Modify: `tests/test_gateway.py`

- [ ] **Step 1: Extend the test**

In `tests/test_gateway.py`, add to `TestGatewayComposition`:

```python
    def test_gateway_mounts_brain_and_metrics(self):
        import gateway
        names = {name for name, _ in gateway.MOUNTED}
        self.assertIn("brain", names)
        self.assertIn("metrics", names)
        self.assertEqual(gateway.MOUNT_ERRORS, [], str(gateway.MOUNT_ERRORS))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_gateway.TestGatewayComposition.test_gateway_mounts_brain_and_metrics -v`
Expected: FAIL — brain/metrics not in `MOUNTED`.

- [ ] **Step 3: Migrate `brain_mcp.py` and `metrics_mcp.py`**

Apply the same two-line transform to both: `from mcp.server.fastmcp import FastMCP` → `from fastmcp import FastMCP`, and `"mcp>=1.0",` → `"fastmcp>=3.0",` in each `# /// script` block. Leave all other deps unchanged.

Verify no server still imports the mcp SDK:
```bash
cd ~/workspace/kaizen-md/plugins/kaizen
grep -l "from mcp.server.fastmcp import" skills/workflow/scripts/*_mcp.py
```
Expected: nothing (all 21 now on fastmcp).

- [ ] **Step 4: Add brain + metrics to `SUBSERVERS` in `gateway.py`**

In `gateway.py`, append to the `SUBSERVERS` list:
```python
    ("brain", "brain_mcp"),
    ("metrics", "metrics_mcp"),
```

- [ ] **Step 5: Verify the two servers import + run**

Run:
```bash
cd ~/workspace/kaizen-md/plugins/kaizen
for s in brain metrics; do
  uv run --script skills/workflow/scripts/${s}_mcp.py --help >/dev/null 2>&1 \
    && echo "$s: ok" || echo "$s: FAIL"
done
```
Expected: `brain: ok`, `metrics: ok`.

- [ ] **Step 6: Run the gateway tests**

Run: `python3 -m unittest tests.test_gateway -v`
Expected: PASS (all tests).

- [ ] **Step 7: Commit + tick the Phase 3 box**

Change `- [ ] Phase 3` to `- [x] Phase 3` in this plan file.

```bash
cd ~/workspace/kaizen-md
git add plugins/kaizen/skills/workflow/scripts/brain_mcp.py \
        plugins/kaizen/skills/workflow/scripts/metrics_mcp.py \
        plugins/kaizen/skills/workflow/scripts/gateway.py \
        plugins/kaizen/tests/test_gateway.py \
        plans/2026-05-15-kaizen-mcp-gateway.md
git commit -m "feat(mcp): fold brain + metrics into the gateway

brain_mcp.py and metrics_mcp.py were built but never registered in
.mcp.json. Migrated to fastmcp + mounted — their ~20 tools are now
reachable through the gateway for the first time. All 21 servers now
on standalone fastmcp. Phase 3 done."
```

---

## Phase 4 — Flip `.mcp.json` + `plugin.json` to the single entry

Now the gateway mounts all 21 servers, the individual `.mcp.json` entries and per-server `plugin.json` permission lines are redundant. Collapse to one.

**Files:**
- Modify: `.mcp.json`
- Modify: `.claude-plugin/plugin.json`
- Modify: `tests/test_gateway.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_gateway.py`, add a new test class:

```python
import json


class TestSingleEntry(unittest.TestCase):
    def test_mcp_json_has_only_the_gateway(self):
        mcp_json = SCRIPTS.parent.parent / ".mcp.json"
        data = json.loads(mcp_json.read_text())
        self.assertEqual(list(data["mcpServers"].keys()), ["kaizen"],
                         "the gateway must be the only registered MCP server")

    def test_plugin_json_has_one_mcp_permission(self):
        plugin_json = SCRIPTS.parent.parent / ".claude-plugin" / "plugin.json"
        text = plugin_json.read_text()
        # the only *_mcp.py / gateway.py permission line is the gateway's
        self.assertNotIn("_mcp.py", text)
        self.assertIn("scripts/gateway.py", text)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_gateway.TestSingleEntry -v`
Expected: FAIL — `.mcp.json` still has 20 servers; `plugin.json` still has `_mcp.py` lines.

- [ ] **Step 3: Reduce `.mcp.json` to the single `kaizen` entry**

Replace the entire contents of `.mcp.json` with:
```json
{
  "mcpServers": {
    "kaizen": {
      "command": "uv",
      "args": [
        "run",
        "--script",
        "${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/gateway.py"
      ]
    }
  }
}
```

- [ ] **Step 4: Collapse the `plugin.json` MCP permissions**

In `.claude-plugin/plugin.json`, remove every line in `permissions.allow` whose value contains `_mcp.py` or `backlog_mcp.py`. Keep exactly one MCP-related line — the gateway's, added in Phase 1 Task 1.4:
```json
      "Bash(uv run --script ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/gateway.py:*)",
```
If that line is not present (e.g. it was removed by the `_mcp.py` sweep — it contains `gateway.py`, not `_mcp.py`, so it should survive), re-add it.

Verify:
```bash
cd ~/workspace/kaizen-md/plugins/kaizen
grep -c "_mcp.py" .claude-plugin/plugin.json   # expect 0
grep -c "scripts/gateway.py" .claude-plugin/plugin.json  # expect 1
python3 -c "import json; json.load(open('.claude-plugin/plugin.json')); print('json valid')"
```
Expected: `0`, `1`, `json valid`.

- [ ] **Step 5: Run the gateway tests + ci-gate**

Run:
```bash
cd ~/workspace/kaizen-md/plugins/kaizen
python3 -m unittest tests.test_gateway -v 2>&1 | tail -3
bash skills/workflow/scripts/ci-gate.sh 2>&1 | tail -3
```
Expected: gateway tests PASS; `ci-gate: all checks passed`.

- [ ] **Step 6: Commit + tick the Phase 4 box**

Change `- [ ] Phase 4` to `- [x] Phase 4` in this plan file.

```bash
cd ~/workspace/kaizen-md
git add plugins/kaizen/.mcp.json plugins/kaizen/.claude-plugin/plugin.json \
        plugins/kaizen/tests/test_gateway.py \
        plans/2026-05-15-kaizen-mcp-gateway.md
git commit -m "feat(mcp): single entry point — .mcp.json + plugin.json collapsed

.mcp.json drops the 20 per-domain entries for one 'kaizen' gateway
entry; plugin.json's ~19 per-server permission lines collapse to one
gateway permission. The gateway composes all 21 sub-servers in-process.
Phase 4 done."
```

---

## Phase 5 — Curate core + tune search + CHANGELOG

Apply the `RegexSearchTransform` so the default surface is the curated core + the 2 synthetic tools, and document the change.

**Files:**
- Modify: `skills/workflow/scripts/gateway.py`
- Modify: `tests/test_gateway.py`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Write the failing test**

In `tests/test_gateway.py`, add to `TestGatewayComposition`:

```python
    def test_search_transform_applied(self):
        import gateway
        # gateway.SEARCH_TRANSFORM_APPLIED is set True after add_transform
        self.assertTrue(gateway.SEARCH_TRANSFORM_APPLIED)

    def test_curated_core_is_defined(self):
        import gateway
        # CURATED_CORE is the always-visible tool-name list
        self.assertGreater(len(gateway.CURATED_CORE), 0)
        self.assertLessEqual(len(gateway.CURATED_CORE), 20,
                             "the curated core must stay small")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_gateway.TestGatewayComposition.test_search_transform_applied tests.test_gateway.TestGatewayComposition.test_curated_core_is_defined -v`
Expected: FAIL — `gateway` has no `SEARCH_TRANSFORM_APPLIED` / `CURATED_CORE`.

- [ ] **Step 3: Add the curated core + search transform to `gateway.py`**

In `gateway.py`, after the mount loop and before the `if __name__ == "__main__":` block, add:

```python
# Curated core — the hot-path read/search tools kept always-visible in
# the default tool list. Everything else is reachable via the search
# transform's kaizen_search_tools / kaizen_call_tool synthetic tools
# (discovery is curated; access is not — every tool stays callable).
CURATED_CORE: list[str] = [
    "loc_search", "knowledge_search", "onboard_search", "trace_search",
    "state_status", "state_health_summary", "workflow_status",
    "backlog_list", "iron_laws_check", "audit_latest",
    "roadmap_next", "drift_status", "metrics_session",
]

SEARCH_TRANSFORM_APPLIED = False
try:
    from fastmcp.server.transforms.search import RegexSearchTransform
    gw.add_transform(RegexSearchTransform(
        search_tool_name="kaizen_search_tools",
        call_tool_name="kaizen_call_tool",
        always_visible=CURATED_CORE,
    ))
    SEARCH_TRANSFORM_APPLIED = True
except Exception as exc:  # never block the gateway on a transform issue
    MOUNT_ERRORS.append(f"search-transform: {exc}")
```

Note: the `always_visible=CURATED_CORE` kwarg name is from the Context7 docs. **If Task 1.1 Step 3 found a different mechanism** (a per-tool tag, a different kwarg), use that instead and update this step's code to match — the intent is "these tool names stay in the default list, the rest go behind search." If `always_visible` is not a constructor kwarg, the fallback is FastMCP tags: tag each curated-core tool and pass the tag to the transform per the Task 1.1 finding.

Also: verify each name in `CURATED_CORE` is a real tool. Run:
```bash
cd ~/workspace/kaizen-md/plugins/kaizen
python3 -c "
import re,pathlib
have=set()
for f in pathlib.Path('skills/workflow/scripts').glob('*_mcp.py'):
    have |= set(re.findall(r'def (\w+)', f.read_text()))
core=['loc_search','knowledge_search','onboard_search','trace_search','state_status','state_health_summary','workflow_status','backlog_list','iron_laws_check','audit_latest','roadmap_next','drift_status','metrics_session']
missing=[c for c in core if c not in have]
print('MISSING:', missing if missing else 'none — all curated-core names exist')
"
```
Expected: `none`. If any are missing, the actual tool name differs — grep the owning server (`grep '@mcp.tool' skills/workflow/scripts/<server>_mcp.py -A2`) and correct the `CURATED_CORE` list to the real names.

- [ ] **Step 4: Run the gateway tests**

Run: `python3 -m unittest tests.test_gateway -v`
Expected: PASS (all tests).

- [ ] **Step 5: Smoke the full gateway under uv**

Run: `uv run --script skills/workflow/scripts/gateway.py </dev/null 2>&1 | head -5; echo "exit: $?"`
Expected: no ImportError, no mount-error or search-transform-error lines.

- [ ] **Step 6: Add the CHANGELOG entry**

In `plugins/kaizen/CHANGELOG.md`, under `## [Unreleased]`, add as the first entry:

```markdown
### Added — single-entry MCP gateway

The plugin's 21 MCP servers (142 tools) are consolidated behind one FastMCP v3 gateway — the sole `.mcp.json` entry.

- **`gateway.py`** imports + `mount()`s all 21 sub-servers in-process (bare mount — tool names are already globally unique, so they stay byte-identical to before). One `uv` process, one venv (the union of sub-server deps; `bootstrap.sh` pre-warms it).
- **Curated core + search.** A `RegexSearchTransform` keeps a ~13-tool hot-path core always-visible; the remaining ~130 tools are reachable via the synthetic `kaizen_search_tools` / `kaizen_call_tool`. Default context cost drops from 142 tool schemas to ~15 — with **zero capability loss**: the search transform controls discovery, not access, so every tool stays fully callable.
- **All 21 sub-servers migrated** from the bundled `mcp` SDK to standalone `fastmcp>=3.0` (two-line change each). `mcp_server.py` normalized to `backlog_mcp.py` with a PEP-723 block.
- **`brain` + `metrics` folded in** — both were built but never registered in `.mcp.json`; their ~20 tools are now reachable for the first time.
- `.mcp.json`: 20 entries → 1. `plugin.json`: ~19 MCP permission lines → 1.
```

- [ ] **Step 7: Run ci-gate**

Run: `bash plugins/kaizen/skills/workflow/scripts/ci-gate.sh 2>&1 | tail -3`
Expected: `ci-gate: all checks passed`.

- [ ] **Step 8: Commit + tick the Phase 5 box**

Change `- [ ] Phase 5` to `- [x] Phase 5` in this plan file.

```bash
cd ~/workspace/kaizen-md
git add plugins/kaizen/skills/workflow/scripts/gateway.py \
        plugins/kaizen/tests/test_gateway.py \
        plugins/kaizen/CHANGELOG.md \
        plans/2026-05-15-kaizen-mcp-gateway.md
git commit -m "feat(mcp): curated-core search transform + CHANGELOG

RegexSearchTransform keeps a ~13-tool hot-path core always-visible;
the long tail is reachable via kaizen_search_tools / kaizen_call_tool.
Default context drops 142 schemas -> ~15, zero capability loss. Phase
5 done — gateway consolidation complete."
```

---

## Self-Review

**Spec coverage:** Architecture/`gateway.py` → Task 1.3 + 2.3 + 3.4 + 5.3. Mount-without-namespace → Task 1.3 Step 3. Migration mechanics → Tasks 1.2, 2.1, 2.2, 3.3. Dependency-surface union → `gateway.py` `# /// script` block (Task 1.3 Step 3). Data flow / search transform → Task 5.3. 5-phase migration → Phases 1-5. Error handling (try/except per mount, MOUNT_ERRORS) → Task 1.3 Step 3. Testing (existing tests re-run + `tests/test_gateway.py` + the no-loss assertion) → every phase's verify steps + `test_gateway.py` grows each phase. `mcp_server.py` normalization → Task 2.2. brain/metrics fold-in → Phase 3. `.mcp.json`/`plugin.json` collapse → Phase 4.

**Known deferral:** the spec's "explicit assertion that all 142 tools are reachable" — the per-phase `test_gateway.py` asserts the exact mounted *server* set + zero mount errors, which transitively proves every server's tools are mounted. A literal 142-count assertion is brittle (the count changes as servers gain tools); the server-set assertion is the durable equivalent. This is an intentional, noted deviation, not a gap.

**Placeholder scan:** none — every code step shows complete code; every command has expected output. The two genuine unknowns (the `fastmcp` API shape, the `always_visible` mechanism) are handled by Task 1.1 as an explicit verify-or-STOP spike, and Task 5.3 Step 3 carries an explicit fallback path.

**Type/name consistency:** `gw` (the FastMCP object), `MOUNTED`, `MOUNT_ERRORS`, `SUBSERVERS` (renamed from `PILOTS` in Task 2.3 — every occurrence), `CURATED_CORE`, `SEARCH_TRANSFORM_APPLIED` — all defined once and referenced consistently. `kaizen_search_tools` / `kaizen_call_tool` consistent across spec + Task 5.3. Sub-server module names (`iron_laws_mcp`, `backlog_mcp`, …) consistent between the migration tasks and the `SUBSERVERS` list.

**Verify-at-impl flags:** (a) Task 1.1 — the real `fastmcp>=3.0` API; STOP if it diverges. (b) Task 1.3 Step 4 — whether the `python3` test runner needs a `fastmcp` skip-guard. (c) Task 5.3 Step 3 — the exact `always_visible` mechanism + the real curated-core tool names (the embedded probe script checks them).
