---
name: layout-migration-sweep
description: Use when a previous refactor relocated files (skills/X/scripts → scripts/X, depth changes, cluster reshuffles) and stragglers — wrappers / shell scripts / docs / hooks — still point at the dead path. Symptom is usually a single broken command (exit 127, "No such file or directory") that on inspection reveals N more files with the same shape. Triggers on "Phase-N migration", "layout drift", "path sweep after move", "post-migration straggler", "../../.. lands at wrong dir", "skills/workflow/scripts/ refs", "stale exec path", "cafa249-shape fix". Pairs with shim-and-sweep (the structured way to relocate so straggler-sweeps aren't needed) and bin-wrapper-per-cli iron-law (which enforces wrapper presence but not target validity).
metadata:
  version: "1.0"
  origin: kaizen-md 2026-05-20 (cafa249 + 992d9e8 + 4476162 + bin-wrapper sweep)
---

# Layout migration sweep — find + fix the stragglers a relocation left behind

A previous refactor moved files. Most consumers got updated. Some didn't. The undetected stragglers stay quiet until the user hits the one specific verb that exercises them — by which point the original refactor commit is far enough back that the connection isn't obvious. This skill is the playbook for catching them in one pass.

## When to load

- A single command exits 127 / "No such file or directory" pointing at a path inside the plugin.
- `grep -r 'old/path' .` returns N files where you only knew about 1.
- A dry-run command prints paths that don't exist on disk (silent — exit 0).
- You're about to commit a one-off fix that looks like cafa249 / 992d9e8 / 4476162 (one path patched, ship; one path patched, ship; one path patched, ship).
- A previous refactor commit said "Phase N" or "relocate" or "rename" and didn't ship a regression test.

## The four straggler classes (from real bugs)

Each class hides in a different place. Sweep each independently.

### Class 1 — bin wrapper `exec` targets

`bin/kaizen-X` files delegate via `exec bash "$PLUGIN_ROOT/path/to/script.sh" "$@"`. After a layout migration, the path is dead. Wrapper crashes before its target runs. The user never sees a useful error — just `bash: ...: No such file or directory`.

**Sweep:**
```bash
grep -ln 'OLD_PATH_SUBSTRING' plugins/<plugin>/bin/*
```

For each hit, distinguish `exec` lines (runtime-load-bearing) from comment-only references (cosmetic but misleading). The former break; the latter are still bad debt.

**Regression test (catches the class):**
Walk every wrapper, parse `exec (bash|python3|uv run --script) "$PLUGIN_ROOT/<path>"`, assert each `<path>` resolves on disk. See `tests/test_bin_wrapper_targets.py` in kaizen-md for the canonical implementation.

### Class 2 — `PLUGIN_ROOT="$SCRIPT_DIR/../..."` depth bugs

When scripts move between directories, their `../` count to reach the plugin root changes. Worst case: the new path resolves to a *different existing directory*, so the script doesn't error — it just operates on the wrong files. **Silent.**

**Sweep:**
```bash
grep -Hn 'PLUGIN_ROOT=.*pwd' plugins/<plugin>/scripts/**/*.sh
```

For each hit, compute `(script_dir / traversal).resolve()` and assert it equals the real plugin root.

**Fix shape (DRY-correct):** instead of patching depth counts, route through a shared helper. Convention in kaizen:
```bash
source "$SCRIPT_DIR/../util/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root)"
```

The helper resolves via `$CLAUDE_PLUGIN_ROOT` → `$KAIZEN_PLUGIN_ROOT` → walk-up-to-find-plugin.json. No depth counting at the call site = no future depth bugs.

**Regression test:** see `tests/test_sh_script_coverage.py::TestPluginRootDepth` in kaizen-md.

### Class 3 — doc + frontmatter references

SKILL.md bodies, command frontmatter `allowed-tools`, table rows like "was X, then Y", iron-law detection rules in `references/iron-laws.md`, and CHANGELOG-style header comments all carry path strings. These don't break anything at runtime but mislead the next contributor and break detection regexes.

**Sweep:**
```bash
grep -rln 'OLD_PATH_SUBSTRING' plugins/<plugin>/ \
  --include='*.md' --include='*.json' --include='*.yaml' \
  --include='*.toml' | grep -v CHANGELOG
```

**Triage rule:** CHANGELOG.md and historical commit-bodies stay (history is fixed). Live docs, frontmatter, and detection patterns update. Per `feedback-no-changelogs-in-descriptions`: descriptions answer "what does this do now", not "what it used to be" — strip the trailing "was /kaizen:X" rather than chasing renames.

### Class 4 — internal `source` / sibling-resolve paths

Scripts source siblings via `source "$_SCRIPT_REAL_DIR/../../scripts/util/_paths.sh"`. When the script itself moves, the relative path to the sibling may still resolve correctly (if both moved together) or break (if they didn't). Easy to miss because the path *looks* current.

**Sweep:**
```bash
grep -Hn 'source.*\$.*\.sh' plugins/<plugin>/scripts/**/*.sh
```

For each hit: confirm the resolved target exists. Prefer the helper pattern (see Class 2) to make these robust to future moves.

## One-shot sweep checklist

When you've decided to do the full sweep (not one-off):

1. Identify the *old path substring* (e.g. `skills/workflow/scripts/`).
2. Run all 4 class sweeps above. Collect the matches.
3. Partition matches: runtime-broken (Class 1/2/4 with bad `exec`/`source`/depth) vs. cosmetic (Class 3 docs, comments).
4. Fix runtime breakage first — that's the user-visible damage. Comments can defer.
5. For Class 2 specifically: prefer the helper rewrite over the depth-count fix. Future-proofs the script.
6. Write the regression test BEFORE landing the fix. The test should fail against the original bug (RED), then pass after the fix (GREEN). The test is the durable artifact — the fix is one commit, the test catches the class for all future commits.
7. Commit per class (one commit for bin wrappers, one for PLUGIN_ROOT, one for docs). Each commit's body lists the files + the structural shape.
8. After the sweep: run any smoke test that exercises the affected verbs end-to-end. Bin wrappers: `kaizen-debug smoke` (deny-list-aware). SH scripts: the new sh-coverage smoke layer.

## Anti-patterns

- **One-off patching without grep.** Fixing `enable_all.sh` without grepping for the same shape in `ops/` leaves the next one to be hit live.
- **Patching depth instead of using the helper.** `../../..` → `../..` works for now; a future move breaks it again. Helper pattern is depth-invariant.
- **No regression test.** If the bug class can recur, ship the test. cafa249 fixed one instance with no test; 992d9e8 hit the next instance two days later.
- **Treating CHANGELOG references as stale.** CHANGELOG is history — frozen on purpose. Don't sweep it; the entry was correct on the day it was written.

## Cross-references

- `tests/test_bin_wrapper_targets.py` — Class 1 catcher (canonical)
- `tests/test_sh_script_coverage.py::TestPluginRootDepth` — Class 2 catcher (canonical)
- `scripts/util/_plugin_root.sh` — the helper that closes the Class 2 bug class
- `scripts/git-hooks/lib.sh::find_sibling` — example consumer of the helper
- `[[Notes/pref-no-deletions]]` — relocation ≠ deletion; the relocated file is still tracked
- kaizen `shim-and-sweep` skill — the *prevention* pair to this skill's *detection* role
