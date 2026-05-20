<!-- DO NOT HAND-EDIT.

Generated from skills/iron-laws/domain/iron-laws.yaml by
skills/iron-laws/application/codegen.py.

To change content, edit the yaml and run `kaizen-iron-laws render`
(or this file directly). CI runs `codegen.py --check` to fail the
build if this file ever drifts from the yaml.
-->

# Iron Laws

The non-negotiable rules for kaizen-plugin-original development. This file is a read-only copy of `skills/iron-laws/domain/iron-laws.yaml` (the single source of truth). `enforcement: auto` laws are machine-checked by `_iron_laws.py`; `manual` laws are listed + documented but not auto-checked.

## Summary

34 laws — 20 auto, 14 manual.

| id | severity | enforcement | check |
|---|---|---|---|
| `canonical-edit-path` | soft | manual | — |
| `no-modify-vendored` | hard | auto | `no_modify_vendored` |
| `schema-driven-domain` | soft | manual | — |
| `node-flow-for-multi-step` | soft | auto | `node_flow_for_multi_step` |
| `lazy-heavy-deps` | soft | auto | `lazy_heavy_deps` |
| `sandbox-tests` | hard | auto | `sandbox_tests` |
| `bin-wrapper-per-cli` | hard | auto | `bin_wrapper_per_cli` |
| `cli-naming-consistency` | soft | auto | `cli_naming_consistency` |
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
| `brain-note-schema` | hard | auto | `brain_note_schema` |
| `brain-rule-schema` | hard | auto | `brain_rule_schema` |
| `starter-no-personal-data` | hard | auto | `starter_no_personal_data` |
| `brain-no-orphan-toplevel` | hard | auto | `brain_no_orphan_toplevel` |
| `append-only-sink` | soft | manual | — |
| `drift-resilient-config-read` | soft | manual | — |
| `prcdr-contract-declared` | soft | manual | — |
| `cross-device-safe-move` | hard | manual | — |
| `cli-json-flag` | soft | manual | — |
| `shim-and-sweep` | hard | manual | — |
| `dry-extract-on-third-repetition` | soft | manual | — |
| `flake-audit-load-before-logic` | soft | manual | — |

## Laws

### `canonical-edit-path` (soft · manual)

Edit at ~/workspace/kaizen-md/, never the symlink ~/.claude/local-marketplaces/kaizen-md/

**Detect:** modified-file path starts with ~/.claude/local-marketplaces/kaizen-md/

**Why:** User stated preference; symlink confuses git status / IDE search / path-canonicalization helpers. See ~/.claude/projects/<slug>/memory/feedback_kaizen_plugin_canonical_path.md. Manual: the checker sees only repo-relative git paths — it cannot tell which path the agent edited through.

### `no-modify-vendored` (hard · auto)

Don't modify actively-vendored skills. Patch upstream first, then refresh. (Currently no skills are vendored — list is empty after the 2026-05-17 retirement; see CHANGELOG. Law retained as infrastructure for any future upstream-tracked content.)

**Check:** `no_modify_vendored` (in `_iron_laws.py`)

**Detect:** modified file in skills/<vendored-skill>/ — vendored list is currently empty

**Why:** Upstream provenance. The originally-bundled skills from coding-skills / superpowers / claude-code-skills / remember have been retired from active upstream-tracking after extensive kaizen-local alterations; they are now plugin-original derivatives. Original-author attribution preserved in ATTRIBUTIONS.md.

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

**Why:** Default kaizen install must not require ~3GB ML stack. See ~/.claude/.kaizen/brain/Notes/pref-optional-feature-graceful-fallback.md

### `sandbox-tests` (hard · auto)

Tests sandbox via env vars (KAIZEN_<X>_PATH=<tmp>). Never touch real ~/.claude/.

**Check:** `sandbox_tests` (in `_iron_laws.py`)

**Detect:** test file writes to ~/.claude/ or ~/workspace/ without KAIZEN_<X>_PATH override

**Why:** Test isolation; CI runs without polluting the user's brain or auto-memory.

### `bin-wrapper-per-cli` (hard · auto)

Each CLI script gets its own bin/kaizen-* wrapper. /kaizen:setup symlinks bin/ into ~/.local/bin/. EXCEPTION: a script that declares `# consolidated-cli-parent: <name>` in its header transfers the wrapper requirement to the named parent's bin (lets brain_audit/evolve/index/promote/migrate live under `kaizen-brain <verb>` without 5 separate wrappers).

**Check:** `bin_wrapper_per_cli` (in `_iron_laws.py`)

**Detect:** skills/workflow/scripts/<feature>_<op>.py with argparse main but no bin/kaizen-<feature>-<op> AND no `# consolidated-cli-parent: <X>` header pointing at an existing bin/kaizen-<X>

**Why:** Without a wrapper, kaizen-<feature>-<op> is 'command not found' from shell. See brain commit 2cfd234 + bin-wrapper hotfix. The consolidated-CLI exemption (v1.40+) lets multi-verb tools collapse to one wrapper without losing iron-law coverage.

### `cli-naming-consistency` (soft · auto)

When a CLI script ships both `argparse.ArgumentParser(prog="...")` and `_envelope.emitter("...", ...)`, the two values must agree. They are two surfaces of the same tool name (one for --help, one for trace events); silent disagreement after a rename means --help prints one name and trace events carry another. Captures the 3-way naming-drift class (bin / prog / emitter) at the prog↔emitter axis; bin↔prog enforcement is reserved for a stricter follow-up after pre-existing drift is cleaned up.

**Check:** `cli_naming_consistency` (in `_iron_laws.py`)

**Detect:** any plugins/kaizen/scripts/**/*.py (non-underscore) with both an `ArgumentParser(prog="X")` literal AND an `_envelope.emitter("Y", ...)` literal where X != Y

**Why:** Surfaced 2026-05-20: 7 internal-disagreement files (docs_flow / index_flow / search_flow / observe / trace / config / loop_state) had `prog="<file>.py"` literals while their emitters carried the proper `kaizen-<feature>` tool-name. --help printed the raw filename; trace events carried the canonical name; the two disagreed silently. See [[Notes/pref-3-way-naming-drift-class]]. Soft severity intentional — pre-existing drift is real; this law surfaces it without breaking the gate until the cleanup PR lands.

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

**Why:** Phased commits read as a coherent rollout in git log. See ~/.claude/.kaizen/brain/Notes/pref-phased-work-commit-template.md. Manual: needs the commit message, which the pre-commit hook does not have (the commit-msg hook is the right home).

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

Every Python script with an argparse main() under skills/workflow/scripts/ MUST have a matching bin/kaizen-* wrapper landed in the SAME commit. Specialized op scripts (e.g. build_index.py / brain_promote.py / metrics.py) need their own wrappers — one bin per CLI script.

**Check:** `bin_wrapper_per_cli_strict` (in `_iron_laws.py`)

**Detect:** git diff shows new skills/workflow/scripts/<f>.py with `if __name__ == "__main__"` + argparse but no bin/kaizen-<feature>[-<op>] in the same commit

**Why:** Hit twice this session: brain shipped only kaizen-brain (missing -index/-promote/-audit/-evolve, fixed in commit ed4b490); metrics shipped only kaizen-metrics. /kaizen:setup symlinks bin/ entries into ~/.local/bin/, so a missing wrapper = 'command not found' from shell. The plugin-development validator's wiring-checklist enforces this via scripts/validate.py.

### `slash-command-args-no-default-spaces` (hard · auto)

Slash command `${ARGUMENTS:-default}` template only bash-evaluates the `:-default` when the default has NO whitespace. For multi-word defaults, give the underlying script a no-arg fallback and pass bare `$ARGUMENTS` (no curly braces, no default).

**Check:** `slash_command_args_no_default_spaces` (in `_iron_laws.py`)

**Detect:** commands/<feature>.md contains `${ARGUMENTS:-<default with spaces>}`

**Why:** Hit on kaizen-metrics — user ran `top --kind skill`, slash dispatched `lifetime --since 7d` (the bash default fell through because CC's template substitution + bash interaction couldn't handle the space). Fixed by giving metrics.py a no-arg default (runs 7d lifetime) and changing slash to bare `$ARGUMENTS`. See onboard.md / trace-search.md for short-default examples that work.

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

A SKILL.md must not invoke a script or interpreter from OUTSIDE the plugin — no `~/.claude/scripts/...`, no `.venv/bin/python` that isn't under ${CLAUDE_PLUGIN_ROOT}. The skill ships to users who don't have your personal ~/.claude/ setup; an unshipped external dependency makes the skill structurally broken for everyone but the author. Reading/writing DATA under ~/.claude/ (a handoff YAML, ~/.claude/.kaizen/brain/) is fine — this law is about EXECUTING unshipped code. If a SKILL.md genuinely needs such a path, guard it (`if [ -f <path> ]; then ... else <graceful skip> fi`) and make the in-plugin path the system of record.

**Check:** `skill_md_no_external_script_paths` (in `_iron_laws.py`)

**Detect:** skills/<feature>/SKILL.md bash block invokes ~/.claude/scripts/ or a .venv/bin/python not under ${CLAUDE_PLUGIN_ROOT}, unguarded by an existence check

**Why:** Hit 2026-05-14: kaizen:handoff steps 3/4 + resume Mode C hard-invoked ~/.claude/scripts/.venv/bin/python3 importing ~/.claude/scripts/stores.py — neither shipped with the plugin, neither present anywhere on the system. The DB step exit-127'd mid-flow; the handoffs table had 0 rows (the skill had NEVER worked for anyone without the author's personal setup). Vendored at v1.33.0 (daddffd) without porting the dependency — the 'lifted ad-hoc, dependency not ported' anti-pattern. Fix: DB persistence made conditional on stores.py existing; the filesystem YAML is the system of record.

### `every-hook-script-traces-its-firing` (soft · auto)

Every hook script in hooks/claude/ MUST fire `_trace.sh` (or `trace.py event`) so its lifecycle is visible to kaizen-metrics. The universal pretooluse/posttooluse trace covers TOOL calls; hook-internal firing needs its own trace line.

**Check:** `every_hook_script_traces_its_firing` (in `_iron_laws.py`)

**Detect:** hooks/claude/<f>.sh (excluding _trace.sh itself) with no `_trace.sh` / `trace.py event` reference

**Why:** Self-audit's hook-trace-coverage stage flags these. Pre-fix, brain-session-end / brain-user-prompt / karpathy-gate / metrics-session-end / stop-ralph fired invisibly — no signal that the hook ran. Fixed 2026-05-14 (commit 691944f).

### `brain-note-schema` (hard · auto)

Every starter Note (`assets/starters/*/Notes/*.md`) has YAML frontmatter with at least `name:` + `type:` (type in the canonical enum). `type: belief` requires `confidence:` so beliefs can graduate to Persona Top Beliefs.

**Check:** `brain_note_schema` (in `_iron_laws.py`)

**Detect:** Notes/*.md frontmatter missing required keys, OR `type` value not in {world-fact, belief, observation, experience, behaviour, persona}, OR `type: belief` without a `confidence:` field

**Why:** The promote / evolve / index flows depend on these fields. Notes shipped in starters set the example; an unset `type` ripples to every user who seeds from that starter. The note.schema.json says it; this law enforces it on the canonical starters.

### `brain-rule-schema` (hard · auto)

Starter Notes with a `kaizen:` frontmatter block (rule notes) declare a valid `rule_type` and supply the type-specific required fields (path_glob for deletion-allow, check_id+severity for check-severity, etc).

**Check:** `brain_rule_schema` (in `_iron_laws.py`)

**Detect:** Note with `kaizen:` block whose `rule_type` isn't in {deletion-allow, check-severity, custom-pattern, dependency-allowlist}, OR is missing the rule-type's required fields per brain-rule.schema.json

**Why:** Malformed kaizen-rule notes silently skip at runtime — the gate never blocks `git rm` on a path the rule MEANT to allow. Catch at commit time, not at the user's frustrating moment.

### `starter-no-personal-data` (hard · auto)

Files under `assets/starters/**/*.md` must not contain personal identifiers (usernames like cherry86, email addresses, specific workspace names like 'shodan workspace'). Generic placeholders (`<your project>`, `~/<user>/`) are allowed.

**Check:** `starter_no_personal_data` (in `_iron_laws.py`)

**Detect:** Regex sweep for /cherry86/, /@(gmail|anthropic|hotmail|outlook|yahoo)\.com/, /\bshodan workspace\b/ across assets/starters/**/*.md

**Why:** Starters get distributed to every new user. A leaked maintainer username in the seeded brain is both privacy-leakage and a discoverability bug ('why is cherry86 in my brain?'). Caught manually during the 2026-05-17 yugecone→kaizen sanitization pass; lifted to law to prevent regression.

### `brain-no-orphan-toplevel` (hard · auto)

Starter root dir contains only the PARA dirs (Inbox / Journal / Projects / People / Areas / Notes / Resources / Tasks / Templates / Archive) and sanctioned top-level files (Persona.md / REMEMBER.md / SessionNotes.md / README.md / brain.db). Stray files signal accumulation drift.

**Check:** `brain_no_orphan_toplevel` (in `_iron_laws.py`)

**Detect:** Entry in assets/starters/<name>/ that isn't in the sanctioned set

**Why:** When a starter accumulates `scratch.md` / `oldidea.md` / `temp/` cruft, new users seed those too. The PARA convention is THE brain UX — drift here erodes the value of every downstream brain.

### `append-only-sink` (soft · manual)

Structured-event sinks (progress.md rows, learn log, observer events.jsonl, patch journal, etc.) NEVER read the existing file — open with 'a' mode + write one line; constant-cost append regardless of sink size.

**Detect:** Module that writes to a *.jsonl / *.md / *.log file uses read() before write — should use open(path, 'a').

**Why:** Read-then-Edit costs ~2KB context per row + 2 tool calls. Proven canonical CLIs (kaizen-progress, kaizen-learn, kaizen-observer, kaizen-bundle patch-journal) all follow append-only. Test pattern: seed 50KB log, append one row, assert size-delta < N bytes (the row size) — see test_append_cost_constant in test_progress_log.py.

### `drift-resilient-config-read` (soft · manual)

Config / rules / schema files that drive runtime behavior are RE-READ from disk on every evaluation — never cached in-memory.

**Detect:** Loader fn cached with @lru_cache or module-level dict; rule/schema loaded once at import time and reused for many evaluations.

**Why:** Counter to the cache-pinning bug class — kaizen-implementer 9b29d3d landed because agent tools list was pinned at session start; mid-session edits to the disk file silently didn't take effect. Observer rules engine + ingest module both re-load source per call. Proven via test_rules_reloaded_per_eval + test_load_schema_called_per_event.

### `prcdr-contract-declared` (soft · manual)

Every new public-API module declares the 5-property contract (PROGRAMMABLE / REPRODUCIBLE / CONSISTENT / DETERMINISTIC / REUSABLE) in its module docstring.

**Detect:** Module under skills/workflow/scripts/ exporting a CLI or pure-function API lacks the 5-property contract block.

**Why:** User directive 2026-05-18 — 'programmable, reproducible, consistent, deterministic, reusable'. Declaring the contract per-module makes design intent reviewable + reusable across features. Pattern: every new kaizen-* surface this session (progress, learn, observer-events, bundle) declares the contract; readers verify each property via the named tests.

### `cross-device-safe-move` (hard · manual)

File-move operations use shutil.move, NOT Path.rename — Path.rename raises OSError(EXDEV) across filesystems (tmpfs → home, etc.).

**Detect:** Module under skills/workflow/scripts/ or hooks/claude/ uses Path.rename or os.rename for paths that might span filesystems.

**Why:** Caught via live smoke in kaizen-bundle add: /tmp (tmpfs) → ~/workspace (home fs) move failed with OSError(EXDEV) when implemented as src.rename(target). shutil.move handles the fallback (copy + delete) transparently. Universally safer for cross-mount user workflows.

### `cli-json-flag` (soft · manual)

Every CLI subcommand that produces structured output offers a `--json` flag returning canonical JSON to stdout.

**Detect:** argparse subparser with output but no `--json` action='store_true' argument.

**Why:** Programmability requirement — scripted / MCP consumers cannot parse human-readable variants reliably. Every kaizen-* CLI this session (progress, learn, observer-events, bundle, handoff get) ships --json. Default: human-readable for terminal use; --json for automation.

### `shim-and-sweep` (hard · manual)

When a feature changes shape (flag retired / default flipped / name changed / module renamed), sweep all docstrings + test docstrings + READMEs + commands/*.md for stale references IN THE SAME COMMIT. No dangling back-compat documentation.

**Detect:** Diff retires/renames a public API element (flag / fn / module / file) but leaves stale references in module-level docstrings, test file docstrings, command bodies, or README text.

**Why:** Caught via session trace 2026-05-18 — the --commit opt-in flag was retired in 6a717e1 but 2 test-file docstrings still described it 2 days later. Stale docs train wrong mental models + invite re-introduction. The sweep is cheap (grep + edit); the cost of skipping it accumulates. Pattern: every retirement commit also greps for the retired token + updates every prose mention.

### `dry-extract-on-third-repetition` (soft · manual)

When a pattern (helper fn / shape / constant block) appears in 3+ distinct call-sites with identical or near-identical shape, extract a shared helper IN THE SAME COMMIT THAT INTRODUCES THE 3RD. Don't wait for the 4th.

**Detect:** Diff adds a 3rd instance of a pattern that's already present in 2 other files (e.g. _<feature>_dir env-overridable resolver; with open(p, 'a') append helper; subprocess git_run wrapper).

**Why:** Rule-of-three is a discipline pinned (DRY) but easy to skip when adding 'just one more.' Session evidence — atomic_append_line existed since the start but was reimplemented 4 times before extraction (commit 3a18b8f); env_overridable_dir went 5 sites before extraction (commit 681a56d). Both extractions saved ~20-30 LOC AND unlocked future consistency changes in ONE place. The discipline cost (extract on add) is much lower than the consolidation cost later (refactor 4-5 sites + update tests). Reinforces shim-and-sweep — the third repetition is where shim-and-sweep work compounds, so catch it then.

### `flake-audit-load-before-logic` (soft · manual)

When a test flakes ONLY under full-suite parallel load (passes solo + passes under narrow --pattern), audit sibling tests for heavy subprocess pressure BEFORE debugging the failing test's own logic. The cause is often elsewhere — fixture-spawning shell scripts in other test families create subprocess / filesystem contention that perturbs the failing test's timing.

**Detect:** A test fails intermittently only under `kaizen-tests` full-suite parallel run, but `python3 -m unittest tests.<failing>` passes consistently AND `kaizen-tests --pattern test_<family>_*` passes consistently.

**Why:** Caught via session trace 2026-05-19 — test_handoff_commit_autotag flaked 2 of 3 full-suite runs (different test in test_loop_state OR test_loop_hardening also failed each time). Solo + pattern runs all clean. After fixing the loop tests to stop invoking setup-ralph-loop.sh (which spawns bash + 2× python3-heredoc per `_init_loop` call → ~88 spawns across 22+ tests in 2 files), the handoff flake vanished — 15 of 15 consecutive clean runs without touching handoff code. The 88 invisible spawns were creating filesystem / process-table contention that perturbed git subprocess timing in unrelated tests. Diagnostic ladder: (1) solo run (2) --pattern run (3) `kaizen-tests bench` for >5s outliers (4) audit setUps for subprocess loops where the script's behavior isn't what's tested (5) only THEN debug the failing test's logic.

