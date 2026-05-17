---
name: ast-grep-project
description: Guides end-to-end structural project linting setup. Use to scaffold configs, author rules, test them, and run project-wide scans.
allowed-tools: [Bash, Write, Edit, Read]
version: "1.2"
---

**PROCEDURE. Run steps in order. Don't skip. Don't improvise commands — every command below is literal.**

User will give you a project path. Substitute it into `<PROJECT>`. If no path given, use `.`.

Language selection: run `ls <PROJECT>` and check for:
- `Cargo.toml` → `<LANG>` = `Rust`, `<EXT>` = `rs`
- `package.json` + `tsconfig.json` → `TypeScript` / `ts` (also handles `.tsx`)
- `package.json` only → `JavaScript` / `js`
- `pyproject.toml` / `requirements.txt` → `Python` / `py`
- `go.mod` → `Go` / `go`

If multiple, pick the one that matches the files under `src/`. If unsure, ask the user.

---

## Step 1 — Preflight (always run)

```bash
cd <PROJECT>
ls sgconfig.yml rules rule-tests utils 2>&1
```

**Done when** — you see whether these already exist.

- If all four exist → skip Step 2, go to Step 3.
- If any missing → go to Step 2.

---

## Step 2 — Scaffold (only if Step 1 shows missing files)

```bash
cd <PROJECT>
ast-grep new project -y
```

**Done when** — `ls` shows `sgconfig.yml`, `rules/`, `rule-tests/`, `utils/`.

**If `ast-grep: command not found`** — stop. Ask user to `cargo install ast-grep` or `brew install ast-grep`. Do not proceed.

**If `sgconfig.yml` exists but uses a non-standard testDir** (e.g. `rules/__tests__`, or an absolute path like `/home/.../rule-tests`):
- Rewrite `testDir` to relative `rule-tests/` in Step 3.
- `mkdir -p rule-tests/` if missing.
- Do NOT delete the old test directory yourself — if it had tests, move them: `mv rules/__tests__/* rule-tests/ 2>/dev/null; rmdir rules/__tests__ 2>/dev/null`.
- Non-standard layouts appear in projects that scaffolded against an older ast-grep version. Standardizing now means the rest of this procedure works unmodified.

---

## Step 3 — Replace `sgconfig.yml` with this exact content

Use the Write tool. Overwrite `<PROJECT>/sgconfig.yml`:

```yaml
# ast-grep project configuration.
#
# Usage:
#   ast-grep scan                         # run every configured rule
#   ast-grep scan --filter <rule-id>      # narrow to one rule
#   ast-grep scan --rule rules/<id>.yml --update-all   # apply auto-fixes
#   ast-grep test                         # snapshot-test rules under rule-tests/
#   ast-grep scan --inspect summary       # verify discovery

ruleDirs:
  - rules

testConfigs:
  - testDir: rule-tests

utilDirs:
  - utils

# Layered on top of .gitignore.
ignoreFiles:
  - target/
  - node_modules/
  - dist/
  - build/
  - .git/
```

**Done when** — file exists with relative paths (no absolute `/home/...` paths).

**If the original used absolute paths** — overwriting is correct. Absolute paths break when the repo moves.

---

## Step 4 — Rules: starter (empty) or audit (pre-existing)

Check first:
```bash
ls <PROJECT>/rules/*.yml 2>/dev/null | wc -l
```

**Branch A — result is `0` (empty rules/):** drop in the 3 starter rules from the language block below.

**Branch B — result is `≥ 1` (pre-existing rules):** do NOT add starter rules. The project has its own. Instead:
- List existing rule IDs: `grep -h '^id:' <PROJECT>/rules/*.yml`
- For each rule that has NO matching `<PROJECT>/rule-tests/<rule-id>-test.yml`, author a test file using the template shape in Step 5 (`id:`, `valid:`, `invalid:`). Use the existing rule's `pattern` / `message` as your guide for what "valid" and "invalid" look like.
- Do NOT overwrite, rename, or re-severity existing rule YAMLs without explicit user approval.
- Do NOT drop the language-block starters on top of a populated `rules/` dir. The starters are for empty projects.

Skip the rest of Step 4 if you took Branch B — jump to Step 5 to cover missing tests, then continue with Step 6 onward.

---

**Branch A** — load [starter rules and test templates](references/starter-rules-and-tests.md) for language-specific starter rules and their matching test files. **Copy verbatim** into `<PROJECT>/rules/<filename>.yml` and `<PROJECT>/rule-tests/<rule-id>-test.yml`. Do not edit severity or message unless the user asks.

**Branch A done when** — all 3 rule YAML files exist in `<PROJECT>/rules/` and matching `-test.yml` files exist in `<PROJECT>/rule-tests/`.

## Step 5 — Tests: verify coverage

Every rule in `<PROJECT>/rules/` must have a matching `-test.yml` in `<PROJECT>/rule-tests/`.

- **From Branch A (starter rules)**: test files were created above from the reference.
- **From Branch B (pre-existing rules)**: author test cases by reading the existing rule's `pattern:` and `message:`. Format: `id:`, `valid:` (2–3 cases that should NOT trigger), `invalid:` (2–3 cases that SHOULD trigger).

Snapshot files will land under `<PROJECT>/rule-tests/__snapshots__/` after Step 6 runs — do not create that directory manually.

**Done when** — every rule in `rules/` has a matching `-test.yml` in `rule-tests/`.

---

## Step 6 — Generate initial snapshots + verify tests pass

Run these in order:

```bash
cd <PROJECT>
ast-grep test --update-all
ast-grep test
```

**Done when** — second command reports `test result: ok. N passed; 0 failed;`.

**If a rule shows `FAIL ... WW` or `NN`** — the rule over-matches or under-matches. Recovery table at the bottom.

**If output says `no sgconfig.yml found`** — you're in the wrong cwd. `cd <PROJECT>` and rerun.

---

## Step 7 — Scan the real tree

```bash
cd <PROJECT>
ast-grep scan --inspect summary 2>&1 | head -20
ast-grep scan
```

**Done when** — scan completes. Count findings per rule:

```bash
ast-grep scan 2>&1 | grep -oE "\[([a-z-]+)\]" | sort | uniq -c
```

**Interpretation:**
- Errors → must fix or add to `ignores:`. Scan exits non-zero; CI would fail.
- Warnings / info / hint → audit list. Do not auto-fix without user approval.
- Zero findings → ship it.

---

## Step 8 — Tune noise (only if warnings are false positives)

Common patterns. Pick exactly one per problem:

| Symptom | Fix (edit the rule YAML) |
| --- | --- |
| Rule fires in test-runner file like `src/tools/foo_tests.rs` | Add `"src/tools/**_tests.rs"` to the rule's `ignores:` list. |
| Rule fires in generated code (`build.rs`, `.pb.go`) | Add `"**/build.rs"` or `"**/*.pb.go"` to `ignores:`. |
| Rule matches macro-expanded code by accident | Add a `kind: <real-node-kind>` constraint. Find the kind with `ast-grep run --pattern '<your pat>' --lang <L> --debug-query` on a sample file. |
| Rule matches an identifier inside a string literal | Add `not: { inside: { kind: string_literal } }` to the rule. |
| Rule should be severity-elevated in CI but not locally | Keep YAML at `warning`; pass `--error <id>` on the CI `ast-grep scan` command. |

After editing a rule, **always rerun** `ast-grep test --filter <id>` (snapshot may need updating with `--update-all`) before rerunning `scan`.

---

## Step 9 — CI gate (optional, only if user asks)

One line for the CI workflow:

```bash
ast-grep scan --error no-dbg-macro --error no-bare-except --error no-mutable-default-arg
```

Promote rules to `--error <id>` for each one you want to fail the build. Non-zero exit = fail.

Machine-readable output for PR annotations:
```bash
ast-grep scan --format github            # GitHub Actions
ast-grep scan --json=stream              # NDJSON, pipe to jq / diff tools
```

---

## Recovery table — "test failed" output → action

| You see | What it means | Action |
| --- | --- | --- |
| `Wrong: No <rule-id> baseline found` | First run of a new rule; no snapshot yet. | `ast-grep test --update-all` once. |
| `FAIL ... .NNN` (N = noisy) | Rule triggers on a `valid:` case (over-matches). | Narrow the rule: add `ignores:`, `not:`, or a `kind:` constraint. Then re-test. |
| `FAIL ... .MMM` (M = missing) | Rule didn't trigger on an `invalid:` case (under-matches). | Widen the rule. Check pattern syntax with `ast-grep run --pattern '<pat>' --lang <L> <file>`. |
| `FAIL ... .WW` (W = wrong) | Snapshot doesn't match. Rule moved or message changed. | Review `ast-grep test --interactive`; accept with `--update-all` if intentional. |
| `Error: Failed to parse rule` | YAML is malformed. | Re-read the rule file. Watch for tab/space mix in the `rule:` block. |
| `ast-grep: command not found` | Binary missing. | `cargo install ast-grep` or `brew install ast-grep`. |
| `no sgconfig.yml found` | Wrong cwd or missing config. | `cd <PROJECT>` and verify `ls sgconfig.yml`. |
| Scan output is empty | Rules loaded but no hits, OR `ignoreFiles` is masking everything. | Run `ast-grep scan --inspect summary` to see what was considered. |

---

## Do NOT

- **Do not modify the project's source code** during this workflow. You're setting up rules, not fixing violations.
- **Do not use `--update-all` on `ast-grep scan`** unless the user explicitly approved applying auto-fixes. Rewrites source files.
- **Do not skip the test step.** A rule without snapshot tests is a rule that will silently rot.
- **Do not add rules that don't exist in the language blocks above** unless the user asked for a specific one. Use the sibling `structural-rule-authoring` skill for authoring custom rules.
- **Do not delete `__snapshots__/` files**. They are the test baseline.
- **Do not drop starter rules on top of pre-existing rules.** If `ls rules/*.yml` is non-empty, take Branch B in Step 4. The project already has its own rules; your job is to add missing tests, not override someone else's design.

---

## Sibling skills (for deeper detail only — do NOT open unless the procedure above fails)

- `structural-rule-authoring` — authoring a custom rule (composite matchers, constraints, transform, fix templates)
- `structural-code-searching` — exhaustive reference for pattern syntax and rule YAML schema
- `structural-project-scanning` — advanced scan-workflow tuning (CI integration, `--json=stream` post-processing)
- `structural-search-routing` — pick an ast-grep invocation for a one-off question (not a project workflow)

For non-structural code-analysis questions ("who calls X", "blast radius", "dead code"), hand off to `code-graph-routing` — `ast-grep` is the structural-pattern tool; `llm-tldr` owns graph-level queries.
