---
name: agent-self-audit
description: Agent-driven follow-up to the mechanical plugin self-audit. The mechanical audit emits skill-checkpoint TODOs (load onion-ddd + each coding-skill, apply to targets); this command dispatches one subagent per checkpoint to actually load + apply each skill read-only, then aggregates their results into a consolidated report. Triggers on "agent self-audit", "apply the self-audit checkpoints", "run the skill checkpoints", "fan out the self-audit", "agent-driven plugin audit", "execute the self-audit remediation".
argument-hint: "(no args — runs the full A→B→C flow)"
---

# /kaizen:agent-self-audit

!`python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/self_audit_agent.py dispatch-plan`

The command above just ran **Phase A — dispatch-plan**: it ran the
mechanical self-audit, turned every skill-checkpoint into a
self-contained subagent brief, and wrote a `dispatch.json` manifest.
Now complete phases B and C.

## Phase B — fan out subagents (you do this)

1. **Read the manifest** at the `manifest:` path printed above. It
   has a `briefs` array — one entry per skill-checkpoint.
2. **Dispatch one subagent per brief.** For each brief, make an Agent
   tool call with:
   - `subagent_type`: the brief's `subagent_type` field
   - `description`: `"audit: apply <skill>"` (3–5 words)
   - `prompt`: the brief's `prompt` field **verbatim** — it is fully
     self-contained (skill to load, targets, focus, output path,
     result schema). Do not summarize or trim it.
3. **Run them in parallel** — put multiple Agent tool calls in one
   message — but respect the manifest's `max_parallel` cap. If there
   are more briefs than the cap, dispatch in waves.
4. Each subagent is a **read-only auditor**: it loads its Skill,
   applies it to the targets, and writes a result JSON to the
   `result_path` in its brief. It does **not** fix anything.
5. **Wait for every subagent to finish** before phase C.

## Phase C — aggregate

Run (substitute the `run_id` printed in Phase A):

    python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/self_audit_agent.py aggregate --run-id <run_id>

This reads + jsonschema-validates every subagent result, merges the
findings into one severity-sorted list, and writes the consolidated
report to `.kaizen/audits/agent/<run_id>/<utc>-agent-self.md`.

Then **present to the user**: the executive summary (checkpoints
dispatched / clean / with-findings) and the remediation plan. Do not
start fixing — remediation is a separate, user-approved step.

## Notes

- A missing or malformed subagent result is recorded by `aggregate`
  as a `medium` finding rather than aborting the run — re-dispatch
  just that one checkpoint's brief and re-run `aggregate` if needed.
- `aggregate` with no `--run-id` defaults to the most recent run.
- The three phases also run standalone via the bin wrapper:
  `kaizen-self-audit-agent dispatch-plan` / `aggregate` / `path`.
- This closes the loop the mechanical `/kaizen:self-audit` opens —
  see `skills/plugin-self-audit/SKILL.md` for how the two relate.
