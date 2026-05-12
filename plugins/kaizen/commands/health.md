---
name: health
description: Diagnostic health check for the kaizen plugin's install in this repo. Reports broken symlinks, missing scripts, schema mismatch, hook misconfiguration, stale backlog drift, missing pre-deletion belief. Read-only; exits 1 on any error, 0 otherwise.
---

# kaizen doctor

Run a systematic diagnostic over the plugin's install state. Useful after upgrades, when commits surprise you, or when something feels off.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/doctor.sh`

## Sections covered

1. **config** — `.kaizen.toml` exists, paths it references actually resolve
2. **hook** — `core.hooksPath` set, symlink valid, target executable
3. **scripts** — all 9 kaizen scripts present + executable
4. **backlog schema** — JSON parses, `schema_version: 1`, `kind: kaizen.backlog`, items have required fields, sections are valid, `.md` ↔ `.json` drift check
5. **plugin bundle** — bundled skills count, remember scripts present
6. **memory** — brain Persona.md, pre-deletion belief, project memory dir
7. **backups** — count, latest, prune-suggestion threshold

## Exit codes

- `0` — healthy OR warnings-only (drift, accumulation, optional missing pieces)
- `1` — at least one ERROR (missing core script, broken symlink, schema invalid)

## Typical outputs

```
[ config ]
✓ .kaizen.toml present
✓ backlog source: .kaizen/workflow/backlog.json
✓ architecture log: .kaizen/workflow/progress.md
∘ verify_cmd: (none)

[ hook ]
✓ core.hooksPath = .kaizen/hooks (local)
✓ pre-commit → /home/.../plugins/kaizen/skills/kaizen/scripts/pre-commit.sh (executable)

[ scripts ]
✓ backlog.py
✓ pre-commit.sh
...

Result: healthy (no issues)
```
