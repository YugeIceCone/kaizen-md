---
name: handoff
description: Create or resume a session handoff document. `/kaizen:handoff create` wraps up the current session into a YAML handoff + indexes it into the plugin's handoff store; `/kaizen:handoff resume` loads the latest handoff (or one by path/ticket), verifies the codebase still matches, and proposes a continuation plan. Thin router over the handoff skill. Triggers on "create a handoff", "resume from handoff", "wrap up this session", "hand off to next session", "save session context".
argument-hint: "[create|resume] [path-or-ticket]"
---

# /kaizen:handoff

Invoke the **handoff** skill to **$ARGUMENTS**.

- **`create`** — wrap up the current session into a thorough YAML
  handoff document, then index it into the plugin's handoff store so a
  future session resumes cleanly.
- **`resume`** — load the latest handoff (or one given by path or
  ticket), verify the codebase still matches its assumptions, and
  propose a continuation plan.

Load `Skill(kaizen:handoff)` and follow its `create` or `resume` flow
according to the argument above. If no argument was given, ask the
user which one they want.

The handoff store (`handoff.py` / `~/.claude/.kaizen/handoff.db`) is
plugin-owned — the skill's flows call it directly. The filesystem
YAML at `~/.claude/handoff/` stays the system of record.
