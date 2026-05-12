---
name: audit
description: Periodic comprehensive audit (per the article's "code audit" definition). Whole-repo or scoped. Severity-classified findings (Critical/High/Medium/Low/Info) across security, architecture, tech-debt, dependencies, coverage, documentation, compliance. Writes a formal report to <repo>/.kaizen/workflow/audits/<UTC>-<scope>.md. Pair with /kaizen:review for per-change checks.
---

# kaizen audit

Comprehensive code audit. Per [synavos: Code Review vs Code Audit](https://synavos.com/blogs/code-review-vs-code-audit/) — **audit is periodic, comprehensive, formal-report-producing, severity-classified**. Distinct from `/kaizen:review` (per-change + lightweight + inline).

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/audit.sh ${ARGUMENTS}`

## Subcommands / flags

| Flag                   | Effect                                                       |
|------------------------|--------------------------------------------------------------|
| (none)                 | Audit whole repo. Writes formal report.                      |
| `--scope <dir>`        | Limit to a subdirectory.                                     |
| `--no-report`          | Print to stdout only; skip the file write.                   |
| `--json`               | Emit findings as JSON (for CI / dashboards).                 |
| `--agent`              | Dispatch `agent-aegis` + `kaizen-debt-auditor` in parallel.  |

## Severity classification

| Severity   | Threshold                                                                |
|------------|--------------------------------------------------------------------------|
| `critical` | Anything that breaks security / correctness in production right now.     |
| `high`     | Onion-DDD violations, hardcoded credentials, eval/exec/shell=True usage. |
| `medium`   | Coverage < 25%, missing LICENSE / README, tech-debt > 100 markers.       |
| `low`      | Stale lockfiles, density indicators, missing architecture log.           |
| `info`     | Healthy state observations, optional follow-ups.                         |

## Categories audited

- **Security** — hardcoded secrets, unsafe Rust outside ffi modules, eval/exec/shell=True in Python.
- **Architecture** — Onion-DDD inward-arrow violations (outer-ring crate imports in `crates/core`), mod-density density indicator.
- **Tech debt** — TODO/FIXME/XXX/HACK marker count, classified by density.
- **Dependencies** — lockfile staleness (>6 months), direct-dep audit hint.
- **Coverage** — test-file / source-file ratio.
- **Documentation** — README, CLAUDE.md, architecture_log presence.
- **Compliance** — LICENSE file presence.

Each category surfaces actionable next-steps in the report.

## Where the report goes

```
<repo>/.kaizen/workflow/audits/<UTC>-<scope>.md
```

Per the v1.22.0 unified layout. The file is markdown with severity-grouped headers + recommendations + a footer pointing to `/kaizen:backlog add` for filing follow-ups.

## What it does NOT do

- It's not a security scan replacement for SAST/DAST tools (Snyk, Semgrep, etc.) — pair with those.
- It doesn't run actual tests; use the project's CI for that.
- It doesn't enforce — it surfaces. Adoption is up to the team.

## When to run

- **Before a major release** — quarterly or monthly cadence per the article.
- **After a critical incident** — to find systemic gaps that caused the bug.
- **On entering a new project** — pair with `/init` + `/kaizen:onboard` for full orientation.
- **As a backlog seed** — top findings become `/kaizen:backlog add` entries with `tag=from-audit`.

## Agent dispatch (`--agent`)

When `--agent` is passed, the script suggests the slash command dispatch:

- `agent-aegis` — security threat-modeling pass
- `kaizen-debt-auditor` — architecture + tech-debt pass

Claude follows up by spawning them in parallel from the slash command body. Their outputs augment (not replace) the script's findings.

Example: `/kaizen:audit --agent --scope crates/auth`

## Examples

```
/kaizen:audit                            # whole-repo, writes report
/kaizen:audit --scope src/api            # limited scope
/kaizen:audit --no-report                # stdout only
/kaizen:audit --json                     # machine-readable
/kaizen:audit --agent --scope crates/    # full audit with agent backing
```

## Companion

- `/kaizen:review` — the per-change sibling. Run frequently.
- `agent-aegis` skill — deep security threat modeling.
- `agent-warden` skill — refactoring/migration plan review.
- `kaizen-debt-auditor` agent — onion-DDD + 8-principles tech-debt audit.

## Workflow

```
/kaizen:audit               # generate report
/kaizen:backlog add --title "..." --probe "..." --verify "..." --ref audit-<date>
# (file top-3 high-severity items as backlog entries)
```
