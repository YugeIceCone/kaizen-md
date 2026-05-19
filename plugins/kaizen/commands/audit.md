---
name: audit
description: "Periodic full-repo audit. Severity-classified findings (Critical/High/Medium/Low) across security, architecture, tech-debt, dependencies, coverage, docs, compliance. Writes report to .kaizen/workflow/audits/."
argument-hint: "[--scope <dir> | --no-report | --json | --agent]"
---

# kaizen audit

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/audit.sh ${ARGUMENTS}`

For per-axis audits (coverage / schema-coverage / name-quality / frontmatter / token-bloat), use `/kaizen:audit:axis <name>` — see `commands/audit/axis.md`.
