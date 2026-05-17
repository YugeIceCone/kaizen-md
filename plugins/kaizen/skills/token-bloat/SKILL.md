---
name: token-bloat
description: Scan everything Claude sees (yaml reason_templates / additionalContext / systemMessage, SKILL.md bodies, commands/*.md, hook heredocs) for high-token bloat. Use when wanting to audit / trim / find token bloat in the kaizen plugin's loaded content. Triggers on "token bloat", "scan for bloat", "what's bloated", "find verbose templates", "audit token use", "trim hooks", "context cost", "what's burning my context", "kaizen-token-bloat". Auto-fires from SessionEnd (cache TTL 6h); SessionStart surfaces top finding as one-line additionalContext when findings exist.
---

# kaizen token-bloat

Mechanical scanner that finds high-token content in places the agent
loads at runtime — yaml templates that burn into context on every
fire, SKILL.md bodies that load in full, multi-line hook heredocs that
get injected as additionalContext.

## What it scans

| Source | Trigger | Why |
|---|---|---|
| `skills/*/domain/*.yaml` | `reason_template` / `additionalContext` / `systemMessage` / `reason` keys with `|` block scalar | Every Stop/intake/notification hook fire dumps these into agent context |
| `skills/*/SKILL.md` | size threshold (default 400 lines med, 800 high) | SKILL.md loads in full when the skill is invoked |
| `commands/*.md` | size threshold (default 100 lines med, 200 high) | Slash-command body appends to user prompt |
| `hooks/claude/*.sh` | `body=''' ... '''` multi-line strings | Hooks emit these as additionalContext/systemMessage |

## CLI

```bash
kaizen-token-bloat scan           # full scan, print results
kaizen-token-bloat scan --cache   # also write cache for SessionStart surface
kaizen-token-bloat scan --json    # machine-readable
kaizen-token-bloat report         # read last cache
kaizen-token-bloat surface        # one-line summary (empty when clean / stale)
```

## Auto-invocation

- **SessionEnd hook** runs `scan --cache` in background (~200ms).
  Writes findings to `$KAIZEN_DIR/token-bloat-findings.json`.
- **SessionStart hook** runs `surface` — reads the cache and emits
  one-line `additionalContext` ONLY when findings exist AND cache is
  fresh (TTL `KAIZEN_TOKEN_BLOAT_TTL_HOURS`, default 6h). Zero noise
  when the plugin is clean.

The user never has to run anything — findings surface on the next
session start with a clear one-liner.

## Thresholds (env-overridable)

```
KAIZEN_BLOAT_YAML_LINES_HIGH    default 15
KAIZEN_BLOAT_YAML_LINES_MED     default 8
KAIZEN_BLOAT_SKILLMD_LINES_HIGH default 800
KAIZEN_BLOAT_SKILLMD_LINES_MED  default 400
KAIZEN_BLOAT_CMDMD_LINES_HIGH   default 200
KAIZEN_BLOAT_CMDMD_LINES_MED    default 100
KAIZEN_BLOAT_HOOK_LINES_HIGH    default 40
KAIZEN_BLOAT_HOOK_LINES_MED     default 20
KAIZEN_TOKEN_BLOAT_TTL_HOURS    default 6
KAIZEN_TOKEN_BLOAT_DISABLE      bypass (skips both hooks)
```

## Output shape

```
kaizen-token-bloat: 9 finding(s) — 5 high, 4 medium
  ▲ [high  ] skill-md       skills/onion-ddd-workflow/SKILL.md::(body)  809 lines (~13614 tok)
  ▲ [high  ] hook-heredoc   hooks/claude/session-intake.sh::body=''' ... '''  88 lines (~1078 tok)
  ...
```

## How to act on findings

| Finding kind | Typical fix |
|---|---|
| `yaml-template` | Trim the template; agent has the skill loaded, doesn't need re-teaching |
| `skill-md` | Split into `references/*.md` (loaded on demand) or trim prose |
| `command-md` | Move docs to the linked skill; keep command body to dispatch + minimal usage |
| `hook-heredoc` | Move the long context to a skill description; hook emits a one-line trigger |

## Pairs with

- `kaizen-coverage` — both are mechanical scanners over plugin content
- `kaizen-gatekeeper` — broader pre-commit gate; token-bloat is the periodic
  content-shape audit
- `kaizen-metrics skips` — runtime adoption signal; token-bloat is the
  static-content cost signal
