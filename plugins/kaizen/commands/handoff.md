---
name: handoff
description: "Session handoff doc. `create` wraps the current session into YAML + indexes it; `resume` loads latest (or by path/ticket), verifies state, proposes continuation. Triggers - "create handoff", "resume from handoff", "wrap up session"."
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
