---
name: auto-handoff
description: "Forces a handoff before /compact when context usage crosses the user-chosen threshold. Schema-driven config + Stop-hook decision=block contract — once it fires, the agent CANNOT stop until the handoff is created. Triggers on \"auto handoff\", \"context-pressure handoff\", \"pre-compact handoff\", \"context threshold trigger\"."
version: 1.0.0
---

# Auto-Handoff — context-pressure → forced handoff

## Contract

When this hook fires, the agent's Stop is **BLOCKED** until a handoff
is created. The block reason is injected as the next-turn prompt, so
the agent receives an imperative directive to complete the handoff
before it can release.

This is intentionally NOT advisory — `systemMessage` was the prior
design, but Claude could skip the suggestion. `decision=block` cannot
be skipped: the assistant literally cannot exit until handoff lands
(or the user manually overrides via `KAIZEN_AUTO_HANDOFF_DISABLE=1`).

## Configuration

Driven by `domain/config.yaml`. Validated against
`domain/schemas/config.schema.json`. Overridable via env:

  `KAIZEN_AUTO_HANDOFF_CONFIG` → path to user-tweaked config.yaml

Defaults:

```yaml
version: 1
valid_thresholds: [25, 50, 75, 85]
dedupe_event_type: "auto_handoff.requested"
on_fire:
  decision: "block"      # block | systemMessage
  reason_template: |     # available vars: {pct} {threshold}
    ⚠ MANDATORY pre-compact handoff (context at {pct}%, threshold {threshold}%).
    …
```

## Fires once per session

A dxm event (`auto_handoff.requested` by default) is written the first
time the threshold is crossed. Subsequent invocations see the marker
and no-op — preventing repeat blocks within the same session.

## Bypass

`KAIZEN_AUTO_HANDOFF_DISABLE=1` — full opt-out (the hook returns `{}`
immediately, no threshold check, no block).

## Source of truth for threshold

The threshold value comes from the **session-mode state**
(`.kaizen/session-mode.json::auto_handoff_threshold`), set at session
intake via `/kaizen:workflow` (Q1 = "This session only" — folded
from the retired `/kaizen:session-mode` slash) or the SessionStart
QA. Valid values are
the four levels declared in this skill's config: 25 / 50 / 75 / 85.
`None` (or unset) = auto-handoff disabled.

## See also

- `skills/handoff/SKILL.md` — the handoff create/resume flow that
  the agent is forced to invoke when this fires
- `skills/workflow/scripts/auto_handoff.py` — the implementation
- `hooks/claude/auto-handoff.sh` — the Stop-hook wire
