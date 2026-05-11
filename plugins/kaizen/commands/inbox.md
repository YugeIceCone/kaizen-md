---
name: inbox
description: Manage the kaizen message inbox — captures every user message via UserPromptSubmit, surfaces pending messages on the next PostToolUse boundary so Claude sees user input mid-sequence without waiting for the whole tool chain to finish. Subcommands: list | peek | drain | clear | stats. Location: ~/.claude/kaizen-inbox/.
---

# kaizen inbox

When you type while Claude is busy mid-tool-call, your message normally only reaches Claude when the WHOLE current sequence finishes. The inbox closes that gap:

1. **UserPromptSubmit hook** captures every message to `~/.claude/kaizen-inbox/<ts>.json`.
2. **PostToolUse hook** drains any pending messages on the next tool boundary, surfacing them as `additionalContext` so Claude sees them immediately.
3. Drained messages stay on disk (marked `drained: true`) as a durable audit trail.

!`python3 ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/inbox.py ${ARGUMENTS:-stats}`

## Subcommands

| arg | effect |
|---|---|
| (none) or `stats` | counts: pending / drained / total / dir |
| `list [--all]` | print pending (default) or all messages |
| `peek` | print pending WITHOUT marking drained (read-only inspect) |
| `drain` | print pending in `USER MESSAGE(S) RECEIVED WHILE BUSY:` block, mark drained |
| `clear` | remove ALL inbox files (pending + drained) — for hygiene |
| `capture <prompt> [--session SID]` | manual capture (normally the hook does this) |

## Where it lives

`$HOME/.claude/kaizen-inbox/` by default. Override via `KAIZEN_INBOX_DIR` env.

Per message: `YYYYMMDDTHHMMSSZ-NNN.json`:

```json
{
  "ts": "2026-05-11T22:50:12.123Z",
  "session_id": "<cc session uuid>",
  "prompt": "<verbatim>",
  "drained": false,
  "drained_at": null
}
```

## Why this isn't a blocker

The UserPromptSubmit hook is **non-blocking** — it exits 0 silently regardless of capture success, so your prompt always reaches Claude through the normal path. The inbox is an ADDITIONAL record + a way to nudge Claude mid-sequence. If kaizen is uninstalled, your messages still flow normally.

## Audit / debugging

`kaizen:inbox list --all` shows every message ever captured (drained or not), so you have a record of what you sent during busy times. Useful for spotting patterns ("I keep interrupting Claude on long refactors").
