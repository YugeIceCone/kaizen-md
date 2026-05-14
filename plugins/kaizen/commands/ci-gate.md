---
name: ci-gate
description: Run the CI-equivalent merge gate locally — bash/python/json/SKILL.md checks, iron-laws codegen drift, and the full unittest suite. The heavy whole-repo gate; distinct from the staged pre-commit gate.
argument-hint: "[--syntax-only]"
---

# kaizen ci-gate

Runs the same checks `.github/workflows/test.yml` runs — locally,
before the work leaves the machine.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/ci-gate.sh $ARGUMENTS`

Exit 0 = green; non-zero = the first failing check. `--syntax-only`
skips the slow unittest suite. See the `ci-gate` skill for when to use
it (end of a routine, before push/PR) and how it differs from the
staged pre-commit gate.
