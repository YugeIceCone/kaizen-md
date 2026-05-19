---
name: self-audit
description: Schema-driven plugin self-audit. Runs mechanical checks (validator, metrics-coverage, skip-detection, hook-trace, bin-permission, vendored-modification, claude-md-volatile-data) AND emits skill-checkpoint TODOs (load onion-ddd-workflow + each of the 8 coding-skills + karpathy against declared targets). Aggregates findings, builds a remediation plan, proposes new functionality. Writes structured markdown to .kaizen/audits/. Subcommands - run [--json] [--no-write] | list-stages | path
argument-hint: [run|list-stages|path]
---

# /kaizen:self-audit

!`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/iron-laws/self_audit.py $ARGUMENTS`
