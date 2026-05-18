# /kaizen:chatlog

Slice the current (or a specified) Claude Code transcript by trigger rules.
Reads `~/.claude/projects/<slug>/<sid>.jsonl`, matches events against
the rules file, writes one `.jsonl` per rule.

## Usage

```
/kaizen:chatlog slice <rules.json> <out_dir>
/kaizen:chatlog slice <rules.json> <out_dir> <transcript>
```

Defaults: `transcript` resolves from `$CLAUDE_SESSION_ID` + the project's
canonical transcript directory.

## Rules file

YAML or JSON; top-level `rules:` list. See
`skills/chatlog/domain/examples.yaml` for a working example.

## Backing CLI

`kaizen-chatlog slice --transcript <path> --rules <path> --out <dir> [--json]`

See `skills/chatlog/SKILL.md` for the full design contract and triggers.
