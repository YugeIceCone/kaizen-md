# Tasks — `kaizen-lint` MCP server

Plan: `plans/2026-05-12-kaizen-lint-mcp.md`. One task per phase. Each task
exits with the phase's verify command passing.

---

## T1 — Server skeleton + `ruff_check` tool

**File:** `plugins/kaizen/skills/workflow/scripts/lint_mcp.py` (new, ~80 LOC)

**Brief:**
- PEP 723 header: `requires-python = ">=3.10"`, `dependencies = ["mcp>=1.0"]`
- Imports: `subprocess`, `json`, `os`, `sys`, `shutil`, `pathlib.Path`
- `mcp = FastMCP("kaizen-lint")`
- Helper `_repo_root() -> str` (subprocess git rev-parse, fallback cwd)
- Helper `_run(cmd: list[str], cwd: str | None = None, timeout: int = 60) -> dict` returning `{exit_code, stdout, stderr}`
- Tool `ruff_check(path=".", select="", ignore="", fix=False)`:
  - cmd = `["ruff", "check", "--output-format=json"]`
  - if `select`: `+ ["--select", select]`
  - if `ignore`: `+ ["--ignore", ignore]`
  - if `fix`: `+ ["--fix"]`
  - `+ [path]`
  - Run, try `json.loads(stdout)`, fall through to `{"raw_stdout": ..., "parse_error": str(e)}` on failure
  - Return `{exit_code, findings, raw?}`
- `if __name__ == "__main__": mcp.run()`

**Verify:**
```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"s","version":"1"}}}' \
  | timeout 30 uv run --script plugins/kaizen/skills/workflow/scripts/lint_mcp.py 2>/dev/null \
  | python3 -c "import sys,json; d=json.loads(sys.stdin.read().splitlines()[0]); assert d['result']['serverInfo']['name'] == 'kaizen-lint'; print('OK')"
```

**Pass:** prints "OK". Server boots, returns `kaizen-lint` as server name.

---

## T2 — `ruff_format` + `ruff_rules` tools

**File:** same; append tools.

**Brief:**
- `ruff_format(path=".", check=True, diff=False)`:
  - cmd = `["ruff", "format"]`
  - if `check`: `+ ["--check"]`
  - if `diff`: `+ ["--diff"]`
  - `+ [path]`
  - parse stdout for "Would reformat: <file>" / "Would format: <file>" lines
  - return `{exit_code, would_format: [paths], diff_output?: str}`
- `ruff_rules(category="")`:
  - cmd = `["ruff", "rule", "--all", "--output-format=json"]`
  - parse `json.loads(stdout)`
  - if `category`: filter rows where `code.startswith(category)` (e.g., "E", "W", "F")
  - return list of `{code, name, short_msg, linter}`

**Verify:**
```bash
# tools/list shows all 3 ruff tools
printf '%s\n%s\n%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"s","version":"1"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  | timeout 30 uv run --script plugins/kaizen/skills/workflow/scripts/lint_mcp.py 2>/dev/null \
  | python3 -c "import sys,json
for line in sys.stdin:
    d=json.loads(line)
    if d.get('id')==2:
        names={t['name'] for t in d['result']['tools']}
        assert {'ruff_check','ruff_format','ruff_rules'}.issubset(names), names
        print('OK')
        break"
```

---

## T3 — `ty_check` + `ty_explain` tools

**File:** same; append.

**Brief:**
- `ty_check(path=".", error_on_warning=False, python_version="")`:
  - cmd = `["uv", "run", "--with", "ty", "--", "ty", "check", "--output-format=concise"]`
  - if `python_version`: `+ ["--python-version", python_version]`
  - if `error_on_warning`: `+ ["--error-on-warning"]`
  - `+ [path]`
  - Parse `concise` format: `<file>:<line>:<col>: <severity>: [<code>] <msg>` (defensive: split on `:` with maxsplit; on parse failure, keep raw line).
  - return `{exit_code, findings: [{file, line, col, severity, code, message}], raw_lines: [...]}`
- `ty_explain(rule="")`:
  - cmd = `["uv", "run", "--with", "ty", "--", "ty", "explain", "rule"]`
  - if `rule`: `+ [rule]`
  - `+ ["--output-format=json"]`
  - return `json.loads(stdout)`

**Verify:**
```bash
# Synthetic typed file with a known type error
mkdir -p /tmp/ty-smoke && cat > /tmp/ty-smoke/bad.py <<'EOF'
def add(x: int, y: int) -> int:
    return x + y
add("hello", 1)
EOF
# Hand-test the tool body (not via MCP) — quickest validation
python3 -c "
import sys; sys.path.insert(0, 'plugins/kaizen/skills/workflow/scripts')
import lint_mcp, asyncio
r = asyncio.run(lint_mcp.ty_check('/tmp/ty-smoke/bad.py'))
print(r)
assert r['exit_code'] == 1, r
assert any('add' in str(f) for f in r.get('findings', []) + r.get('raw_lines', [])), r
print('OK')
"
rm -rf /tmp/ty-smoke
```

---

## T4 — Composite tools: `lint_path` + `lint_changed_files`

**File:** same; append.

**Brief:**
- `lint_path(path)`:
  - call `ruff_check(path)` then `ty_check(path)`
  - return `{ruff: <ruff_check result>, ty: <ty_check result>, summary: {total_findings: int, max_severity: str}}`
  - severity rank: error > warning > info > none
- `lint_changed_files(base_ref="HEAD", include_untracked=True)`:
  - git changed: `git diff --name-only --diff-filter=AM <base_ref>`
  - if include_untracked: also `git ls-files --others --exclude-standard`
  - filter `.py$`
  - if empty: return `{files: [], findings: {}}`
  - for each file, call ruff_check + ty_check; aggregate
  - return `{files: [paths], findings: {<path>: {ruff, ty}}, summary}`

**Verify:**
```bash
# In a clean python project (shodan has no .py — try the kaizen plugin itself)
cd /home/cherry86/.claude/local-marketplaces/kaizen-md
python3 -c "
import sys, asyncio
sys.path.insert(0, 'plugins/kaizen/skills/workflow/scripts')
import lint_mcp
# lint a known good kaizen script (should produce few findings)
r = asyncio.run(lint_mcp.lint_path('plugins/kaizen/skills/workflow/scripts/_blobs.py'))
print('exit_codes: ruff=', r['ruff']['exit_code'], 'ty=', r['ty']['exit_code'])
print('total findings:', r['summary']['total_findings'])
print('OK')
"
```

---

## T5 — Register in `.mcp.json` + permissions + smoke

**Files:**
- `plugins/kaizen/.mcp.json` (modify)
- `plugins/kaizen/.claude-plugin/plugin.json` (modify permissions)

**Brief:**
- Add `kaizen-lint` entry to `.mcp.json`:
  ```json
  "kaizen-lint": {
    "command": "uv",
    "args": ["run", "--script", "${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/lint_mcp.py"]
  }
  ```
- Add to `plugin.json` permissions allow:
  ```
  "Bash(uv run --script ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/lint_mcp.py:*)"
  ```
- Refresh cache + reload-plugins (cache script handles rsync)

**Verify:**
```bash
# 1. json parses
python3 -c "import json; json.load(open('plugins/kaizen/.mcp.json'))"
python3 -c "import json; json.load(open('plugins/kaizen/.claude-plugin/plugin.json'))"
# 2. full MCP handshake — server boots + lists all 7 tools
printf '%s\n%s\n%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"s","version":"1"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  | timeout 60 uv run --script plugins/kaizen/skills/workflow/scripts/lint_mcp.py 2>/dev/null \
  | python3 -c "import sys,json
for line in sys.stdin:
    d=json.loads(line)
    if d.get('id')==2:
        names=[t['name'] for t in d['result']['tools']]
        expected={'ruff_check','ruff_format','ruff_rules','ty_check','ty_explain','lint_path','lint_changed_files'}
        assert set(names) >= expected, set(names) ^ expected
        print(f'OK — {len(names)} tools: '+', '.join(names))
        break"
# 3. existing tests still green
python3 plugins/kaizen/skills/workflow/scripts/_tests.py
# 4. health
cd /home/cherry86/workspace/shodan && bash /home/cherry86/.claude/local-marketplaces/kaizen-md/plugins/kaizen/skills/workflow/scripts/health.sh 2>&1 | tail -1
```

**Pass:**
- All JSON files parse
- MCP handshake returns 7 tool names
- `_tests.py` says `Ran 48 tests` ... `OK`
- health: `Result: healthy (no issues)`

---

## Per-task discipline (kaizen Iron Laws)

1. Compile-barrier per task: `python3 -m py_compile lint_mcp.py` between T1–T4 edits
2. Commit after each passing task (when the user authorizes commits)
3. No batching commits across tasks
4. If a task fails verify: STOP, surface details, don't proceed
