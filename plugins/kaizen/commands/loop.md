---
description: "Start (or cancel) a self-correcting Ralph loop — cross-CLI"
argument-hint: "PROMPT [--max-iterations N] [--completion-promise TEXT] | --cancel"
allowed-tools: ["Bash(${CLAUDE_PLUGIN_ROOT}/skills/loop/scripts/setup-ralph-loop.sh:*)", "Bash(test -f .kaizen/loop.state.md:*)", "Bash(rm .kaizen/loop.state.md)", "Read(.kaizen/loop.state.md)"]
---

# /kaizen:loop — self-correcting Stop-hook loop

Starts (or cancels) a Ralph-pattern self-correcting loop. The Stop hook
intercepts session exit and feeds the same prompt back until the
completion promise is emitted or `--max-iterations` is reached.

**State file:** `.kaizen/loop.state.md` (shared between Claude Code and Codex
hosts). **Stop hooks:** auto-installed via the kaizen plugin
(`hooks/claude/stop-ralph.sh` on CC, `hooks/codex/stop-ralph.sh` on Codex).

## Usage

```bash
# Start a loop
/kaizen:loop "Build a REST API for todos. Output <promise>DONE</promise> when complete." \
  --max-iterations 30 --completion-promise "DONE"

# Cancel the active loop
/kaizen:loop --cancel
```

## Behavior

1. **Start:** Writes `.kaizen/loop.state.md` with the prompt, iteration count,
   max-iterations limit, and completion-promise phrase.
2. **Iterate:** When the assistant tries to exit, the Stop hook reads the
   state file and emits `{decision: "block", reason: <prompt>}` to feed the
   same prompt back. Iteration count increments per turn.
3. **Stop:** Loop exits when the assistant emits `<promise>PHRASE</promise>`
   matching `--completion-promise`, when `--max-iterations` is reached, or
   when you run `/kaizen:loop --cancel`.

## Iron Laws

- **Always set `--max-iterations`** as a safety mechanism. The completion
  promise is exact-match — no glob, no regex.
- **Emit the promise only when the criteria are truly met.** False
  promises waste budget and corrupt the iteration data.
- **Write durable state to files.** The loop carries no in-memory context
  between iterations; the assistant relies on files + git history.
- **Loop prompts must be self-contained.** You cannot inject mid-loop.

## Behavior when invoked

If `$ARGUMENTS` is `--cancel`:

1. Check `test -f .kaizen/loop.state.md`.
2. If absent, report "No active Ralph loop found."
3. If present, read iteration via `grep '^iteration:' .kaizen/loop.state.md`,
   then `rm .kaizen/loop.state.md`. Report "Cancelled Ralph loop (was at
   iteration N)."

Otherwise, run the setup script with the given arguments:

```!
"${CLAUDE_PLUGIN_ROOT}/skills/loop/scripts/setup-ralph-loop.sh" $ARGUMENTS
```

Then begin work on the task. When you try to exit, the Stop hook will feed
the same prompt back for the next iteration. You'll see previous work in
files and git history, allowing you to iterate and improve.

**CRITICAL RULE:** If a completion promise is set, you may ONLY output it
when the statement is completely and unequivocally TRUE. Do not output
false promises to escape the loop, even if you think you're stuck or
should exit for other reasons. The loop is designed to continue until
genuine completion.

## Related

- **Workflow routine:** `/workflow schema=ralph-loop` composes the loop with
  workflow-stage discipline (verify gate between iterations).
- **Skill body:** `kaizen:loop` covers the discipline + prompt-writing
  best-practices in detail.
