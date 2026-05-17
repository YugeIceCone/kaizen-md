---
name: audit:axis
description: "Per-axis audit dispatcher. Consolidates the 5 audit-axis slash commands under the audit:axis namespace — coverage / schema-coverage / name-quality / frontmatter / token-bloat. No args = list available axes. Triggers on \"audit one axis\", \"coverage audit\", \"schema coverage gap\", \"name quality\", \"frontmatter gaps\", \"token bloat scan\", \"specific axis audit\"."
argument-hint: "[coverage | schema-coverage | name-quality | frontmatter | token-bloat | list]"
allowed-tools: ["Bash(bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/audit.sh:*)", "Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-coverage:*)", "Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-schema-coverage:*)", "Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-name-quality:*)", "Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-frontmatter:*)", "Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-token-bloat:*)"]
---

# /kaizen:audit:axis

Per-axis audit dispatcher under the audit namespace. The standalone
axis-specific slash commands (`/kaizen:coverage`, `/kaizen:schema-coverage`,
`/kaizen:name-quality`, `/kaizen:frontmatter`) remain as aliases for
back-compat.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/audit.sh axis ${ARGUMENTS:-list}`

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

## See also

- `/kaizen:audit` — whole-repo comprehensive audit (different mode)
- `/kaizen:gatekeeper check --all` — aggregated verdict across 9 sub-gates (including these 5)
