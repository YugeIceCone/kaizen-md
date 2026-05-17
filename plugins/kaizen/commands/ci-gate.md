---
name: ci-gate
description: "Run the CI-equivalent merge gate locally — bash/python/json/SKILL.md checks, iron-laws codegen drift, and (optionally) the full unittest suite. Static-only by default (~1s, agent-callable); pass --full to include the ~80s unittest run. Distinct from the staged pre-commit gate. Triggers on \"run the gate\", \"local CI\", \"check before push\", \"lint before commit\", \"ci-gate dry-run\"."
argument-hint: "[--full | --syntax-only]"
---

# kaizen ci-gate

Runs the same checks `.github/workflows/test.yml` runs — locally,
before the work leaves the machine.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/ci-gate.sh $ARGUMENTS`

**Default = static-only** (~1s — agent-callable). Runs steps 1-5:
shell `bash -n` parse (via glob discovery — all `*.sh` under
plugins/kaizen/), Python `ast.parse`, JSON manifest validity,
SKILL.md frontmatter, iron-laws codegen drift.

**`--full`** (or `KAIZEN_CI_GATE_FULL=1`) — adds step 6, the full
unittest suite (~80s). This is what CI runs (`.github/workflows/test.yml`
passes `--full` explicitly).

**`--syntax-only`** — alias of default (kept for back-compat).

Exit 0 = green; non-zero = the first failing check. See the `ci-gate`
skill for when to use it (end of a routine, before push/PR) and how
it differs from the staged pre-commit gate.
