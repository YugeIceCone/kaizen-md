---
name: audit
description: Periodic comprehensive audit (per the article's "code audit" definition). Whole-repo or scoped. Severity-classified findings (Critical/High/Medium/Low/Info) across security, architecture, tech-debt, dependencies, coverage, documentation, compliance. Writes a formal report to <repo>/.kaizen/workflow/audits/<UTC>-<scope>.md. Pair with /kaizen:review for per-change checks.
argument-hint: [--scope <dir>|--no-report|--json|--agent]
---

# kaizen audit

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/audit.sh ${ARGUMENTS}`
