---
name: menu
description: List all /kaizen:* slash commands with brief descriptions + suggested first-time onboarding flow. Run this any time to recall what's available.
---

# kaizen — command reference

## Commands

| Command | Purpose |
|---|---|
| `/kaizen:install` | Activate the pre-commit gate in this repo (local-only, idempotent) |
| `/kaizen:uninstall` | Reverse install (dry-run default; preserves backlog + backups) |
| `/kaizen:health` | Health diagnostic — broken symlinks, schema mismatch, missing scripts |
| `/kaizen:status` | At-a-glance: config, hook, backlog, active routine, backups |
| `/kaizen:gate` | Dry-run the pre-commit gate against staged changes |
| `/kaizen:backlog` | List / add / start / tick / park / decision / render / verify backlog items |
| `/kaizen:migrate` | Scan + retire loose duplicates / marketplaces; convert hand-written BACKLOG.md |
| `/kaizen:backup` | Create / list / restore / prune workflow-state snapshots |
| `/kaizen:disable-dupes` | Reversibly disable loose-side duplicate skills (rename SKILL.md ↔ SKILL.md.disabled) |
| `/kaizen:test` | Run the full pipeline test (TAP-style, 29+ checks, ~1s, low token cost) |
| `/kaizen:flow` | Run the pocketflow Node+Flow demo against the current backlog (offline, no LLM) |
| `/kaizen:menu` | This reference |

## MCP server

Auto-loaded via the plugin's `.mcp.json` — exposes 10 backlog tools (list / show / add / start / tick / park / unpark / decision / render / verify) so any MCP client can drive the backlog programmatically. Requires `pip install fastmcp` once.

## First-time onboarding (3 steps)

```
1. /kaizen:install              # activate per-repo hooks + config
2. /kaizen:disable-dupes        # see which loose skills duplicate plugin bundle
3. /kaizen:status               # confirm everything green
```

After that, commit normally — the pre-commit gate fires automatically.

## Recommended cadence

| When | Command |
|---|---|
| After plugin update | `/kaizen:health` to surface any breakage |
| Before risky operation | `/kaizen:backup create --label <what>` |
| When sizing a new task | `/kaizen:backlog add` with probe + verify hooks |
| End of week | `/kaizen:backup prune --keep 10` |
| Before retiring loose skills | `/kaizen:disable-dupes` then `/kaizen:migrate retire-loose-skill <name>` |

## Skill bundle (reminder)

The plugin bundles **32 skills** under the `kaizen:` namespace. See `/plugin info kaizen@kaizen-md` for the full list and `ATTRIBUTIONS.md` for credits to original authors (Jordan Coin Jackson / Jesse Vincent / Gabi Fratica).

## Iron Laws

- **Size by trace + sem + grep, never clock-time.** `Notes/pref-sizing-by-trace-not-hours.md`
- **One BACKLOG.json source of truth.** `.md` is generated.
- **Same-commit discipline.** Structural change + architecture-log row in one commit.
- **Pre-deletion gate non-negotiable.** `git rm` triggers belief scan unless explicitly authorized.
- **Read this skill in full every time.** No "I remember it" shortcut.
