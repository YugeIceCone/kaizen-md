---
name: structural-search-routing
description: Routes structural code searches or rewrites to the correct ast-grep invocation. Use for AST-level find/replace that regex cannot handle cleanly.
allowed-tools: [Bash]
version: "1.2"
---

`ast-grep` has 5 subcommands. `run` for ad-hoc, `scan` for configured rules, `test` for rule snapshots, `new` for scaffolds, `lsp` for editors.

Intent → invocation:

One-off search:
- find pattern in a tree → `ast-grep run --pattern '<pat>' --lang <lang> <path>`
- show context around hits → `ast-grep run --pattern '<pat>' --lang <lang> -C 3 <path>`
- JSON output → `ast-grep run --pattern '<pat>' --lang <lang> --json=stream <path>`
- limit to a file glob → `ast-grep run --pattern '<pat>' --lang <lang> --globs '<glob>' <path>`

One-off rewrite (**always dry-run first**):
- preview → `ast-grep run --pattern '<pat>' --rewrite '<repl>' --lang <lang> --dry-run <path>`
- apply → swap `--dry-run` for `--update-all`

Configured project (uses `sgconfig.yml`):
- run all rules → `ast-grep scan`
- one rule → `ast-grep scan --filter <rule-id>`
- apply a rule's fix → `ast-grep scan --rule rules/<id>.yml --update-all`
- snapshot-test rules → `ast-grep test`

Scaffolding a project / rule:
- new project → `ast-grep new project -y` (creates `sgconfig.yml`, `rules/`, `rule-tests/`, `utils/`)
- new rule → `ast-grep new rule <id> -l <lang> -y`

Editor integration:
- LSP server (stdio) → `ast-grep lsp`

If the user wants to **write a rule**, load `structural-rule-authoring`. For full flag / pattern reference, load `structural-code-searching`. For running the whole rule set over a repo, load `structural-project-scanning`. For the **whole scaffold→rule→test→scan→severity flow in one place**, load `structural-project-linting`. Never guess pattern syntax — metavars are `$VAR`, `$$$`, `$_` (load `structural-code-searching` if unsure).

`ast-grep` is part of the llm-tldr workflow, not a rival to it. `llm-tldr search` is a thin wrapper around `ast-grep run` for the common find case; reach for this skill when the task needs the full toolbox — rewrites (`--rewrite` + `--update-all`), file globbing (`--globs`), streaming JSON (`--json=stream`), or composite rules. For "who calls X" / "blast radius" / "dead code" / "architecture" / "import graph" questions, route through `code-graph-routing` instead.
