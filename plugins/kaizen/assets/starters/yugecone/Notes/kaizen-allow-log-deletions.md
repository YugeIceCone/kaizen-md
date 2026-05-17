---
name: kaizen-allow-log-deletions
description: Allow `git rm` of *.log files anywhere without KAIZEN_ALLOW_DELETE — they're transient
type: behaviour
tags: [kaizen, deletion-allow]
sources_count: 1
freshness: stable
created: {{today}}
updated: {{today}}
kaizen:
  rule_type: deletion-allow
  path_glob: "**/*.log"
---

# Allow log-file deletions

Log files are runtime artifacts. Deleting them shouldn't require the
same authorization gate as production code. This rule is the
canonical EXAMPLE of a kaizen-rule note — a Markdown file with a
`kaizen:` frontmatter block that the pre-commit gate consults.

## Why this matters

The kaizen pre-commit gate blocks `git rm` by default (per
`pref-no-deletions`). For low-risk file classes (logs, build
artifacts, *.tmp), you want a blanket allowlist so the gate doesn't
slow you down.

## How rule notes work

The `kaizen:` block in the frontmatter declares:
- `rule_type` — one of `deletion-allow` / `check-severity` /
  `custom-pattern` / `dependency-allowlist`
- Type-specific fields (here: `path_glob` is the glob for matching
  paths)

At commit time, `kaizen-rules` reads every Note with a `kaizen:`
block and applies it. List all your active rules:

```bash
kaizen-rules list
```

## Customize this rule

The `path_glob` is intentionally narrow (`**/*.log`). To extend to
other transient classes for your projects, edit the YAML frontmatter
or add SIBLING notes (one rule per file):

```yaml
kaizen:
  rule_type: deletion-allow
  path_glob: "**/*.tmp"      # or "target/**", "dist/**", etc.
```

Generate templates for other rule types:

```bash
kaizen-rules template check-severity
kaizen-rules template custom-pattern
kaizen-rules template dependency-allowlist
```
