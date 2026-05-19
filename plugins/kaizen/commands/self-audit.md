---
name: self-audit
description: "Plugin self-audit. Default - mechanical pipeline (validator, metrics-coverage, skip-detection, hook-trace, bin-perm, vendored, claude-md-volatile). `agent` verb fans out skill-checkpoints. Verbs - run | list-stages | path | agent."
argument-hint: "[run|list-stages|path|agent [dispatch-plan|aggregate]]"
---

# /kaizen:self-audit

Default behavior — mechanical audit. Pass `agent` to fan out subagent checkpoints.

!`bash -c 'ARGS="${ARGUMENTS:-run}"
case "$ARGS" in
  agent|agent\ *)
    AGENT_ARGS="${ARGS#agent}"
    AGENT_ARGS="$(echo "$AGENT_ARGS" | sed "s/^[[:space:]]*//")"
    python3 ${CLAUDE_PLUGIN_ROOT}/scripts/iron-laws/self_audit_agent.py ${AGENT_ARGS:-dispatch-plan}
    ;;
  *)
    python3 ${CLAUDE_PLUGIN_ROOT}/scripts/iron-laws/self_audit.py $ARGS
    ;;
esac'`

## Verbs

- (none / `run`) — Mechanical pipeline (validator → metrics →
  skip-detection → hook-trace → bin-perm → vendored →
  claude-md-volatile). Emits skill-checkpoint TODOs at the end.
- `list-stages` / `path` — pipeline introspection.
- `agent` (folded from the retired `/kaizen:agent-self-audit`) —
  dispatch one subagent per skill-checkpoint.
  - `agent dispatch-plan` (default) — runs the mechanical audit then
    writes a `dispatch.json` manifest with one self-contained
    subagent brief per checkpoint. Prints the manifest path.
  - `agent aggregate --run-id <id>` — merges every subagent's result
    into a severity-sorted report at `.kaizen/audits/agent/<id>/`.

## Agent dispatch flow (Phase B — between dispatch-plan and aggregate)

After `agent dispatch-plan` writes the manifest, dispatch one Agent
tool call per brief (in parallel, capped by `max_parallel`). Each
subagent is a read-only auditor — loads its Skill, applies to the
brief's targets, writes a result JSON to `result_path`. After every
subagent finishes, run `agent aggregate --run-id <id>` to merge.

Each brief is fully self-contained (skill to load, targets, focus,
output path, result schema) — pass it verbatim to the Agent tool's
`prompt` field. Do not summarize or trim.

A missing or malformed subagent result is recorded as a `medium`
finding rather than aborting — re-dispatch just that one brief and
re-run `aggregate` if needed.

## Backing scripts

- `scripts/iron-laws/self_audit.py` — mechanical pipeline
- `scripts/iron-laws/self_audit_agent.py` — agent dispatch + aggregate
- `bin/kaizen-self-audit`, `bin/kaizen-agent-self-audit` — direct CLI access

See `skills/plugin-self-audit/SKILL.md` for the full design contract.
