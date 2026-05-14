---
name: plugin-development
description: Canonical patterns for adding a feature to the kaizen plugin. Use when building any new module / MCP server / hook / slash command / bin wrapper inside kaizen-md, or when reviewing a feature PR. Constructive counterpart to plugin-pitfalls (which catalogs failures). Triggers on "add a feature to kaizen", "new kaizen module", "wire a kaizen mcp server", "kaizen feature scaffold", "node+flow shape", "domain-driven yaml schema in kaizen", "kaizen feature checklist", "follow B1-B5 cadence", "new kaizen indexer", "kaizen bin wrapper", "schema-driven kaizen feature".
version: 1.0.0
---

# Plugin development — building features into kaizen-md

## ⚠ Iron Law — read in full

Skip nothing. The constructive patterns + the canonical-source pointers
+ the anti-patterns hang together. Skimming to "Quick reference"
without internalizing the canonical-edit-path rule, the vendored-vs-
plugin-original distinction, or the test-discipline produces PRs that
churn through review.

## What this skill IS

A constructive walk-through of "how to add a feature to kaizen-md
without re-discovering the conventions every time." Codifies the
shape proven across:

- B1-B5 brain fold-in (5-commit cadence, ~5000 LOC Python + tests)
- Phase 4 of the kaizen roadmap (E9/E10/O8/X4 — 4 modules, same shape)
- The optimized PocketFlow engine (Node+Flow primitives consumers reuse)

## Schema-driven — the prose is NOT the source of truth

The authoritative declarations live in `domain/`:

| File | What it declares |
|---|---|
| `domain/feature-shape.yaml` | The 11 file slots + per-slot `required` / `when` predicates |
| `domain/iron-laws.yaml` | 13 iron laws with `severity` (hard / soft / info) and machine-checkable `detect` patterns |
| `domain/wiring-checklist.yaml` | Per-artifact wiring entries (plugin.json permissions, hooks.json events, bin chmod, etc.) |
| `domain/schemas/feature.schema.json` | JSONSchema for optional `skills/<feature>/domain/manifest.yaml` |

The prose below explains the WHY; the yaml encodes the WHAT.
`scripts/validate.py` reads the yaml directly and reports
violations. **When prose and yaml disagree, yaml wins.**

## Enforcement (the skill is not skippable)

Four layers:

1. **`scripts/validate.py`** — run manually or as a pre-commit
   gate hook:
   ```bash
   python3 plugins/kaizen/skills/plugin-development/scripts/validate.py --all
   python3 plugins/kaizen/skills/plugin-development/scripts/validate.py --staged
   python3 plugins/kaizen/skills/plugin-development/scripts/validate.py --feature brain
   ```
   Exit codes: `0` clean, `1` soft warnings, `2` hard failures.

2. **Persona ## Top Beliefs** entry `pref-kaizen-plugin-dev` —
   loads at every session start. When the user is editing
   kaizen-md, this directive is in context.

3. **Brain rule** at `~/.claude/brain/Notes/pref-kaizen-plugin-dev.md`
   with `kaizen:` frontmatter. Surfaces via the kaizen gate's
   custom-pattern check when commits touch `plugins/kaizen/`.

4. **`/kaizen:metrics skips`** (v1.34+) — runtime skip-detection.
   The SessionEnd hook auto-fires `metrics-session-end.sh` which
   runs `metrics.py skips` and writes draft Inbox entries when
   files were touched without the matching skill being loaded.
   See [`metrics`](../metrics/SKILL.md) — the self-correction
   surface that catches violations after the fact.

   ```bash
   # Manual check at any time:
   kaizen-metrics skips
   # Or via MCP from an agent:
   mcp__plugin_kaizen_metrics__metrics_skips(sid=None)
   ```

## What this skill is NOT

This skill **does not duplicate** canonical content. For these
topics, the authoritative homes are:

| Topic | Canonical source |
|---|---|
| Commit discipline / sizing rule / PR checklist | [`CONTRIBUTING.md`](../../CONTRIBUTING.md) |
| Failure modes / "why won't my plugin load" | [`plugin-pitfalls`](../plugin-pitfalls/SKILL.md) |
| Brain-sourced runtime rules (`kaizen:` frontmatter) | [`behaviour-config`](../behaviour-config/SKILL.md) |
| Rules management / templates | [`kaizen:rule`](https://...) skill |
| Publishing to GitHub | [`publishing`](../publishing/SKILL.md) |
| AI-coding discipline before commit | [`vibe-check`](../vibe-check/SKILL.md) |
| Generic plugin structure / hooks / commands / agents / MCP | External `plugin-dev:*` skills |
| Plugin pre-commit gate / 12 checks | [`workflow`](../workflow/SKILL.md) PART 3 |
| Adoption / never-used / skip-detection metrics | [`metrics`](../metrics/SKILL.md) |

Read those FIRST when relevant. This skill assumes you've absorbed
their rules and focuses on what's **kaizen-md specific**.

## Canonical edit path (rule #0 — non-negotiable)

```text
EDIT AT:   ~/workspace/kaizen-md/                  ← canonical
NOT AT:    ~/.claude/local-marketplaces/kaizen-md/ ← symlink (install path)
```

The local-marketplaces path is a symlink Claude Code uses for plugin
discovery. Both paths resolve to the same files, but addressing
through the symlink confuses tools (git status output, IDE search
indices, some path-canonicalization helpers). When the user reminds
you "edit at workspace/kaizen-md", they mean: use the workspace path
for ALL writes.

See the project-memory entry
`~/.claude/projects/-home-cherry86-workspace-shodan/memory/feedback_kaizen_plugin_canonical_path.md`
for the user's stated preference.

---

## Part 1 — The 11-file new-feature shape

Every kaizen-original feature ("kaizen-original" = code in
`skills/workflow/`, `skills/<feature>/`, `commands/`, `bin/`, `hooks/`
— not vendored bundles) follows this shape. Land each file in its
own atomic commit using the [phased-work commit template](../../../../.claude/brain/Notes/pref-phased-work-commit-template.md).

```text
plugins/kaizen/
├── skills/<feature>/
│   ├── SKILL.md                       (1) navigable guide
│   └── domain/                        (2) schema-driven yaml
│       ├── <thing>.yaml
│       ├── <thing-2>.yaml
│       └── schemas/
│           └── <type>.schema.json
├── skills/workflow/scripts/
│   ├── _<feature>.py                  (3) core primitives + paths + config
│   ├── <feature>.py                   (4) capture/main flow + CLI
│   ├── <feature>_index.py             (5) SQLite + (optional) semantic index
│   ├── <feature>_<op>.py              (6) specialized flows (audit/promote/evolve/…)
│   └── <feature>_mcp.py               (7) FastMCP server
├── bin/
│   └── kaizen-<feature>[-<op>]        (8) thin shell wrappers — one per CLI script
├── hooks/claude/
│   └── <feature>-<event>.sh           (9) optional CC-only event hooks
├── commands/
│   └── <feature>.md                   (10) /kaizen:<feature> slash command
└── tests/
    └── test_<feature>_<aspect>.py     (11) unit + flow + integration tests
```

Plus the manifest changes:

```text
plugins/kaizen/.claude-plugin/plugin.json   ← permissions entries for each script + hook
plugins/kaizen/hooks/hooks.json             ← event-slot wiring for each hook
```

### Why these 11 files (and not fewer)

- **Separation of `_<feature>.py` (private core) from `<feature>.py` (public)** —
  the underscore module is pure primitives (paths, config, type
  detection, frontmatter); the public module is flow + CLI. Tests
  hit the core in isolation; the public module composes.
- **Per-operation specialized flows** instead of a fat router —
  follows Node+Flow's one-responsibility-per-node rule scaled up to
  one-responsibility-per-flow.
- **MCP server as a separate file** — the FastMCP shebang script
  has different deps than the rest. Keeping it isolated means
  `python3 brain.py` works without `mcp` installed.
- **Bin wrappers as plain bash** — each CLI script gets its own
  symlink-target so `kaizen-<feature>-<op>` works from shell after
  `/kaizen:install` symlinks them into `~/.local/bin/`.

### Sizing within the shape

If a feature has only one flow (no index, no promote, no audit, etc.),
collapse files 5/6 into file 4. If it has no CLI surface (purely
agent-facing via MCP), collapse file 4 into file 7. **Never** collapse
the schema (file 2) into code — yaml is the source of truth for
routing.

---

## Part 2 — Module conventions

### Private core (`_<feature>.py`)

- Defines `Config` (loads yaml from `skills/<feature>/domain/`)
- Path resolution: `<feature>_root()` + per-project resolution
- Frontmatter parse + serialize (when the feature reads/writes
  markdown files with frontmatter)
- Pure helpers — no side effects on filesystem unless the feature
  is itself a write operation
- Stdlib-only when possible; lazy-imports for heavy deps

### Public CLI (`<feature>.py`)

- Imports `_<feature>` as the core
- Imports `flow as _flow` and uses `AsyncNode` / `AsyncFlow`
- `argparse` CLI with subcommands matching the operations
- Each subcommand is a thin wrapper around the Node+Flow assembly
- `main(argv=None) -> int` for testability

### Indexer (`<feature>_index.py`)

When the feature needs SQLite + semantic search, mirror
`brain_index.py` / `trace_index.py` / `onboard_index.py`:

- Schema in `_SCHEMA_SQL` constant (idempotent `CREATE IF NOT EXISTS`)
- Migrations as separate functions (`_migrate_<v>_<col>`)
- `open_db(create=True)` resolves path + applies schema + migrations
- Indexing flow: `Discover → Embed → Upsert → Report`
- Search supports semantic (when `_embed.embed_one` available) AND
  LIKE fallback (graceful degradation)
- Env knob `KAIZEN_<FEATURE>_INDEX_SKIP_EMBED=1` for fast/CI tests

### MCP server (`<feature>_mcp.py`)

Shebang script with `# /// script` dep block:

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=1.0", ...other_deps...]
# ///
```

- `FastMCP("kaizen-<feature>")` instance at module scope
- Every tool wraps the corresponding CLI helper via `asyncio.to_thread`
- Tool docstrings document the kwargs (FastMCP uses them as schema)
- One async function per tool
- Errors return `{"error": "<msg>"}` instead of raising (better MCP UX)

### Hooks (`hooks/claude/<feature>-<event>.sh`)

- Shebang `#!/usr/bin/env bash` + `set -uo pipefail` (NOT `-e` — hooks must not abort on benign failures)
- Bypass env knob early: `if [ "${KAIZEN_<FEATURE>_DISABLE:-}" = "1" ]; then exit 0; fi`
- Resolve plugin root via `_plugin_root.sh` (cross-platform):
  ```bash
  _SCRIPT_REAL="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "${BASH_SOURCE[0]}")"
  _HOOK_DIR="$(cd "$(dirname "$_SCRIPT_REAL")" && pwd)"
  source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
  PLUGIN_ROOT="$(kaizen_plugin_root)" || exit 0
  ```
- Defensive stdin parse — `INPUT="$(cat 2>/dev/null || true)"` then
  `python3 -c '...'` to extract JSON fields (jq may not be installed)
- Always `exit 0` at the bottom — hooks blocking the session is a
  failure mode

---

## Part 3 — Schema-driven domain/yaml pattern

Every feature whose behavior changes per-user or per-config should
load its decisions from yaml in `domain/` rather than encode them in
code.

### Why yaml + jsonschema

| Alternative | Problem |
|---|---|
| Hardcoded Python dicts | Users must edit code + restart to change |
| `.kaizen.toml` | Already the gate's home; adding feature rules bloats it |
| Brain rules (`kaizen:` frontmatter) | Right for runtime gate overrides (deletion-allow etc.); wrong for feature-internal decisions like type taxonomies |
| **yaml + jsonschema in `skills/<feature>/domain/`** ✓ | Lives WITH the feature; user can edit; validation via jsonschema |

### Required files per feature

```text
skills/<feature>/domain/
├── <thing>.yaml             # the decision tables
├── <thing-2>.yaml           # add more as the feature grows
└── schemas/
    └── <type>.schema.json   # JSONSchema validation for the artifacts the feature writes
```

### Loader convention

`_<feature>.py` exposes a `Config` class with:

```python
class Config:
    @classmethod
    def load(cls, domain_dir: Optional[Path] = None) -> "Config":
        d = domain_dir or _DOMAIN_DIR
        # Load each yaml; populate dataclasses; validate via jsonschema
```

PyYAML when available; minimal fallback parser when not (the brain
feature shows the pattern).

### Yaml gotcha

A literal colon inside a description string trips the YAML parser
("mapping values are not allowed here"). **Quote any description
that contains `: `**:

```yaml
# BROKEN
description: Frontmatter `promote: true` forces promotion

# CORRECT
description: "Frontmatter `promote: true` forces promotion"
```

---

## Part 4 — Node+Flow design rules

Every operation is a `flow.AsyncNode` graph. The runtime sits at
`skills/workflow/scripts/flow.py`. See its module docstring for the
full primitive set — this skill describes how to USE them, not what
they are.

### One responsibility per node

A node does ONE of:

- pull-from-store (prep)
- pure work (exec)
- write-to-store (post)

If a node does two of those structurally, split it. The flow gains
readability + observability (event hooks fire per node).

### Action keys are the dispatch

`post_async` returns a string (or `None`). The flow dispatches via
`node.successors[action]`. Use the new `>>` operator for linear
chains:

```python
parse >> detect >> journal >> route >> dedup >> write >> report
```

For branches:

```python
router - "retry" >> retry_node
router - "fail"  >> error_handler
router - "ok"    >> next_step
```

### Use `AsyncParallelBatchNode` for fan-out

Override `exec_one_async(item)` instead of `exec_async(items)` and
the base class wraps with `asyncio.gather`. Optional `concurrency`
attribute caps simultaneous tasks.

### Retry + fallback for I/O-bound nodes

```python
class Flaky(AsyncNode):
    max_retries = 3
    wait = 1.0  # seconds between attempts

    async def exec_async(self, prep):
        # may raise transiently
        ...

    async def exec_fallback_async(self, prep, exc):
        return None  # degrade gracefully instead of re-raising
```

Default `max_retries = 1` is fail-fast — opt in to retries when the
node calls a network / flaky external resource.

### Cycle guard

`AsyncFlow(start, max_iterations=N)` defaults to 1000. Set higher for
intentional loops; set `None` to disable. Lets accidental cycles
fail loudly instead of hanging.

### Event hooks for tracing

```python
flow = AsyncFlow(
    start_node,
    on_enter=lambda n, s: trace.emit("flow.enter", n.__class__.__name__),
    on_exit=lambda n, s, a: trace.emit("flow.exit", a),
    on_error=lambda n, s, e: trace.emit("flow.error", str(e)),
)
```

Sync or async hooks; the flow awaits if needed.

---

## Part 5 — Lazy load + graceful fallback (heavy deps)

When a feature depends on a HEAVY package (transformers, torch,
tree-sitter wheels, mcp, PyYAML, etc.), use the canonical 4-element
shape:

```python
_cached = None
_load_attempted = False

def is_enabled() -> bool:
    return os.environ.get("KAIZEN_<X>_ENABLE", "").lower() in {"1", "true", "yes", "on"}

def _load():
    global _cached, _load_attempted
    if _load_attempted: return _cached
    _load_attempted = True
    try:
        from heavy_dep import Thing
    except ImportError:
        return None
    try:
        _cached = Thing(...)
    except Exception as e:
        sys.stderr.write(f"<feature>: failed: {e}\n")
        return None
    return _cached

def reset_cache() -> None:
    """For tests that mutate env between cases."""

def is_available() -> bool:
    return _load() is not None
```

Indexers/search probe `is_available()` and return `[]` / `None` on
miss — they NEVER raise, never spam stderr per-call, never auto-install.

See cross-project belief
`~/.claude/brain/Notes/pref-optional-feature-graceful-fallback.md`
for the full pattern + 4 proven instances.

---

## Part 6 — Test discipline

### Sandbox path env

Every test that writes to disk sandboxes via env vars:

```python
class FeatureBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "feature-root"
        self.root.mkdir()
        self._orig = os.environ.get("KAIZEN_FEATURE_PATH")
        os.environ["KAIZEN_FEATURE_PATH"] = str(self.root)

    def tearDown(self):
        self._tmp.cleanup()
        if self._orig is None:
            os.environ.pop("KAIZEN_FEATURE_PATH", None)
        else:
            os.environ["KAIZEN_FEATURE_PATH"] = self._orig
```

This means feature path resolution MUST be env-aware (see `_brain.brain_root()`
for the canonical shape — env > default).

### Mock encoders for heavy deps

Test the integration without loading the heavy model:

```python
fake_embed = lambda texts: ([struct.pack("384f", *([i/100.0]*384)) for i in range(len(texts))], 384)
with patch.object(module, "encode_batch", side_effect=fake_embed), \
     patch.object(module, "is_available", return_value=True):
    result = module.do_index()
```

### Three layers of tests

1. **Pure-logic** (always run): serialize / deserialize / dispatch / type detection
2. **Mocked integration** (numpy-only): full pipeline with mocked encoder
3. **Real-model** (skipped when deps missing): `@unittest.skipUnless(module.is_available(), "deps missing")`

### Parses-without-deps test

Add at least one test that just confirms the module FILE compiles
without importing the heavy deps:

```python
def test_module_script_parses(self):
    path = SCRIPT_DIR / "feature_mcp.py"
    with open(path, "r") as f:
        compile(f.read(), str(path), "exec")
```

Catches syntax errors in CI envs that lack the runtime deps.

---

## Part 7 — Wiring checklist

After dropping the 11 files, wire them into the plugin:

### plugin.json permissions

Add one entry per Python script + one per hook script:

```jsonc
{
  "permissions": {
    "allow": [
      "Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/<feature>.py:*)",
      "Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/<feature>_index.py:*)",
      "Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/<feature>_<op>.py:*)",
      "Bash(uv run --script ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/<feature>_mcp.py:*)",
      "Bash(bash ${CLAUDE_PLUGIN_ROOT}/hooks/claude/<feature>-<event>.sh:*)"
    ]
  }
}
```

Without these, Claude Code prompts the user every invocation.

### hooks/hooks.json

Add hook entries under the matching event slot. The validator
requires the top-level `hooks` wrapper (see [`plugin-pitfalls #1`](../plugin-pitfalls/SKILL.md#1-hooksjson-must-be-wrapped-in-a-top-level-hooks-record)).

When adding multiple commands to an event already populated, append
to the existing `hooks: []` list — don't add a new outer config block
(see [`test_cc_hooks_wireup.py`](../../tests/test_cc_hooks_wireup.py)
for the structural test; relax it if you genuinely need a 2nd block).

### Plugin version bump

`plugin.json::version` bumps with EVERY meaningful feature merge.
Semver judgment: minor for new feature, patch for bug fix. The
`CHANGELOG.md` entry under `[Unreleased]` is part of the SAME
commit (CONTRIBUTING.md rule).

### Bin wrapper symlinks

`/kaizen:install` walks `bin/` and symlinks every executable into
`~/.local/bin/`. Drop one wrapper per CLI script you want shell-
addressable. Without a wrapper, the script is only reachable via
`/kaizen:<feature>` slash command or direct path.

**Don't forget specialized bins** (e.g. `kaizen-brain-index`,
`kaizen-brain-promote`) — the omission caused a real bug this round,
caught by smoke-testing `kaizen-<feature>-<op>` from shell.

---

## Part 8 — Anti-patterns

### Don't modify vendored skills

`skills/kiss/`, `skills/solid/`, `skills/dry/`, `skills/yagni/`,
`skills/karpathy/`, `skills/separation-of-concerns/`,
`skills/law-of-demeter/`, `skills/convention-over-configuration/`,
`skills/boy-scout-rule/` are **upstream-vendored** from
[`coding-skills`](https://github.com/JordanCoin/codingskills).

`skills/superpowers/*` (14 entries) are from
[`superpowers`](https://github.com/obra/superpowers).

`skills/init/`, `skills/remember/`, `skills/process/`,
`skills/evolve/`, `skills/reflect/`, `skills/synthesize/`,
`skills/status/` are from the retired remember-md plugin.

**Edit upstream first.** Then refresh via the
[bundle-refresh procedure](../../CONTRIBUTING.md#bundle-refresh-procedure).
Plugin-original content lives in `skills/workflow/`, `skills/<your-feature>/`,
`skills/behaviour-config/`, `skills/code-tour/`, `skills/agent-formatting/`,
`skills/plugin-pitfalls/`, `skills/publishing/`, `skills/vibe-check/`,
`skills/handoff/`, and a handful of others.

### Don't skip the gate

The plugin's own pre-commit gate runs on every commit (it eats own
dogfood). Bypass via `--no-verify` is reserved for HOOK FAILURE
(when the hook script itself is broken), not for getting around
inconvenient checks. If a check fires wrongly, fix the rule or add
a brain-sourced override per [`behaviour-config`](../behaviour-config/SKILL.md).

### Don't reach across feature boundaries

`brain.py` shouldn't import `loc_index.py`. Each feature owns its
core; cross-feature integration goes through MCP tools or shared
helpers in `skills/workflow/scripts/_*` (private modules). The
`_embed.py` / `_sqlite.py` / `_paths.py` / `_progress.py` shared
helpers are the only legitimate cross-feature imports.

### Don't hardcode paths in features

Path resolution lives in the private core (`_<feature>.py`). It
reads env vars (`KAIZEN_<FEATURE>_PATH` > legacy fallbacks > default)
and supports both `~` and `$HOME` expansion. The test sandbox
discipline depends on this.

### Don't write commit SHAs / dates / LOC into CLAUDE.md

CLAUDE.md is the durable rulebook. Volatile data goes in:
- `CHANGELOG.md` for releases
- `progress.md` for architecture-log rows (when the project has one)
- Commit body / `git log --grep` for history

This rule applies to README.md and any rulebook-shaped file too.

### Don't ship a CLI script without a bin wrapper

Specialized op scripts (e.g. `brain_index.py` / `brain_promote.py` /
`brain_audit.py` / `brain_evolve.py` / `metrics.py`) each need their
OWN `bin/kaizen-<feature>[-<op>]` wrapper. `/kaizen:install` symlinks
`bin/` entries into `~/.local/bin/`; a missing wrapper means
`kaizen-<feature>-<op>` returns `command not found` from any shell.

Caught TWICE this session: brain initially shipped only
`kaizen-brain` (hotfix `ed4b490` added the four missing wrappers);
metrics caught at the same place. The validator's wiring-checklist
now flags this — iron-laws.yaml::`bin-wrapper-per-cli-strict`.

### Don't use `${ARGUMENTS:-default}` with whitespace defaults

Slash commands template-substitute `${ARGUMENTS}` to the user's
args. The `:-default` bash-parameter-expansion only fires when the
substituted-then-bash-evaluated value is empty AND the default
contains NO whitespace. Multi-word defaults are interpreted
literally even when the user passes args.

❌ Broken — `commands/<feature>.md` body (exec marker stripped):

    python3 .../metrics.py ${ARGUMENTS:-lifetime --since 7d}

    # User runs: /kaizen:metrics top --kind skill
    # Result:     runs "lifetime --since 7d" (default fired
    #             despite ARGUMENTS being set)

✓ Fix: give the underlying script a no-arg default + pass bare
`$ARGUMENTS`. The `commands/<feature>.md` body (shown WITHOUT its
leading bang-backtick exec marker, which the Skill loader would
otherwise try to run) becomes:

    python3 .../metrics.py $ARGUMENTS

— and the script's `main()` runs `lifetime --since 7d` when argv is
empty.

OR use the brain.md-style explicit dispatcher — a `bash -c '...'`
body that reads `${ARGUMENTS:-default}` into a local before
dispatching. See `commands/brain.md` for the worked example.

Single-word defaults work fine (`${ARGUMENTS:-stats}` in onboard.md).

> **Meta-gotcha:** SKILL.md examples must NOT contain a literal
> bang-backtick (`` ! `` + `` ` ``) exec marker — the Skill tool
> processes those the same way slash commands do and will try to
> run them at skill-load time. Describe slash-command bodies in
> prose or indented blocks, never as live exec markup.

### Don't add per-tool trace hooks if the universal already covers it

`hooks/claude/pretooluse-trace.sh` + `posttooluse-trace.sh` (matcher
`*`) fire for every non-Bash tool. New hooks should NOT re-trace
the same tool — pollution + double-counting in metrics rollups.

Bash is the exception: `pretooluse-bash-gate.sh` traces + gates;
the universal hook skips Bash to avoid the double.

---

## Quick reference

### Commit-message template

See [`~/.claude/brain/Notes/pref-phased-work-commit-template.md`](../../../../.claude/brain/Notes/pref-phased-work-commit-template.md).
Shape per atomic commit:

```text
<type>(<scope>): Phase <N> <id> — <one-line headline>

<2-3 sentences motivation>

Default off — gated on <env knob>. <Migration / fallback behavior>.

Files
- <new module> (new) — <one-line role>
- <touched module> — <one-line delta>
- tests/test_<x>.py — <N tests; how many gated when>

Test baseline: <prev> to <new> (+<delta>); same 0 failures.

Env knobs (all opt-in, default off):
- KAIZEN_<X>_ENABLE=1
- <other knobs>

Refs: roadmap section <id>; Phase <N>: <M/N> complete
```

### One-shot scaffold script (manual today; automation candidate)

For a new feature `xyz`, drop these files in one PR / phased commits:

```bash
F=xyz
mkdir -p plugins/kaizen/skills/$F/domain/schemas
touch plugins/kaizen/skills/$F/{SKILL.md,domain/types.yaml,domain/routing.yaml,domain/schemas/note.schema.json}
touch plugins/kaizen/skills/workflow/scripts/{_$F.py,$F.py,${F}_index.py,${F}_mcp.py}
touch plugins/kaizen/hooks/claude/$F-session-end.sh
touch plugins/kaizen/commands/$F.md
touch plugins/kaizen/bin/kaizen-$F plugins/kaizen/bin/kaizen-$F-index
chmod +x plugins/kaizen/bin/kaizen-$F plugins/kaizen/hooks/claude/$F-session-end.sh
mkdir -p plugins/kaizen/tests
touch plugins/kaizen/tests/test_${F}_core.py plugins/kaizen/tests/test_${F}_flow.py
```

Then fill in following the patterns above. The brain feature
(B1-B5, kaizen-md commits `733e0c5..2cfd234`) is the canonical
worked example — read it end-to-end before starting your own.

### Iron Laws (cheat-sheet)

1. **Edit at `~/workspace/kaizen-md/`, never the symlink.**
2. **Don't modify vendored skills.** Patch upstream first.
3. **11-file new-feature shape** (or principled subset).
4. **Schema-driven via yaml in `domain/`.** No hardcoded routing.
5. **Node+Flow for all multi-step ops.** No ad-hoc orchestration.
6. **Lazy-load heavy deps + `is_available()`** — never auto-install.
7. **Sandbox tests via env vars.** Never touch real `~/.claude/`.
8. **Bin wrapper per CLI script** — every argparse-main script gets
   its OWN `bin/kaizen-<feature>[-<op>]`. Symlinks land via
   `/kaizen:install`. Specialized ops (index / promote / audit /
   evolve / metrics) each need their own wrapper.
9. **plugin.json + hooks.json + bin wrappers wired** in the same commit.
10. **Commit per atomic unit** using the phased-work template.
11. **Run `kaizen-metrics skips` before merging** structural changes —
    catches mandatory-skill-load misses; the SessionEnd hook also
    surfaces these to brain/Inbox/.
12. **Slash command `${ARGUMENTS:-default}` only works with whitespace-
    free defaults.** Multi-word default → give the script a no-arg
    fallback and pass bare `$ARGUMENTS`.
13. **Don't re-trace tools** the universal `pretooluse-trace.sh` /
    `posttooluse-trace.sh` already cover.
