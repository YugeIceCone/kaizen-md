---
name: plugin-self-audit
description: Schema-driven plugin self-audit pipeline. Mechanical checks + skill-checkpoint TODOs (onion-ddd + 9 coding-skills). Triggers on "audit the kaizen plugin", "self-audit", "plugin health check", "find gaps in kaizen", "plugin coverage audit", "what should I fix in kaizen", "structured audit report", "remediation plan for kaizen", "what new functionality should kaizen have", "kaizen onion-ddd review", "review kaizen for solid/dry/kiss".
version: 1.0.0
---

# Plugin self-audit

## ⚠ Iron Law — read in full

The audit produces a structured report; the agent then APPLIES the
skill-checkpoints. Skipping the apply phase = the audit was useless.
The mechanical checks are reproducible; the skill checks are agent
judgment + skill body authority.

## What this is

A Node+Flow pipeline that audits the kaizen plugin against:

1. **Its own canonical shape** (plugin-development validator)
2. **Adoption signals** (kaizen-metrics never-used + skips)
3. **Wiring gaps** (hooks-trace coverage, bin/permission coverage)
4. **Discipline violations** (vendored-modification, claude-md-volatile-data)
5. **Architectural soundness** (onion-ddd-workflow checkpoint)
6. **Code-quality principles** (the 8 coding-skills + karpathy checkpoints)

Output: structured markdown report at
`.kaizen/audits/<UTC>-self.md` with:

- Executive summary (counts by severity / kind)
- Mechanical findings (concrete violations)
- Skill checkpoints (agent-action TODOs)
- Remediation plan (one task per actionable finding)
- New-functionality suggestions (heuristic emergence from finding patterns)

## Quick reference

```
/kaizen:self-audit run                     # full audit + write report
/kaizen:self-audit run --json              # machine-readable
/kaizen:self-audit run --no-write          # don't persist (preview only)
/kaizen:self-audit list-stages             # show pipeline yaml
/kaizen:self-audit path                    # report dir + pipeline path

kaizen-self-audit                          # bare = run
kaizen-self-audit list-stages              # via bin wrapper
```

## Pipeline shape (Node+Flow)

```
LoadPipelineNode
   ↓
RunMechanicalStagesNode  (parallel batch — concurrency=4)
   ↓
EmitSkillCheckpointsNode
   ↓
AggregateFindingsNode    (de-dup + severity sort)
   ↓
BuildRemediationPlanNode
   ↓
ProposeNewFunctionalityNode  (heuristic rule-based)
   ↓
WriteReportNode
```

The pipeline is declared in `domain/audit-pipeline.yaml`. Edit yaml
to add stages; the runner dispatches on stage `runner` field.

## Mechanical stages — always-run

| stage | What it checks |
|---|---|
| `validator` | plugin-development validate.py --all (canonical shape) |
| `metrics-coverage` | never-used skills/MCPs/bins (adoption %) |
| `metrics-skips` | skill-skips for the latest session |
| `hook-trace-coverage` | every hook fires `_trace.sh` or `trace.py event` |
| `bin-permission-coverage` | every bin/kaizen-* has plugin.json permission |
| `vendored-modification-detect` | git diff over vendored skill dirs |
| `claude-md-volatile-data` | CLAUDE.md / README.md against volatile-data rule |

## Skill checkpoints — agent applies after report

| stage | Skill | Targets |
|---|---|---|
| `onion-ddd-checkpoint` | onion-ddd-workflow | skills/workflow/scripts/ |
| `kiss-checkpoint` | kiss | scripts/ |
| `dry-checkpoint` | dry | scripts/ |
| `yagni-checkpoint` | yagni | scripts/ |
| `solid-checkpoint` | solid | scripts/ |
| `separation-of-concerns-checkpoint` | separation-of-concerns | plugins/kaizen/ |
| `law-of-demeter-checkpoint` | law-of-demeter | scripts/ |
| `boy-scout-checkpoint` | boy-scout-rule | plugins/kaizen/ |
| `convention-checkpoint` | convention-over-configuration | plugins/kaizen/ |
| `karpathy-checkpoint` | karpathy | scripts/ |
| `verification-before-completion-checkpoint` | verification-before-completion | scripts/ + tests/ |
| `writing-plans-checkpoint` | writing-plans | plans/ + plugin-development SKILL.md |
| `executing-plans-checkpoint` | executing-plans | plans/ + .kaizen/workflow/ |

The audit DOES NOT load + apply these skills itself — they're
LLM-applied, not script-executable. The audit emits one Finding
per checkpoint with `kind: checkpoint` and `skill:` set; the agent
loads the skill and applies it to the targets, then re-runs the
audit to compare findings.

## Why mechanical + checkpoint split

Mechanical = reproducible (run on every CI commit; same result every time).
Checkpoint = judgment (only an LLM with the skill loaded can apply it
faithfully). Forcing both into one form would either over-promise
(claim the script applies KISS — it doesn't) or under-deliver
(skip skill-judgment entirely).

## New-functionality proposals

`ProposeNewFunctionalityNode` walks the findings and applies
heuristic rules to suggest emergent extensions. Current rules:

- Many never-used skills → propose `kaizen-metrics graveyard` auto-archiver
- Bin/permission gaps → propose pre-commit gate for the diff
- Hook-trace gaps → propose adding `every-hook-script-traces-its-firing`
  iron law
- Skill-checkpoint findings → propose `agent-self-audit` (LLM-driven follow-up)
- Never-used MCP → propose `kaizen-metrics smoke --kind mcp` smoke-tester

Rules are intentionally rule-based (not LLM) so the audit is
reproducible. Add new rules in `ProposeNewFunctionalityNode` as
patterns emerge.

## Severity model

Five levels (ordered low→high):
- `info` — informational only; not in remediation plan
- `low` — soft warnings (e.g. canonical-shape soft hits)
- `medium` — adoption gaps, skill-skips, missing permissions
- `high` — vendored modifications, validator hard fails
- `critical` — reserved for security / data-loss issues

Remediation plan excludes `info` findings.

## Output location

Reports land at `.kaizen/audits/<UTC>-self.md` in the cwd repo
(typically the kaizen-md repo when auditing the plugin itself, or
the consumer repo when running there). The `--no-write` flag
returns the markdown without persisting.

## When to run

- **Before shipping a feature** — ensure no soft warnings on the new code
- **After landing structural changes** — confirm wiring coverage
- **Periodic** (weekly?) — track adoption + skill usage drift
- **On-demand** — when something feels off

The slash command + bin wrapper make on-demand cheap.

## Agent-self-audit — the checkpoint executor

The mechanical audit *emits* skill checkpoints; it cannot *apply*
them (skill bodies are LLM judgment, not script-executable).
`agent-self-audit` closes that loop in three phases:

| Phase | Owner | What |
|---|---|---|
| A · `dispatch-plan` | `self_audit_agent.py` | Run the mechanical audit, render one self-contained subagent brief per checkpoint Finding, write `dispatch.json`. |
| B · fan-out | the orchestrating **agent** | Dispatch one subagent per brief via the Agent tool — each loads its Skill, applies it read-only, writes a result JSON. |
| C · `aggregate` | `self_audit_agent.py` | jsonschema-validate every result, merge into a unified Finding list, write `<utc>-agent-self.md`. |

Python owns A + C (mechanical, reproducible); the agent owns B — the
Agent tool is agent-runtime-only, so the fan-out cannot be scripted.

```
/kaizen:agent-self-audit                          # full A→B→C playbook
kaizen-self-audit-agent dispatch-plan [--json]    # phase A standalone
kaizen-self-audit-agent aggregate [--run-id ID]   # phase C standalone
kaizen-self-audit-agent path                      # dirs + config paths
```

Runs land in `.kaizen/audits/agent/<run-id>/` — `dispatch.json`, one
`<checkpoint-id>.json` per subagent, and the consolidated report.
Phase A's briefs are schema-driven: edit `domain/agent-dispatch.yaml`
(subagent type, prompt template, severity hint) to retune them — no
Python change. Subagent output is validated against
`domain/schemas/checkpoint-result.schema.json`; a missing or
malformed result becomes a `medium` finding rather than aborting.
