---
name: audit
description: "Periodic full-repo audit. Severity-classified findings (Critical/High/Medium/Low) across security, architecture, tech-debt, dependencies, coverage, docs, compliance. Writes report to .kaizen/workflow/audits/."
argument-hint: "[--scope <dir> | --no-report | --json | --agent]"
---

# kaizen audit

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/audit.sh ${ARGUMENTS}`

For per-axis audits (coverage / schema-coverage / name-quality / frontmatter / token-bloat), use `/kaizen:audit:axis <name>` — see `commands/audit/axis.md`.

## Sibling diagnostic verbs (folded surface)

The following diagnostic bins are now reachable via the audit umbrella
rather than separate slashes:

| Concern | Bin (direct) | Use case |
|---|---|---|
| Plugin self-audit pipeline | `kaizen-self-audit` | Mechanical validator + metrics-coverage + skip-detection cascade — was `/kaizen:self-audit` |
| Code-to-test coverage gaps | `kaizen-coverage gaps` | 1:1 mapping check — was `/kaizen:coverage` |
| Hygiene + auto-cleanups | `kaizen-hygiene` | Prune cache / backups / inbox TTL / logs — was `/kaizen:hygiene` (daemon also runs this on schedule) |
| Karpathy 4-principle review | `kaizen-karpathy-check` | Staged diff or `--last-commit` — was `/kaizen:karpathy-check` |
| Fast diff review | `kaizen-review` | HEAD-vs-base findings — was `/kaizen:review` |
| Vibe-coding discipline check | `kaizen-vibe-check` | Precommit + karpathy + intent triggers — was `/kaizen:vibe-check` |
| Dry-run pre-commit gate | `bash plugins/kaizen/scripts/git-hooks/pre-commit.sh` | Surface blocks/warns/skips on staged diff — was `/kaizen:precommit`. Equivalent staged-Python view: `kaizen-gatekeeper check --staged`. |
| Local CI-equivalent merge gate | `kaizen-ci-gate` | syntax + iron-laws + optional test suite — was `/kaizen:ci-gate` |
| Unified kaizen gate | `kaizen-gatekeeper` | Aggregates iron-laws + etu + karpathy + plugin-dev validate — was `/kaizen:gatekeeper` |

Surfaces for **MCP+hooks registry drift** moved into `kaizen-health`
(both are install-state diagnostics — see that command).
