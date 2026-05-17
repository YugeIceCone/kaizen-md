---
name: ast-grep-code
description: Provides exact flags, pattern syntax, and rule schemas for structural code search with ast-grep. Use to ensure correct syntax for patterns and rules.
allowed-tools: [Bash]
version: "1.2"
---

Binary: `ast-grep` (alias `sg`). Project config: `sgconfig.yml` (see `structural-project-scanning` for layout).

Subcommands:
- `run [OPTS] <PATH>` — one-off search / rewrite via `--pattern` + `--lang`
- `scan [OPTS]` — runs every rule listed under `ruleDirs:` in `sgconfig.yml`
- `test [OPTS]` — snapshot tests against rule fixtures in `testConfigs.testDir`
- `new {project|rule|test|util} [NAME]` — scaffold (pass `-y` for non-interactive)
- `lsp` — stdio LSP server (reads `sgconfig.yml`)

Common `run` / `scan` flags:
- `--pattern '<pat>'` / `-p` — pattern (run only)
- `--rewrite '<repl>'` — replacement (run only)
- `--update-all` — apply rewrites
- `--dry-run` — preview rewrites without writing
- `--lang <LANG>` / `-l` — rust | python | typescript | javascript | go | java | c | cpp | csharp | html | css | json | yaml | bash | lua | php | ruby | swift | kotlin | dart | scala
- `--globs '<glob>'` — file glob (repeatable)
- `--context N` / `-C N` — lines of context around matches
- `--json[=compact|pretty|stream]` — JSON output (stream = NDJSON, best for piping)
- `--filter <id>` — scan only the rule with this id
- `--rule <path>` — scan with a specific rule file (bypass `ruleDirs`)
- `--no-ignore` — don't respect `.gitignore` / `ignoreFiles`

Pattern syntax (structural, AST-aware — **not regex**):
- `$NAME` — single node; same name matches the same node twice (back-reference)
- `$$$NAME` — list of nodes (arguments, statements, etc.)
- `$_` — wildcard single node, no capture
- `$$$_` — wildcard list, no capture
- literal tokens in the pattern must parse as valid source in `--lang`

Examples:
- `foo($ARG)` — a call to `foo` with exactly one arg, captured as `$ARG`
- `foo($$$ARGS)` — any-arity call, capture the arg list
- `fn $NAME($$$) { $$$BODY }` — any Rust fn, capture name + body
- `console.log($$$)` — any `console.log` call

Rule YAML (files under `rules/*.yml`):
```yaml
id: no-foo-in-bar              # unique id
language: Rust                 # capitalized language name
severity: warning              # hint | info | warning | error
message: "short one-liner"
note: |
  multi-line rationale that shows up in LSP hover.
files:                         # optional — glob allowlist
  - "crates/*/src/**/*.rs"
ignores:                       # optional — glob denylist
  - "**/tests/**"
rule:                          # the matcher
  pattern: foo()
  # or composite:
  any:
    - pattern: a()
    - pattern: b()
  # inside / has / follows / precedes / not for positional constraints
fix: bar()                     # optional — auto-fix replacement
```

Composite rule keys:
- `pattern:` — literal pattern string
- `any: [rule1, rule2]` — OR
- `all: [rule1, rule2]` — AND
- `not: rule` — negation
- `inside: rule` — match only when ancestor matches
- `has: rule` — match only when a descendant matches
- `follows: rule` / `precedes: rule` — sibling-order constraint
- `kind: identifier` — match a tree-sitter node kind directly
- `regex: '^foo'` — regex filter on the matched text (combine with `kind:` for speed)

Severity levels in YAML map to LSP: `hint` (subtle), `info` (noted), `warning` (attention), `error` (must-fix).

For whole-project workflows, load `structural-project-scanning`. For writing / iterating a single rule, load `structural-rule-authoring`.
