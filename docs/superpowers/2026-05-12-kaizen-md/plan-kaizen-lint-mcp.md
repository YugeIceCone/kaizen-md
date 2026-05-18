# Plan — `kaizen-lint` MCP server (ruff + ty)

## Status

**COMPLETE 2026-05-12** — landed in daddffd (v1.33.0). lint_mcp.py ships
all 7 tools; registered as the `lint` MCP server in `.mcp.json`.

## Goal

Add an MCP server `kaizen-lint` that exposes ruff (lint + format) and ty
(typecheck + explain) as Claude-callable tools, so Claude can run linters
mid-conversation without the user typing slash commands.

## Current state

- 8 MCP servers exist in `.mcp.json`. No lint/typecheck server.
- `ruff` v0.15.6 available on PATH; `ty` available via `uv run --with ty`.
- `state_mcp.py` is the canonical CLI-wrapping template (subprocess +
  structured dict returns; no embed-model deps).

## Invariants (must remain true)

1. Pre-deletion belief — this plan is additive only; no `rm`.
2. List-form `subprocess.run([cmd, args])` everywhere — no `shell=True`.
3. Stdlib-only inside the MCP server itself (mcp dep is the one external).
4. All `*_mcp.py` follow the same PEP 723 header shape so `uv run` works.
5. `.mcp.json` stays valid JSON; broken JSON breaks every kaizen MCP boot.

## Phases

### Phase 1 — server skeleton + ruff smoke

- [x] Create `plugins/kaizen/skills/workflow/scripts/lint_mcp.py`
- [x] PEP 723 header: `dependencies = ["mcp>=1.0"]` (no torch/sentence-transformers)
- [x] `FastMCP("kaizen-lint")` instance
- [x] `_run(cmd, cwd)` helper — subprocess.run wrapper returning `{exit_code, stdout, stderr}`
- [x] `_repo_root()` helper (mirror state_mcp.py)
- [x] First tool: `ruff_check(path=".", select="", ignore="", fix=False)` → parses `--output-format=json`
- **Verify:** `printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize",...}' | uv run --script lint_mcp.py` returns proper handshake naming `kaizen-lint`
- **Verify:** `tools/list` shows `ruff_check`

### Phase 2 — remaining ruff surface

- [x] `ruff_format(path=".", check=True, diff=False)` → `{would_format: [paths], exit_code, raw}`
- [x] `ruff_rules(category="")` → list of available rule codes (parses `ruff rule --output-format=json` or `ruff linter`)
- **Verify:** all 3 ruff tools callable via tools/list + handshake test

### Phase 3 — ty surface

- [x] `ty_check(path=".", error_on_warning=False, python_version="")` →
      runs `uv run --with ty -- ty check --output-format=concise <path>`,
      parses line-format into `{findings: [{file, line, col, severity, code, message}], exit_code, raw}`
- [x] `ty_explain(rule="")` → runs `ty explain rule [<name>] --output-format=json`,
      returns parsed JSON
- **Verify:** ty_check returns findings dict for a synthetic file with type errors
- **Verify:** ty_explain returns rule docs as structured JSON

### Phase 4 — composite tools (high-value for Claude)

- [x] `lint_path(path)` — fan out to ruff_check + ty_check in sequence,
      return `{ruff: {...}, ty: {...}, summary: {findings_count, severity_max}}`
- [x] `lint_changed_files(base_ref="HEAD")` — `git diff --name-only --diff-filter=AM <base>`,
      filter `.py`, then `lint_path` over each. Compact result.
- **Verify:** call `lint_changed_files()` against shodan repo; returns {} (no .py files there)
- **Verify:** call `lint_path("/tmp/synthetic_test_file.py")` returns combined ruff+ty findings

### Phase 5 — wire + register + smoke

- [x] Add `kaizen-lint` entry to `plugins/kaizen/.mcp.json`
- [x] Add `Bash(uv run --script ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/lint_mcp.py:*)` to plugin.json permissions
- [x] Refresh plugin cache (`/kaizen:refresh-cache` equivalent script)
- [x] Run MCP handshake smoke test:
      `init → notifications/initialized → tools/list` returns expected tool names
- **Verify:** `python3 _tests.py` still passes 48/48 (no regression)
- **Verify:** `bash health.sh` returns "healthy (no issues)"

## Verification commands (per phase)

```bash
# Per-phase MCP handshake smoke
printf '%s\n%s\n%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"1"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  | timeout 60 uv run --script plugins/kaizen/skills/workflow/scripts/lint_mcp.py \
  | python3 -c "import sys,json; [print(json.loads(l).get('result',{}).get('tools',[]) and 'OK') for l in sys.stdin if 'result' in l and 'tools' in l]"

# Regression
python3 plugins/kaizen/skills/workflow/scripts/_tests.py

# Cache refresh + reload-plugins
bash plugins/kaizen/skills/workflow/scripts/refresh-cache.sh
```

## Rollback

```bash
# Single-step undo
rm plugins/kaizen/skills/workflow/scripts/lint_mcp.py
# Revert .mcp.json + plugin.json:
git -C plugins/kaizen checkout -- .mcp.json .claude-plugin/plugin.json
/kaizen:refresh-cache && /reload-plugins
```

## Resume protocol

If a fresh session picks this up:
1. Read this plan top to bottom.
2. Check phase checkboxes for completion state.
3. The next unticked phase is the resume point.
4. Run the verify commands for the previous phase to confirm it actually
   landed (the checkbox could be stale from a prior session).
5. Proceed to the next phase.

## Anti-patterns to avoid

- Don't add caching at the MCP layer — each tool re-runs the binary. Linters
  are cheap; cache invalidation is harder than re-running.
- Don't wrap `--fix`/`--apply` modes silently — they mutate code. Expose
  them, but make the parameter explicit + default to non-mutating.
- Don't `shell=True`. Ever. Always list-form args.
- Don't parse ty's `concise` output rigidly — Astral has changed line
  formats before. Defensive parsing + always return raw `output` field.

## Open questions

- Should we add a `pyproject.toml`-aware `ruff_config()` tool that surfaces
  the effective rule set? Defer — YAGNI until requested.
- Should `lint_changed_files` also lint added but untracked .py files?
  Decision: yes (`git ls-files --others --exclude-standard | grep '\.py$'`).
