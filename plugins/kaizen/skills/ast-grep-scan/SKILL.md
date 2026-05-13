---
name: structural-project-scanning
description: Lints whole projects with configured structural rules. Use for repo-wide audits, finding violations, and gating CI on structural rules.
allowed-tools: [Bash]
version: "1.2"
---

Prereq: project has `sgconfig.yml` at root. If not: `ast-grep new project -y` first (scaffolds `sgconfig.yml`, `rules/`, `rule-tests/`, `utils/`).

Typical sgconfig.yml:
```yaml
ruleDirs: [rules]
testConfigs:
  - testDir: rule-tests
utilDirs: [utils]
ignoreFiles:
  - target/
  - .git/
```

Workflow:
1. `ast-grep scan` — run everything; stop here if clean.
2. `ast-grep scan --filter <rule-id>` — narrow to one rule when triaging.
3. `ast-grep scan --json=stream | jq ...` — machine-readable output for diff tools.
4. Before landing a rule-yaml change: `ast-grep test` — snapshot tests catch regressions.
5. Auto-fix pass: `ast-grep scan --rule rules/<id>.yml --update-all` (only rules with a `fix:` field).

Reading the output:
- Severity order: `error` > `warning` > `info` > `hint`.
- Each finding is `severity[rule-id]: message` + a file:line span.
- Exit non-zero means ≥1 error-severity finding → use in CI as a gate.
- `--no-ignore` bypasses `.gitignore` + `ignoreFiles:` (useful when auditing vendored code).

Multi-rule audits scale best when rules are **narrow and fast**:
- Use `files:` globs on each rule to scope its work (don't scan `tests/` with a production-only rule).
- Prefer `kind:` + `regex:` over a bare `pattern:` when matching identifiers — tree-sitter walk is faster than structural unification.

When results are noisy: add `ignores:` to the offending rule, or tune its `severity:` down to `hint` for audit-only use.

For writing or iterating a single rule, load `structural-rule-authoring`. For pattern syntax, load `structural-code-searching`.
