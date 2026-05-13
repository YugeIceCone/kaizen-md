---
name: structural-rule-authoring
description: Authors, iterates, and snapshot-tests structural lint rules. Use to codify patterns, flag practices, and ensure rule correctness with fixtures.
allowed-tools: [Bash, Write, Edit, Read]
version: "1.2"
---

Loop: sketch pattern on CLI → save as rule YAML → snapshot-test → add to `rules/`.

1. **Sketch the pattern in `run`** (fast feedback, no YAML):
   ```
   ast-grep run --pattern '<pat>' --lang <L> --context 2 <path>
   ```
   Iterate the pattern until the match set is what you want. Prefer the **smallest** pattern that still distinguishes — extra nodes narrow accidentally.

2. **Scaffold the rule file** (optional; handwriting the YAML is fine):
   ```
   ast-grep new rule <id> -l <lang> -y
   ```
   Writes `rules/<id>.yml` with id / language / severity / message / rule stubs.

3. **Shape the rule YAML**:
   ```yaml
   id: no-bar-in-foo
   language: Rust
   severity: warning
   message: "short actionable one-liner"
   note: |
     Why this matters. Shown in LSP hover and in `scan` output.
   files: ["crates/*/src/**/*.rs"]
   ignores: ["**/tests/**"]
   rule:
     pattern: bar()
   ```
   For fix-on-save: add `fix: baz()`. For audit-only: use `severity: hint` or `info`.

4. **Narrow with composite keys** when `pattern:` alone over-matches:
   - `inside: { pattern: fn $F() { $$$ } }` — only inside a fn body
   - `has: { pattern: unsafe { $$$ } }` — only when body contains `unsafe {}`
   - `not: { pattern: #[test] }` — exclude test items
   - `any: [...]` / `all: [...]` for OR / AND

5. **Snapshot-test** (catches regressions when the rule or tree-sitter grammar updates):
   - `ast-grep new test <rule-id> -y` creates `rule-tests/<id>-test.yml` with `valid:` / `invalid:` sections.
   - Put one minimal program per case. `valid:` must not trigger the rule; `invalid:` must.
   - `ast-grep test` runs them all. Accept new output with `ast-grep test --accept-all` (review the diff first).

6. **Wire into the project**: drop `rules/<id>.yml` under `ruleDirs:` in `sgconfig.yml`; it picks up automatically.

Debugging tips:
- Rule doesn't fire → `ast-grep run --pattern '<same pat>' --lang <L>` on the same file. If `run` matches but the rule doesn't, `files:` / `ignores:` globs are probably excluding it.
- Rule over-matches inside test modules → add `not: { inside: { pattern: "#[cfg(test)] $$$" } }` — but note Rust's tree-sitter grammar keeps attributes as siblings, not children, so this pattern is awkward; often simpler to use `ignores: ["**/tests/**", "**/*_test.rs"]`.
- Rule over-matches on macro calls / string literals → add `kind:` to constrain node type, or `not: { inside: { kind: string_literal } }`.

For the sgconfig layout and CI gating, load `structural-project-scanning`. For full pattern / flag reference, load `structural-code-searching`.
