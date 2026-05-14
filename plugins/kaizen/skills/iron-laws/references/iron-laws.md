<!-- DO NOT HAND-EDIT.

Generated from skills/iron-laws/domain/iron-laws.yaml by
skills/iron-laws/application/codegen.py.

To change content, edit the yaml and run:
    python3 skills/iron-laws/application/codegen.py
or `kaizen-iron-laws render`. refresh-cache.sh runs codegen before sync.
-->

# Iron Laws

The non-negotiable rules for kaizen-plugin-original development. This file is a read-only copy of `skills/iron-laws/domain/iron-laws.yaml` (the single source of truth). `enforcement: auto` laws are machine-checked by `_iron_laws.py`; `manual` laws are listed + documented but not auto-checked.

## Summary

21 laws — 15 auto, 6 manual.

| id | severity | enforcement | check |
|---|---|---|---|
| `canonical-edit-path` | soft | manual | — |
| `no-modify-vendored` | hard | auto | `no_modify_vendored` |
| `schema-driven-domain` | soft | manual | — |
| `node-flow-for-multi-step` | soft | auto | `node_flow_for_multi_step` |
| `lazy-heavy-deps` | soft | auto | `lazy_heavy_deps` |
| `sandbox-tests` | hard | auto | `sandbox_tests` |
| `bin-wrapper-per-cli` | hard | auto | `bin_wrapper_per_cli` |
| `plugin-manifest-permissions` | hard | auto | `plugin_manifest_permissions` |
| `hook-bypass-knob` | hard | auto | `hook_bypass_knob` |
| `claude-md-no-volatile-data` | hard | auto | `claude_md_no_volatile_data` |
| `phased-commit-template` | soft | manual | — |
| `paired-tests` | soft | auto | `paired_tests` |
| `skill-cant-be-skipped` | soft | manual | — |
| `bin-wrapper-per-cli-strict` | hard | auto | `bin_wrapper_per_cli_strict` |
| `slash-command-args-no-default-spaces` | hard | auto | `slash_command_args_no_default_spaces` |
| `hooks-json-additive-event-multi-command` | soft | auto | `hooks_json_additive_event_multi_command` |
| `trace-coverage-all-tools` | soft | manual | — |
| `metrics-skip-check-before-merge` | soft | manual | — |
| `skill-md-no-exec-markers` | soft | auto | `skill_md_no_exec_markers` |
| `skill-md-no-external-script-paths` | soft | auto | `skill_md_no_external_script_paths` |
| `every-hook-script-traces-its-firing` | soft | auto | `every_hook_script_traces_its_firing` |

## Laws

### `canonical-edit-path` (soft · manual)

Edit at ~/workspace/kaizen-md/, never the symlink ~/.claude/local-marketplaces/kaizen-md/

**Detect:** modified-file path starts with ~/.claude/local-marketplaces/kaizen-md/

**Why:** User stated preference; symlink confuses git status / IDE search / path-canonicalization helpers. See ~/.claude/projects/<slug>/memory/feedback_kaizen_plugin_canonical_path.md. Manual: the checker sees only repo-relative git paths — it cannot tell which path the agent edited through.

### `no-modify-vendored` (hard · auto)

Don't modify vendored skills. Patch upstream first, then refresh via bundle-refresh.

**Check:** `no_modify_vendored` (in `_iron_laws.py`)

**Detect:** modified file in skills/{kiss,solid,dry,yagni,karpathy,boy-scout-rule,convention-over-configuration,law-of-demeter,separation-of-concerns,brainstorming,executing-plans,writing-plans,using-superpowers,subagent-driven-development,test-driven-development,verification-before-completion,dispatching-parallel-agents,finishing-a-development-branch,using-git-worktrees,writing-skills,receiving-code-review,requesting-code-review,systematic-debugging,tdd,init,remember,process,evolve,reflect,synthesize,status}/

**Why:** Upstream provenance. See CONTRIBUTING.md::Architecture rules and ATTRIBUTIONS.md.

### `schema-driven-domain` (soft · manual)

Feature routing / taxonomies / conventions live in domain/*.yaml — not hardcoded in Python.

**Detect:** feature has hardcoded route table without corresponding domain/*.yaml

**Why:** Users edit yaml without rebuilding; tests validate against jsonschema. Manual: 'hardcoded route table' has no reliable mechanical signature.

### `node-flow-for-multi-step` (soft · auto)

Multi-step async ops use flow.AsyncNode + AsyncFlow. No ad-hoc orchestration.

**Check:** `node_flow_for_multi_step` (in `_iron_laws.py`)

**Detect:** module imports asyncio.gather more than once without subclassing AsyncParallelBatchNode

**Why:** Consistent observability + retry/cycle guards; see skills/workflow/scripts/flow.py docstring.

### `lazy-heavy-deps` (soft · auto)

Heavy deps (transformers, torch, tree-sitter, etc.) lazy-load with is_available() + graceful fallback.

**Check:** `lazy_heavy_deps` (in `_iron_laws.py`)

**Detect:** top-level `import torch` or `import transformers` outside try/except

**Why:** Default kaizen install must not require ~3GB ML stack. See ~/.claude/brain/Notes/pref-optional-feature-graceful-fallback.md

### `sandbox-tests` (hard · auto)

Tests sandbox via env vars (KAIZEN_<X>_PATH=<tmp>). Never touch real ~/.claude/.

**Check:** `sandbox_tests` (in `_iron_laws.py`)

**Detect:** test file writes to ~/.claude/ or ~/workspace/ without KAIZEN_<X>_PATH override

**Why:** Test isolation; CI runs without polluting the user's brain or auto-memory.

### `bin-wrapper-per-cli` (hard · auto)

Each CLI script gets its own bin/kaizen-* wrapper. /kaizen:install symlinks bin/ into ~/.local/bin/.

**Check:** `bin_wrapper_per_cli` (in `_iron_laws.py`)

**Detect:** skills/workflow/scripts/<feature>_<op>.py with argparse main but no bin/kaizen-<feature>-<op>

**Why:** Without a wrapper, kaizen-<feature>-<op> is 'command not found' from shell. See brain commit 2cfd234 + bin-wrapper hotfix.

### `plugin-manifest-permissions` (hard · auto)

New script + hook entries land with matching plugin.json permission lines in the same commit.

**Check:** `plugin_manifest_permissions` (in `_iron_laws.py`)

**Detect:** git diff shows new skills/workflow/scripts/<feature>.py or hooks/claude/<feature>-*.sh without matching plugin.json::permissions.allow entry

**Why:** Missing permission entries prompt the user on every invocation; structural cohesion.

### `hook-bypass-knob` (hard · auto)

Every hook script reads KAIZEN_<FEATURE>_DISABLE env early and exits 0 when set.

**Check:** `hook_bypass_knob` (in `_iron_laws.py`)

**Detect:** hooks/claude/<feature>-*.sh missing `KAIZEN_*_DISABLE` guard

**Why:** User must be able to disable any hook without uninstalling the plugin.

### `claude-md-no-volatile-data` (hard · auto)

Don't write commit SHAs, dates, or LOC counts into CLAUDE.md / README.md. Use CHANGELOG / git log / progress.md.

**Check:** `claude_md_no_volatile_data` (in `_iron_laws.py`)

**Detect:** claude-md-no-sha gate check

**Why:** CLAUDE.md is the durable rulebook; volatile data rots. Overlaps a git-discipline.yaml pre-commit gate — that gate defers here so the law is defined + checked in one place.

### `phased-commit-template` (soft · manual)

Atomic per-item commit using the phased-work template (subject / motivation / Files / env / test baseline / refs).

**Detect:** git commit message length < 200 chars on a structural change

**Why:** Phased commits read as a coherent rollout in git log. See ~/.claude/brain/Notes/pref-phased-work-commit-template.md. Manual: needs the commit message, which the pre-commit hook does not have (the commit-msg hook is the right home).

### `paired-tests` (soft · auto)

Every new .py / .sh script in plugin-original code has a matching test in tests/test_<x>.py.

**Check:** `paired_tests` (in `_iron_laws.py`)

**Detect:** git diff adds skills/workflow/scripts/<f>.py without adding/modifying tests/test_<f>*.py

**Why:** Existing gate check (paired-test, severity=warn). See workflow skill PART 3. Overlaps a git-discipline.yaml pre-commit gate — that gate defers here so the law is defined + checked in one place.

### `skill-cant-be-skipped` (soft · manual)

When touching plugin-original code, the plugin-development skill is mandatory-load.

**Detect:** session enters kaizen-md cwd without plugin-development in loaded-skills

**Why:** User stated: 'the dev skill can't be skipped' — codified 2026-05-14. Manual: needs session state (which skills were loaded) — not visible to a file/diff checker.

### `bin-wrapper-per-cli-strict` (hard · auto)

Every Python script with an argparse main() under skills/workflow/scripts/ MUST have a matching bin/kaizen-* wrapper landed in the SAME commit. Specialized op scripts (e.g. brain_index.py / brain_promote.py / metrics.py) need their own wrappers — one bin per CLI script.

**Check:** `bin_wrapper_per_cli_strict` (in `_iron_laws.py`)

**Detect:** git diff shows new skills/workflow/scripts/<f>.py with `if __name__ == "__main__"` + argparse but no bin/kaizen-<feature>[-<op>] in the same commit

**Why:** Hit twice this session: brain shipped only kaizen-brain (missing -index/-promote/-audit/-evolve, fixed in commit ed4b490); metrics shipped only kaizen-metrics. /kaizen:install symlinks bin/ entries into ~/.local/bin/, so a missing wrapper = 'command not found' from shell. The plugin-development validator's wiring-checklist enforces this via scripts/validate.py.

### `slash-command-args-no-default-spaces` (hard · auto)

Slash command `${ARGUMENTS:-default}` template only bash-evaluates the `:-default` when the default has NO whitespace. For multi-word defaults, give the underlying script a no-arg fallback and pass bare `$ARGUMENTS` (no curly braces, no default).

**Check:** `slash_command_args_no_default_spaces` (in `_iron_laws.py`)

**Detect:** commands/<feature>.md contains `${ARGUMENTS:-<default with spaces>}`

**Why:** Hit on /kaizen:metrics — user ran `top --kind skill`, slash dispatched `lifetime --since 7d` (the bash default fell through because CC's template substitution + bash interaction couldn't handle the space). Fixed by giving metrics.py a no-arg default (runs 7d lifetime) and changing slash to bare `$ARGUMENTS`. See onboard.md / trace-search.md for short-default examples that work.

### `hooks-json-additive-event-multi-command` (soft · auto)

When adding a hook to an ADDITIVE_EVENT (SubagentStop / SessionEnd / Notification) that already has a config block, APPEND to the existing block's `hooks:[]` list — don't add a sibling block with the same matcher.

**Check:** `hooks_json_additive_event_multi_command` (in `_iron_laws.py`)

**Detect:** hooks.json::<EVENT> has 2+ config blocks with matcher='*'

**Why:** test_cc_hooks_wireup.py originally asserted exactly 1 config block per ADDITIVE_EVENT. Relaxed 2026-05-14 to allow >= 1 commands, but the convention is still to append within one block for the same matcher.

### `trace-coverage-all-tools` (soft · manual)

Hook scripts that fire on PreToolUse / PostToolUse should cover ALL tools (matcher='*'), not just Bash. The universal pretooluse-trace.sh / posttooluse-trace.sh fire for Skill / Edit / Write / mcp__* / etc. — don't add per-tool hooks that re-trace what the universal already captures.

**Detect:** new hook script in hooks/claude/ fires `_trace.sh` with a tool name already covered by the universal hooks

**Why:** Until M1 (2026-05-14), only Bash had trace coverage. 30K events captured, 0 skill invocations. The universal trace fixed it; new hooks should rely on it for tool-call traces, not re-add per-tool tracing. Manual: 'a tool name already covered' requires semantic analysis of hook intent.

### `metrics-skip-check-before-merge` (soft · manual)

Before merging any structural change touching plugin-original code, run `kaizen-metrics skips --json` to confirm no mandatory-skill-load was missed.

**Detect:** session touched plugins/kaizen/** files without `Skill(plugin-development)` invocation; surfaced via metrics-session-end.sh hook

**Why:** Self-correction signal. The SessionEnd hook auto-writes drafts to brain/Inbox/; surfacing the same check pre-merge catches violations before they ship. Manual: needs session trace state, not a file/diff.

### `skill-md-no-exec-markers` (soft · auto)

Don't put a `!`-backtick exec marker in a SKILL.md body. The Skill tool executes them at skill-load time. Document slash-command bodies as PROSE or INDENTED plain-text blocks — never as `!`-backtick markup, fenced or not. Fence-type matters and is fragile: a ```bash fence did NOT protect the marker (it ran + errored); a ```markdown fence appeared to. Don't rely on that — just don't use the marker.

**Check:** `skill_md_no_exec_markers` (in `_iron_laws.py`)

**Detect:** skills/<feature>/SKILL.md contains `!` immediately followed by a backtick (any column, any fence)

**Why:** Hit 2026-05-14: loading Skill(plugin-development) errored — its SKILL.md had `!`bash -c '...'`` examples inside a ```bash fence that the loader ran anyway (the literal `...` in the example then failed as a command). plugin-pitfalls documents the same gotcha but keeps its example inside a ```markdown fence which apparently didn't fire — fragile. SKILL.md is documentation; only commands/*.md files carry live exec markers.

### `skill-md-no-external-script-paths` (soft · auto)

A SKILL.md must not invoke a script or interpreter from OUTSIDE the plugin — no `~/.claude/scripts/...`, no `.venv/bin/python` that isn't under ${CLAUDE_PLUGIN_ROOT}. The skill ships to users who don't have your personal ~/.claude/ setup; an unshipped external dependency makes the skill structurally broken for everyone but the author. Reading/writing DATA under ~/.claude/ (a handoff YAML, ~/.claude/brain/) is fine — this law is about EXECUTING unshipped code. If a SKILL.md genuinely needs such a path, guard it (`if [ -f <path> ]; then ... else <graceful skip> fi`) and make the in-plugin path the system of record.

**Check:** `skill_md_no_external_script_paths` (in `_iron_laws.py`)

**Detect:** skills/<feature>/SKILL.md bash block invokes ~/.claude/scripts/ or a .venv/bin/python not under ${CLAUDE_PLUGIN_ROOT}, unguarded by an existence check

**Why:** Hit 2026-05-14: kaizen:handoff steps 3/4 + resume Mode C hard-invoked ~/.claude/scripts/.venv/bin/python3 importing ~/.claude/scripts/stores.py — neither shipped with the plugin, neither present anywhere on the system. The DB step exit-127'd mid-flow; the handoffs table had 0 rows (the skill had NEVER worked for anyone without the author's personal setup). Vendored at v1.33.0 (daddffd) without porting the dependency — the 'lifted ad-hoc, dependency not ported' anti-pattern. Fix: DB persistence made conditional on stores.py existing; the filesystem YAML is the system of record.

### `every-hook-script-traces-its-firing` (soft · auto)

Every hook script in hooks/claude/ MUST fire `_trace.sh` (or `trace.py event`) so its lifecycle is visible to kaizen-metrics. The universal pretooluse/posttooluse trace covers TOOL calls; hook-internal firing needs its own trace line.

**Check:** `every_hook_script_traces_its_firing` (in `_iron_laws.py`)

**Detect:** hooks/claude/<f>.sh (excluding _trace.sh itself) with no `_trace.sh` / `trace.py event` reference

**Why:** Self-audit's hook-trace-coverage stage flags these. Pre-fix, brain-session-end / brain-user-prompt / karpathy-gate / metrics-session-end / stop-ralph fired invisibly — no signal that the hook ran. Fixed 2026-05-14 (commit 691944f).

