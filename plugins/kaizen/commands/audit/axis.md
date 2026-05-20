---
name: audit:axis
description: "Per-axis audit dispatcher. Consolidates the 5 axis-specific commands under the audit:axis namespace — coverage / schema-coverage / name-quality / frontmatter / token-bloat. No args → multiSelect AskUserQuestion checklist (pick any subset to audit in one pass). With single axis name → direct dispatch. Triggers on \"audit some axes\", \"coverage audit\", \"schema coverage gap\", \"name quality\", \"frontmatter gaps\", \"token bloat scan\", \"audit menu\"."
argument-hint: "(empty = multi-axis checklist) | [coverage | schema-coverage | name-quality | frontmatter | token-bloat | list]"
allowed-tools: ["AskUserQuestion", "Bash(bash ${CLAUDE_PLUGIN_ROOT}/scripts/ops/audit.sh:*)", "Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-coverage:*)", "Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-schema-coverage:*)", "Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-name-quality:*)", "Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-frontmatter:*)", "Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-token-bloat:*)"]
---

# /kaizen:audit:axis

Per-axis audit dispatcher under the audit namespace. The standalone
axis-specific slash commands (`/kaizen:coverage`, `/kaizen:schema-coverage`,
`/kaizen:name-quality`, `/kaizen:frontmatter`) remain as aliases for
back-compat.

!`bash ${CLAUDE_PLUGIN_ROOT}/scripts/ops/audit.sh axis ${ARGUMENTS:-list}`

## Available axes

| Axis | What it checks | Backing bin |
|---|---|---|
| `coverage` | 1:1 script ↔ test-file presence | `kaizen-coverage` |
| `schema-coverage` | Feature-shape conformance (4 canonical shapes) | `kaizen-schema-coverage` |
| `name-quality` | Filename ↔ docstring intent match | `kaizen-name-quality` |
| `frontmatter` | SKILL.md name + ≥3 quoted trigger phrases | `kaizen-frontmatter` |
| `token-bloat` | High-cost low-value content (skills/commands/hooks) | `kaizen-token-bloat` |
| `list` | (default) list available axes | — |

## Pass-through args

Anything after the axis name is forwarded to the backing bin:

```
/kaizen:audit:axis coverage report         → kaizen-coverage report
/kaizen:audit:axis schema-coverage --json  → kaizen-schema-coverage --json
/kaizen:audit:axis token-bloat scan        → kaizen-token-bloat scan
```

Default verb per axis (when no extra args):
- `coverage / schema-coverage / name-quality / frontmatter` → `gaps`
- `token-bloat` → `scan`

## Interactive multi-axis checklist (when `$ARGUMENTS` is empty)

The body above runs `audit.sh axis list` on empty args (prints the
table). The agent SHOULD ALSO walk the user through a 1-question
multiSelect AskUserQuestion so they can pick ANY subset of axes to
audit in a single pass:

```
question:    "Which audit axes? (pick multiple)"
header:      "Axes"
multiSelect: true
options:
  - label: "coverage"
    description: "1:1 script ↔ test-file presence (kaizen-coverage gaps)"
  - label: "schema-coverage"
    description: "Feature-shape conformance against the 4 canonical shapes"
  - label: "name-quality"
    description: "Filename ↔ docstring intent match"
  - label: "frontmatter"
    description: "SKILL.md name + ≥3 quoted trigger phrases"
```

Token-bloat omitted from the multi-pick (it's the only one whose
default verb is `scan`, not `gaps`; runs differently — invoke directly
via `/kaizen:audit:axis token-bloat` if you want it).

### After the user picks

For each chosen axis, RE-INVOKE: `/kaizen:audit:axis <axis>` and
collate the per-axis verdicts in one summary. Format:

```
=== multi-axis audit ===
coverage         → <result>
schema-coverage  → <result>
name-quality     → <result>
frontmatter      → <result>
```

If the user picks ZERO axes, fall back to printing the `axis list`
output (current default).

## See also

- `/kaizen:audit` — whole-repo comprehensive audit (different mode)
- `kaizen-gatekeeper check --all` — aggregated verdict across every registered sub-gate (including these 5 axes); `kaizen-gatekeeper list` shows the live registry
